# -*- coding: utf-8 -*-
"""database.py - Lớp dữ liệu trung tâm: SQLite (cache + chỉ mục tìm kiếm cục bộ).

Thiết kế:
- MỌI thao tác ghi đều đi qua ``Database.write()`` -> ``BEGIN IMMEDIATE`` (khóa ghi ở mức DB)
  kết hợp khoá process (threading.RLock) => chống ghi đồng thời giữa các thread / tiến trình.
- Chống trùng phòng được CỦNG Ở TẦNG DỮ LIỆU bằng unique index (building_id, unit_key)
  nên dù kiểm tra trùng ở tầng nghiệp vụ có bỏ sót, DB vẫn chặn bản ghi trùng.
- Google Sheets là nguồn trung tâm nhưng KHÔNG chặn giao diện: DB luôn sẵn sàng (offline-first).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config import DB_FILE, now_iso, get_settings
from logger import get_logger

log = get_logger("db")

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buildings (
    id            TEXT PRIMARY KEY,
    code          TEXT NOT NULL,
    house_number  TEXT NOT NULL DEFAULT '',
    street        TEXT NOT NULL DEFAULT '',
    ward          TEXT NOT NULL DEFAULT '',
    district      TEXT NOT NULL DEFAULT '',
    display       TEXT NOT NULL DEFAULT '',
    address_key   TEXT NOT NULL,
    owner_name    TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    zalo_group    TEXT NOT NULL DEFAULT '',
    ev_policy     TEXT NOT NULL DEFAULT '',
    pet_policy    TEXT NOT NULL DEFAULT '',
    commission    TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    search_norm   TEXT NOT NULL DEFAULT '',
    external_ref  TEXT NOT NULL DEFAULT '',
    sync_state    TEXT NOT NULL DEFAULT 'local',
    version       INTEGER NOT NULL DEFAULT 0,
    deleted       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    updated_by    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_buildings_address ON buildings(address_key) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS ix_buildings_street ON buildings(street);

CREATE TABLE IF NOT EXISTS rooms (
    id            TEXT PRIMARY KEY,
    building_id   TEXT NOT NULL,
    room_code     TEXT NOT NULL DEFAULT '',
    room_code_key TEXT NOT NULL DEFAULT '',
    unit_code     TEXT NOT NULL DEFAULT '',
    unit_key      TEXT NOT NULL DEFAULT '',
    floor         TEXT NOT NULL DEFAULT '',
    room_type     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'new',
    surveyed      INTEGER NOT NULL DEFAULT 0,
    price         INTEGER NOT NULL DEFAULT 0,
    deposit       INTEGER NOT NULL DEFAULT 0,
    capacity      TEXT NOT NULL DEFAULT '',
    ev_support    INTEGER NOT NULL DEFAULT 0,
    pet_policy    TEXT NOT NULL DEFAULT '',   -- GIỮ NGUYÊN văn bản gốc từ Excel
    pet_ok        INTEGER NOT NULL DEFAULT 0, --1 = cho nuôi (dùng cho lọc/tìm kiếm)
    rating        TEXT NOT NULL DEFAULT '',
    owner_phone   TEXT NOT NULL DEFAULT '',
    zalo_group    TEXT NOT NULL DEFAULT '',
    drive_link    TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    needs_verify  INTEGER NOT NULL DEFAULT 0,
    search_norm   TEXT NOT NULL DEFAULT '',
    external_ref  TEXT NOT NULL DEFAULT '',
    sync_state    TEXT NOT NULL DEFAULT 'local',
    version       INTEGER NOT NULL DEFAULT 0,
    deleted       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    updated_by    TEXT NOT NULL DEFAULT ''
);
-- Khoá nhận diện căn hộ = Mã tòa nhà (địa chỉ) + Số căn thực tế (fallback: mã phòng)
CREATE UNIQUE INDEX IF NOT EXISTS ux_rooms_identity
    ON rooms(building_id, unit_key) WHERE deleted = 0 AND unit_key <> '';
CREATE INDEX IF NOT EXISTS ix_rooms_building ON rooms(building_id);
CREATE INDEX IF NOT EXISTS ix_rooms_status   ON rooms(status);
CREATE INDEX IF NOT EXISTS ix_rooms_price    ON rooms(price);
CREATE INDEX IF NOT EXISTS ix_rooms_code     ON rooms(room_code_key);
CREATE INDEX IF NOT EXISTS ix_rooms_type     ON rooms(room_type);
CREATE INDEX IF NOT EXISTS ix_rooms_updated  ON rooms(updated_at);

CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     TEXT NOT NULL,
    old_status  TEXT NOT NULL DEFAULT '',
    new_status  TEXT NOT NULL DEFAULT '',
    changed_at  TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_hist_room ON status_history(room_id);

CREATE TABLE IF NOT EXISTS sync_queue (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    idem_key       TEXT NOT NULL UNIQUE,   -- chống gửi trùng lệnh (idempotency)
    entity         TEXT NOT NULL,          -- room | building | stats
    entity_id      TEXT NOT NULL DEFAULT '',
    op             TEXT NOT NULL,          -- upsert | delete | append
    payload        TEXT NOT NULL DEFAULT '{}',
    state          TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed|conflict
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_queue_state ON sync_queue(state, next_attempt_at);

CREATE TABLE IF NOT EXISTS locks (
    name       TEXT PRIMARY KEY,
    token      TEXT NOT NULL,
    owner      TEXT NOT NULL DEFAULT '',
    expires_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_batches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    total      INTEGER NOT NULL DEFAULT 0,
    added      INTEGER NOT NULL DEFAULT 0,
    updated    INTEGER NOT NULL DEFAULT 0,
    skipped    INTEGER NOT NULL DEFAULT 0,
    suspect    INTEGER NOT NULL DEFAULT 0,
    errors     INTEGER NOT NULL DEFAULT 0,
    actor      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS id_map (            -- ánh xạ ID nội bộ <-> dòng trên Google Sheets
    room_id     TEXT PRIMARY KEY,
    entity      TEXT NOT NULL DEFAULT 'room',
    sheet       TEXT NOT NULL DEFAULT '',
    row_number  INTEGER NOT NULL DEFAULT 0,
    remote_ver  INTEGER NOT NULL DEFAULT 0,
    local_ver   INTEGER NOT NULL DEFAULT 0,
    remote_hash TEXT NOT NULL DEFAULT '',      -- nội dung ta đã ghi lần cuối lên Sheets
    local_hash  TEXT NOT NULL DEFAULT '',
    remote_at   TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
"""


def row_to_dict(row) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


class Database:
    """Singleton logic: một kết nối + khoá RLock (an toàn với thread của Qt/worker)."""

    _instance: Optional["Database"] = None
    _instance_lock = threading.Lock()

    def __init__(self, path: Optional[str] = None, create: bool = True):
        self.path = str(path or get_settings().get("db_path") or DB_FILE)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data_version = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=10000")
        if create:
            self.migrate()

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def instance(cls) -> "Database":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                except Exception:
                    pass
                cls._instance = None

    def migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            ver = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if ver != SCHEMA_VERSION:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._data_version += 1

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ primitives
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def data_version(self) -> int:
        """Tăng mỗi khi dữ liệu đổi -> dùng invalidate cache tìm kiếm."""
        return self._data_version

    def query(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    @contextmanager
    def write(self):
        """Khóa ghi tập trung: BEGIN IMMEDIATE -> commit/rollback.

        Mọi ghi dữ liệu nghiệp vụ PHẢI đi qua đây (mục 5 - chống ghi đồng thời).
        """
        self._lock.acquire()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield self._conn
            self._conn.execute("COMMIT")
            self._data_version += 1
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self._lock.release()

    def write_lock(self, name: str, ttl_sec: float = 30.0, owner: str = "") -> Optional[str]:
        """Khóa ghi có hạn (lease) - dùng cho thao tác cần ngăn tiến trình khác.

        Trả về token nếu giành được khoá, None nếu khoá đang bị giữ.
        """
        token = f"{owner}:{time.time_ns()}"
        now = time.time()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT token, expires_at FROM locks WHERE name=?", (name,)).fetchone()
                if row and row["expires_at"] > now and row["token"] != token:
                    self._conn.execute("ROLLBACK")
                    return None
                self._conn.execute(
                    "INSERT INTO locks(name, token, owner, expires_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET token=excluded.token, owner=excluded.owner, expires_at=excluded.expires_at",
                    (name, token, owner, now + ttl_sec),
                )
                self._conn.execute("COMMIT")
                return token
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def write_unlock(self, name: str, token: Optional[str]) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT token FROM locks WHERE name=?", (name,)).fetchone()
                if row and (token is None or row["token"] == token):
                    self._conn.execute("DELETE FROM locks WHERE name=?", (name,))
                    self._conn.execute("COMMIT")
                    return True
                self._conn.execute("ROLLBACK")
                return False
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    # ------------------------------------------------------------------ buildings
    def get_building(self, bid: str) -> Optional[Dict]:
        row = self.query_one("SELECT * FROM buildings WHERE id=?", (bid,))
        return row_to_dict(row)

    def find_building_by_address(self, address_key: str) -> Optional[Dict]:
        row = self.query_one("SELECT * FROM buildings WHERE address_key=? AND deleted=0", (address_key,))
        return row_to_dict(row)

    def list_buildings(self, include_deleted: bool = False, text: str = "") -> List[Dict]:
        sql = "SELECT * FROM buildings"
        cond, params = [], []
        if not include_deleted:
            cond.append("deleted=0")
        if text:
            cond.append("search_norm LIKE ?")
            params.append(f"%{text}%")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY street, house_number"
        return [row_to_dict(r) for r in self.query(sql, params)]

    def insert_building(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.write() as conn:
            self.insert_building_tx(conn, data)
        return self.get_building(data["id"]) or data

    def insert_building_tx(self, conn, data: Dict[str, Any]) -> None:
        """Chèn tòa nhà trong 1 transaction đang mở (gọi từ manager để giữ nguyên tính nguyên tử)."""
        cols = list(data.keys())
        sql = f"INSERT INTO buildings({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        conn.execute(sql, [data[c] for c in cols])

    def update_building(self, bid: str, changes: Dict[str, Any]) -> Optional[Dict]:
        if not changes:
            return self.get_building(bid)
        changes = dict(changes)
        changes["updated_at"] = now_iso()
        changes["version"] = changes.get("version", 0) + 1
        sets = ",".join(f"{k}=?" for k in changes)
        with self.write() as conn:
            conn.execute(f"UPDATE buildings SET {sets} WHERE id=?", [*changes.values(), bid])
        return self.get_building(bid)

    # ------------------------------------------------------------------ rooms
    def get_room(self, rid: str, with_address: bool = True) -> Optional[Dict]:
        if with_address:
            row = self.query_one(_ROOM_SELECT + " WHERE r.id=?", (rid,))
        else:
            row = self.query_one("SELECT * FROM rooms WHERE id=?", (rid,))
        return row_to_dict(row)

    def get_rooms(self, ids: Iterable[str], with_address: bool = True) -> List[Dict]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return []
        out: Dict[str, Dict] = {}
        # chunk để không vượt giới hạn biến của SQLite (999)
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            ph = ",".join("?" * len(chunk))
            if with_address:
                rows = self.query(_ROOM_SELECT + f" WHERE r.id IN ({ph})", chunk)
            else:
                rows = self.query(f"SELECT * FROM rooms WHERE id IN ({ph})", chunk)
            for r in rows:
                d = row_to_dict(r)
                out[d["id"]] = d
        return [out[i] for i in ids if i in out]

    def insert_room(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.write() as conn:
            self.insert_room_tx(conn, data)
        return self.get_room(data["id"]) or data

    def insert_room_tx(self, conn, data: Dict[str, Any]) -> None:
        """Chèn phòng trong transaction đang mở -> kiểm tra trùng + ghi xảy ra trong CÙNG khoá ghi."""
        cols = list(data.keys())
        sql = f"INSERT INTO rooms({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        conn.execute(sql, [data[c] for c in cols])

    def update_room_tx(self, conn, rid: str, changes: Dict[str, Any]) -> int:
        changes = dict(changes)
        changes["updated_at"] = now_iso()
        changes["version"] = int(changes.get("version", 0)) + 1
        sets = ",".join(f"{k}=?" for k in changes)
        cur = conn.execute(f"UPDATE rooms SET {sets} WHERE id=?", [*changes.values(), rid])
        return changes["version"]

    def update_room(self, rid: str, changes: Dict[str, Any]) -> Optional[Dict]:
        if not changes:
            return self.get_room(rid)
        changes = dict(changes)
        changes["updated_at"] = now_iso()
        changes["version"] = int(changes.get("version", 0)) + 1
        sets = ",".join(f"{k}=?" for k in changes)
        with self.write() as conn:
            cur = conn.execute(f"UPDATE rooms SET {sets} WHERE id=?", [*changes.values(), rid])
            if cur.rowcount == 0:
                raise KeyError(f"Không tìm thấy phòng {rid}")
        return self.get_room(rid)

    def soft_delete_room(self, rid: str, actor: str = "") -> None:
        with self.write() as conn:
            conn.execute(
                "UPDATE rooms SET deleted=1, sync_state='pending', updated_at=?, updated_by=?, version=version+1 WHERE id=?",
                (now_iso(), actor, rid),
            )

    def restore_room(self, rid: str, actor: str = "") -> None:
        with self.write() as conn:
            conn.execute(
                "UPDATE rooms SET deleted=0, sync_state='pending', updated_at=?, updated_by=?, version=version+1 WHERE id=?",
                (now_iso(), actor, rid),
            )

    def find_room_identity(self, building_id: str, unit_key: str) -> Optional[Dict]:
        if not unit_key:
            return None
        row = self.query_one(
            "SELECT * FROM rooms WHERE building_id=? AND unit_key=? AND deleted=0", (building_id, unit_key)
        )
        return row_to_dict(row)

    def find_room_by_code(self, code_key: str) -> List[Dict]:
        if not code_key:
            return []
        return [row_to_dict(r) for r in self.query(
            _ROOM_SELECT + " WHERE r.room_code_key=? AND r.deleted=0", (code_key,))]

    def room_counts(self, include_deleted: bool = False) -> Dict[str, Any]:
        where = "" if include_deleted else "WHERE deleted=0"
        out = {"total": 0, "buildings": 0, "status": {}, "surveyed": 0, "unsurveyed": 0,
               "ev": 0, "pet": 0, "types": {}, "price_avg": 0}
        row = self.query_one(f"SELECT COUNT(*) c FROM rooms {where}")
        out["total"] = row["c"] if row else 0
        for r in self.query(f"SELECT status, COUNT(*) c FROM rooms {where} GROUP BY status"):
            out["status"][r["status"]] = r["c"]
        row = self.query_one(f"SELECT SUM(surveyed) s FROM rooms {where}")
        out["surveyed"] = row["s"] or 0
        out["unsurveyed"] = out["total"] - out["surveyed"]
        row = self.query_one(f"SELECT SUM(ev_support) e, SUM(pet_ok) p, AVG(price) a FROM rooms {where}")
        if row:
            out["ev"] = row["e"] or 0
            out["pet"] = row["p"] or 0
            out["price_avg"] = int(row["a"] or 0)
        for r in self.query(f"SELECT room_type, COUNT(*) c FROM rooms {where} GROUP BY room_type ORDER BY c DESC"):
            out["types"][r["room_type"] or "(chưa rõ)"] = r["c"]
        row = self.query_one("SELECT COUNT(*) c FROM buildings WHERE deleted=0")
        out["buildings"] = row["c"] if row else 0
        return out

    def building_counts(self) -> Dict[str, Dict[str, int]]:
        """{building_id: {'total','vacant','soon_vacant','rented','deposit','holding',...}}"""
        sql = """
            SELECT building_id, status, COUNT(*) c FROM rooms WHERE deleted=0
            GROUP BY building_id, status
        """
        out: Dict[str, Dict[str, int]] = {}
        for r in self.query(sql):
            b = out.setdefault(r["building_id"], {"total": 0})
            c = r["c"]
            b["total"] += c
            b[r["status"]] = b.get(r["status"], 0) + c
        return out

    def count_rooms(self, where: str = "", params: Sequence = ()) -> int:
        sql = "SELECT COUNT(*) c FROM rooms r " + (f"WHERE {where}" if where else "")
        row = self.query_one(sql, params)
        return row["c"] if row else 0

    def search_rooms_sql(self, where: str, params: Sequence = (), order: str = "r.room_code",
                         limit: int = 0, offset: int = 0) -> List[Dict]:
        sql = _ROOM_SELECT + (f" WHERE {where}" if where else "")
        sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {limit} OFFSET {offset}"
        return [row_to_dict(r) for r in self.query(sql, params)]

    # ------------------------------------------------------------------ history
    def add_history(self, room_id: str, old_status: str, new_status: str, actor: str, note: str = "") -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO status_history(room_id, old_status, new_status, changed_at, actor, note) VALUES(?,?,?,?,?,?)",
                (room_id, old_status, new_status, now_iso(), actor, note),
            )

    def history(self, room_id: str, limit: int = 50) -> List[Dict]:
        return [row_to_dict(r) for r in self.query(
            "SELECT * FROM status_history WHERE room_id=? ORDER BY changed_at DESC, id DESC LIMIT ?",
            (room_id, limit))]

    def recent_history(self, limit: int = 30) -> List[Dict]:
        return [row_to_dict(r) for r in self.query(
            "SELECT h.*, r.room_code, r.building_id FROM status_history h "
            "LEFT JOIN rooms r ON r.id=h.room_id ORDER BY h.changed_at DESC, h.id DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------ sync queue
    def queue_push(self, idem_key: str, entity: str, entity_id: str, op: str, payload: Dict) -> bool:
        """Đưa 1 lệnh vào hàng đợi. Trả False nếu lệnh idempotent đã tồn tại (chống lặp).

        Lệnh PENDING cũ của cùng bản ghi bị thay thế (superseded) -> tiết kiệm quota Sheets
        vì lệnh mới đã chứa trạng thái mới nhất.
        """
        with self.write() as conn:
            try:
                conn.execute(
                    "INSERT INTO sync_queue(idem_key, entity, entity_id, op, payload, state, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,'pending',?,?)",
                    (idem_key, entity, entity_id, op, json.dumps(payload, ensure_ascii=False), now_iso(), now_iso()),
                )
                conn.execute(
                    "DELETE FROM sync_queue WHERE entity=? AND entity_id=? AND state IN ('pending','failed') "
                    "AND idem_key<>?",
                    (entity, entity_id, idem_key),
                )
                return True
            except sqlite3.IntegrityError:
                # đã từng gửi đúng lệnh này -> bỏ qua (chống gửi lặp)
                conn.execute(
                    "UPDATE sync_queue SET payload=?, updated_at=? WHERE idem_key=? AND state IN ('failed','conflict')",
                    (json.dumps(payload, ensure_ascii=False), now_iso(), idem_key),
                )
                return False

    def queue_pending(self) -> List[Dict]:
        """Lệnh chờ xử lý (conflict KHÔNG tự retry - cần người xác nhận)."""
        return [row_to_dict(r) for r in self.query(
            "SELECT * FROM sync_queue WHERE state IN ('pending','failed') "
            "AND next_attempt_at <= ? ORDER BY id", (time.time(),))]

    def queue_has_pending(self, entity_id: str) -> bool:
        row = self.query_one(
            "SELECT 1 FROM sync_queue WHERE entity_id=? AND state IN ('pending','failed','running') LIMIT 1",
            (entity_id,))
        return row is not None

    def queue_count(self) -> Dict[str, int]:
        out = {"pending": 0, "running": 0, "failed": 0, "conflict": 0}
        for r in self.query("SELECT state, COUNT(*) c FROM sync_queue GROUP BY state"):
            out[r["state"]] = r["c"]
        return out

    def queue_update(self, qid: int, state: str, error: str = "", backoff: float = 0.0) -> None:
        with self.write() as conn:
            conn.execute(
                "UPDATE sync_queue SET state=?, last_error=?, attempts=attempts+1, "
                "next_attempt_at=?, updated_at=? WHERE id=?",
                (state, error, time.time() + backoff, now_iso(), qid),
            )

    def queue_clear_done(self) -> int:
        with self.write() as conn:
            cur = conn.execute("DELETE FROM sync_queue WHERE state='done'")
            return cur.rowcount

    # ------------------------------------------------------------------ id map (Sheets rows)
    def idmap_get(self, room_id: str) -> Optional[Dict]:
        row = self.query_one("SELECT * FROM id_map WHERE room_id=?", (room_id,))
        return row_to_dict(row)

    def idmap_upsert(self, room_id: str, sheet: str, row_number: int, remote_ver: int, local_ver: int,
                     remote_hash: str = "", local_hash: str = "", remote_at: str = "") -> None:
        with self.write() as conn:
            self.idmap_upsert_tx(conn, room_id, sheet, row_number, remote_ver, local_ver,
                                 remote_hash, local_hash, remote_at)

    def idmap_upsert_tx(self, conn, room_id: str, sheet: str, row_number: int, remote_ver: int,
                        local_ver: int, remote_hash: str = "", local_hash: str = "",
                        remote_at: str = "") -> None:
        conn.execute(
            "INSERT INTO id_map(room_id, entity, sheet, row_number, remote_ver, local_ver, "
            "remote_hash, local_hash, remote_at, updated_at) VALUES(?,'room',?,?,?,?,?,?,?,?) "
            "ON CONFLICT(room_id) DO UPDATE SET sheet=excluded.sheet, row_number=excluded.row_number, "
            "remote_ver=excluded.remote_ver, local_ver=excluded.local_ver, remote_hash=excluded.remote_hash, "
            "local_hash=excluded.local_hash, remote_at=excluded.remote_at, updated_at=excluded.updated_at",
            (room_id, sheet, row_number, remote_ver, local_ver, remote_hash, local_hash, remote_at, now_iso()),
        )

    def idmap_all(self) -> Dict[str, Dict]:
        return {r["room_id"]: dict(r) for r in self.query("SELECT * FROM id_map")}

    def idmap_by_row(self) -> Dict[int, Dict]:
        return {r["row_number"]: dict(r) for r in self.query("SELECT * FROM id_map WHERE row_number>0")}

    # ------------------------------------------------------------------ imports
    def log_import(self, filename: str, counts: Dict[str, int], actor: str) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO import_batches(filename, created_at, total, added, updated, skipped, suspect, errors, actor) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (filename, now_iso(), counts.get("total", 0), counts.get("new", 0), counts.get("changed", 0),
                 counts.get("duplicate", 0), counts.get("suspect", 0), counts.get("error", 0), actor),
            )

    def recent_imports(self, limit: int = 10) -> List[Dict]:
        return [row_to_dict(r) for r in self.query(
            "SELECT * FROM import_batches ORDER BY id DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------ misc
    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")


_ROOM_SELECT = (
    "SELECT r.*, b.display AS address, b.code AS building_code "
    "FROM rooms r LEFT JOIN buildings b ON b.id = r.building_id"
)


def build_room_search_norm(room: Dict[str, Any], building: Optional[Dict[str, Any]] = None) -> str:
    """Chuỗi chuẩn hoá để tìm kiếm nhanh (bỏ dấu, thường hoá) - lưu trong cột search_norm."""
    import text_utils as tu

    b = building or {}
    parts = [
        room.get("room_code", ""), room.get("unit_code", ""), room.get("floor", ""),
        room.get("room_type", ""), room.get("status", ""), room.get("owner_phone", ""),
        room.get("capacity", ""), room.get("pet_policy", ""), room.get("rating", ""),
        room.get("notes", ""), str(room.get("price", "")), str(room.get("deposit", "")),
        b.get("house_number", ""), b.get("street", ""), b.get("ward", ""),
        b.get("district", ""), b.get("display", ""), b.get("phone", ""), b.get("owner_name", ""),
    ]
    price = int(room.get("price") or 0)
    if price:
        if price % 1_000_000 == 0:
            parts += [f"{price // 1_000_000}tr", f"{price // 1_000_000}trieu"]
        if price % 1_000 == 0:
            parts.append(f"{price // 1000}n")
    return " ".join(tu.norm(p) for p in parts if p)
