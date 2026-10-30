# -*- coding: utf-8 -*-
"""sync_queue.py - Hàng đợi đồng bộ nền + worker chạy thread riêng (giao diện không bao giờ bị đứng).

Đặc tính theo đặc tả:
- Mất mạng -> lệnh vẫn nằm trong hàng đợi (SQLite), không rơi.
- Có mạng trở lại -> đồng bộ lại an toàn, có lũy thừa + giới hạn số lần thử.
- Chống gửi lặp: mỗi lệnh có ``idem_key`` UNIQUE (một thay đổi = một lệnh).
- Nhiều máy: khoá lease trên Sheets trước khi ghi + content hash để phát hiện ghi đè.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from config import get_settings, now_iso
from logger import get_logger
from google_sheets import NotConfigured, SheetsClient, SheetsError, content_hash

log = get_logger("sync")

_MAX_ATTEMPTS = 8


# ------------------------------------------------------------------ mạng
class NetworkMonitor:
    """Kiểm tra nhanh có kết nối tới Google không (cache 15s -> không tốn thời gian UI)."""

    def __init__(self, host: str = "sheets.googleapis.com", port: int = 443, ttl: float = 15.0):
        self.host, self.port, self.ttl = host, port, ttl
        self._last: Optional[bool] = None
        self._ts = 0.0
        self._lock = threading.Lock()

    def online(self) -> bool:
        with self._lock:
            if self._last is not None and time.time() - self._ts < self.ttl:
                return self._last
            ok = False
            try:
                with socket.create_connection((self.host, self.port), timeout=1.8):
                    ok = True
            except OSError:
                ok = False
            self._last, self._ts = ok, time.time()
            return ok

    def invalidate(self) -> None:
        with self._lock:
            self._ts = 0.0


# ------------------------------------------------------------------ worker
class SyncWorker(threading.Thread):
    """Thread nền duy nhất phụ trách đồng bộ Google Sheets."""

    def __init__(self, db, client: Optional[SheetsClient] = None,
                 remote_applier: Optional[Callable[[Any], Dict[str, Any]]] = None):
        super().__init__(daemon=True, name="sync-worker")
        self.db = db
        self.settings = get_settings()
        self.client = client or SheetsClient(self.settings)
        self.net = NetworkMonitor()
        self.remote_applier = remote_applier     # inventory_manager.apply_remote_rows
        self._stop_evt = threading.Event()
        self._kick = threading.Event()
        self._events: deque = deque(maxlen=200)
        self._lock = threading.Lock()
        self._state = "idle"
        self._last_sync = ""
        self._last_error = ""
        self._syncing = False

    # ---------------------------------------------------------------- events
    def emit(self, event: str, data: Optional[Dict] = None) -> None:
        with self._lock:
            self._events.append({"event": event, "data": data or {}, "ts": now_iso()})

    def take_events(self) -> List[Dict]:
        with self._lock:
            out = list(self._events)
            self._events.clear()
        return out

    def notify(self) -> None:
        """Bắn tín hiệu cho worker thức dậy ngay (khi có lệnh mới)."""
        self._kick.set()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_evt.set()
        self._kick.set()
        if self.ident is not None:          # chỉ join khi thread đã chạy
            try:
                self.join(timeout=timeout)
            except RuntimeError:
                pass

    # ---------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        counts = self.db.queue_count()
        enabled = bool(self.settings.get("google_enabled"))
        ready = self.client.configured
        return {
            "state": self._state,
            "last_sync": self._last_sync,
            "last_error": self._last_error,
            "pending": counts.get("pending", 0) + counts.get("failed", 0),
            "conflict": counts.get("conflict", 0),
            "done": counts.get("done", 0),
            "online": self.net.online() if enabled else False,
            "enabled": enabled,
            "ready": ready,
            "syncing": self._syncing,
            "sheets_status": self.client.status(),
        }

    # ---------------------------------------------------------------- loop
    def run(self) -> None:  # pragma: no cover - vòng lặp nền
        log.info("SyncWorker khởi động")
        while not self._stop_evt.is_set():
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("Lỗi vòng đồng bộ: %s", e)
                self._last_error = str(e)
                self.emit("error", {"message": str(e)})
                self._state = "error"
            interval = max(10, int(self.settings.get("sync_interval_sec") or 60))
            self._stop_evt.wait(interval if not self._kick.is_set() else 0.5)
            self._kick.clear()
        log.info("SyncWorker dừng")

    def _tick(self) -> None:
        if not self.settings.get("google_enabled"):
            self._state = "disabled"
            return
        if not self.client.configured:
            self._state = "not_configured"
            return
        if self.db.queue_count().get("pending", 0) + self.db.queue_count().get("failed", 0) == 0:
            # vẫn kéo dữ liệu định kỳ để phát hiện thay đổi từ máy khác
            if self.settings.get("auto_sync"):
                self._state = "idle"
            return
        if not self.net.online():
            self._state = "offline"
            self.emit("offline", {})
            return
        self.pump()

    # ---------------------------------------------------------------- pump
    def pump(self) -> Dict[str, Any]:
        """Xử lý hàng đợi 1 lần. An toàn khi gọi từ thread khác (test / gọi tay)."""
        summary: Dict[str, Any] = {"done": 0, "conflict": 0, "failed": 0, "pulled": 0}
        if not self.net.online():        # MẠNG trước: mất mạng -> GIỮ hàng đợi, không đánh dấu lỗi
            summary["state"] = "offline"
            return summary
        if not self.client.configured:
            summary["state"] = "not_configured"
            return summary

        self._syncing = True
        self._state = "syncing"
        try:
            if not self.net.online():        # kiểm tra MẠNG trước -> mất mạng giữ nguyên hàng đợi
                self._state = "offline"
                self.emit("offline", {})
                summary["state"] = "offline"
                return summary
            if not self.client.configured:
                summary["state"] = "not_configured"
                self._state = "not_configured"
                return summary
            if not self.client.acquire_lock("warehouse"):
                summary["state"] = "locked"
                self._state = "locked"
                self.emit("locked", {})
                return summary
            try:
                ops = self.db.queue_pending()
                if ops:
                    res = self._apply_ops(ops)
                    summary.update(res)
                if self.remote_applier and (ops or self.settings.get("auto_sync")):
                    pulled = self._pull_once()
                    summary["pulled"] = pulled
            finally:
                self.client.release_lock("warehouse")

            self._last_sync = now_iso()
            self._last_error = ""
            self._state = "idle"
            self.emit("synced", summary)
            return summary
        except NotConfigured as e:
            self._state = "not_configured"
            summary["error"] = str(e)
            return summary
        except SheetsError as e:
            self._last_error = str(e)
            self._state = "error"
            summary["error"] = str(e)
            self.emit("error", {"message": str(e)})
            log.warning("Đồng bộ lỗi: %s", e)
            return summary
        finally:
            self._syncing = False

    # ---------------------------------------------------------------- ops
    def _apply_ops(self, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
        rooms_ops = [o for o in ops if o["entity"] == "room"]
        bld_ops = [o for o in ops if o["entity"] == "building"]
        stats_ops = [o for o in ops if o["entity"] == "stats"]
        out = {"done": 0, "conflict": 0, "failed": 0}

        if rooms_ops:
            r = self._sync_rooms(rooms_ops)
            for k in out:
                out[k] += r.get(k, 0)
        if bld_ops:
            r = self._sync_buildings(bld_ops)
            for k in out:
                out[k] += r.get(k, 0)
        if stats_ops:
            try:
                payload = json.loads(stats_ops[-1]["payload"])
                self.client.push_stats(payload.get("stats", {}), self.settings.get("stats_sheet"))
                for o in stats_ops:
                    self.db.queue_update(o["id"], "done")
                    out["done"] += 1
            except Exception as e:  # noqa: BLE001
                self._fail(stats_ops, str(e))
                out["failed"] += len(stats_ops)
        return out

    def _fail(self, ops: List[Dict], error: str) -> None:
        for o in ops:
            attempts = int(o.get("attempts") or 0) + 1
            if attempts >= _MAX_ATTEMPTS:
                self.db.queue_update(o["id"], "conflict", error)
            else:
                backoff = min(300.0, 5.0 * (2 ** min(attempts, 6)))
                self.db.queue_update(o["id"], "failed", error, backoff)

    def _sync_rooms(self, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
        from excel_export import room_to_row_values

        out = {"done": 0, "conflict": 0, "failed": 0}
        try:
            table = self.client.read_table()
        except Exception as e:  # noqa: BLE001
            self._fail(ops, str(e))
            out["failed"] = len(ops)
            return out

        remote_map = {}
        try:
            remote_map = self.client.read_map()
        except Exception as e:  # noqa: BLE001
            log.warning("Không đọc được App_ID_Map: %s", e)

        mapping = table.mapping
        headers_len = len(table.headers)
        # index theo identity để nhận lại dòng chưa có map
        ident_index: Dict[str, int] = {}
        row_cells: Dict[int, List[Any]] = {}
        for row in table.rows:
            payload = row["cells"]
            key = _row_identity(row, mapping)
            if key and key not in ident_index:
                ident_index[key] = row["excel_row"]
            row_cells[row["excel_row"]] = row["cells"]

        writes: Dict[int, List[Any]] = {}
        appends: List[Dict[str, Any]] = []
        map_entries: Dict[str, Dict[str, Any]] = {}
        conflict_ops: List[Dict] = []
        ok_ops: List[Dict] = []

        for op in ops:
            try:
                p = json.loads(op["payload"])
            except Exception:
                self._fail([op], "payload hỏng")
                out["failed"] += 1
                continue
            room, building = p.get("room", {}), p.get("building", {})
            rid = room.get("id") or op["entity_id"]
            info = remote_map.get(rid) or {}
            row_no = int(info.get("row") or 0)
            if not row_no:
                row_no = ident_index.get(_room_identity(room, building), 0)

            target = room_to_row_values(room, building, mapping, headers_len)

            if row_no and row_no in row_cells:
                remote_hash = content_hash(row_cells[row_no])
                stored_hash = str(info.get("content_hash") or "")
                if stored_hash and remote_hash != stored_hash and remote_hash != content_hash(target):
                    # máy khác đã sửa dòng này sau lần sync cuối -> không ghi đè ngầm
                    conflict_ops.append(op)
                    continue
                if remote_hash == content_hash(target):
                    ok_ops.append((op, row_no, target, remote_hash))
                    continue
                writes[row_no] = target
                ok_ops.append((op, row_no, target, remote_hash))
            elif row_no:
                writes[row_no] = target
                ok_ops.append((op, row_no, target, content_hash(target)))
            else:
                appends.append({"op": op, "room": room, "building": building, "values": target})
                ok_ops.append((op, 0, target, ""))

        try:
            if writes:
                data = [{"range": f"'{table.title}'!A{r}:{_col_letter(headers_len)}{r}", "values": [v]}
                        for r, v in sorted(writes.items())]
                for i in range(0, len(data), MAX_RANGES_PER_BATCH):
                    self.client.batch_update_values(data[i:i + MAX_RANGES_PER_BATCH])
            if appends:
                # STT liên tục
                stt_idx = mapping.get("stt")
                next_stt = max([int(_num(v[stt_idx]) or 0) for v in row_cells.values() if stt_idx is not None]
                               or [0]) + 1
                values = []
                for a in appends:
                    if stt_idx is not None:
                        a["values"][stt_idx] = next_stt
                        next_stt += 1
                    values.append(a["values"])
                rng = f"A{_first_data_row(mapping, table)}"
                for i in range(0, len(values), MAX_RANGES_PER_BATCH):
                    self.client.append_values(table.title, values[i:i + MAX_RANGES_PER_BATCH], rng)
                # đọc lại bảng để xác định CHÍNH XÁC số dòng vừa append (không dựa vào vị trí tương đối)
                table2 = self.client.read_table()
                idx2: Dict[str, int] = {}
                for row in table2.rows:
                    k = _row_identity(row, table.mapping)
                    if k:
                        idx2.setdefault(k, row["excel_row"])
                for a in appends:
                    k = _room_identity(a["room"], a.get("building") or {})
                    a["new_row"] = idx2.get(k, 0)
        except Exception as e:  # noqa: BLE001
            self._fail(ops, str(e))
            out["failed"] = len(ops)
            log.exception("Lỗi ghi Sheets")
            return out

        # cập nhật id map (Sheets + local)
        import text_utils as tu
        map_list: List[Dict[str, Any]] = []
        for rid, info in remote_map.items():
            map_list.append({"room_id": rid, "sheet": table.title, "row": info.get("row", 0),
                             "version": info.get("version", 0), "content_hash": info.get("content_hash", ""),
                             "updated_at": info.get("updated_at", ""),
                             "address_key": info.get("address_key", ""), "unit_key": info.get("unit_key", ""),
                             "room_code": info.get("room_code", "")})
        try:
            with self.db.write() as conn:
                for op, row_no, target, _h in ok_ops:
                    p = json.loads(op["payload"])
                    room = p.get("room", {})
                    rid = room.get("id") or op["entity_id"]
                    row_final = row_no
                    for a in appends:
                        if a["op"]["id"] == op["id"]:
                            row_final = a.get("new_row") or 0
                    h = content_hash(target)
                    entry = {"room_id": rid, "sheet": table.title, "row": row_final,
                             "version": int(room.get("version", 0)), "content_hash": h,
                             "updated_at": now_iso(),
                             "address_key": tu.address_key(room.get("house_number"), room.get("street"),
                                                           room.get("ward"), room.get("district")) or p.get("address_key", ""),
                             "unit_key": room.get("unit_key", ""), "room_code": room.get("room_code", "")}
                    map_list = [m for m in map_list if m["room_id"] != rid] + [entry]
                    self.db.idmap_upsert_tx(conn, rid, table.title, row_final, int(room.get("version", 0)),
                                            int(room.get("version", 0)), h, h, now_iso())
                    conn.execute("UPDATE rooms SET sync_state='synced' WHERE id=?", (rid,))
                for op in conflict_ops:
                    conn.execute("UPDATE sync_queue SET state='conflict', last_error=?, updated_at=? WHERE id=?",
                                 ("Dòng trên Sheets đã bị máy khác thay đổi - cần xác nhận", now_iso(), op["id"]))
                for op, *_ in ok_ops:
                    conn.execute("UPDATE sync_queue SET state='done', last_error='', updated_at=? WHERE id=?",
                                 (now_iso(), op["id"]))
            try:
                self.client.write_map(map_list)
            except Exception as e:  # noqa: BLE001
                log.warning("Không ghi được App_ID_Map: %s", e)
        except Exception as e:  # noqa: BLE001
            self._fail(ops, str(e))
            out["failed"] = len(ops)
            return out

        out["done"] = len(ok_ops)
        out["conflict"] = len(conflict_ops)
        return out

    def _sync_buildings(self, ops: List[Dict]) -> Dict[str, Any]:
        """Đồng bộ danh mục tòa nhà (ghi vào sheet Danh Mục - map theo địa chỉ)."""
        out = {"done": 0, "conflict": 0, "failed": 0}
        # Sheets không có khoá dòng ổn định cho tòa nhà -> dùng App_ID_Map riêng theo building_id
        try:
            # ghi nhận như 1 sheet phụ, an toàn: mỗi lần push ghi trọn bảng danh mục
            from excel_export import building_to_row_values
            sheet = str(self.settings.get("buildings_sheet") or "Danh Mục Địa Điểm & Chủ Nhà")
            table = self.client.read_table(sheet)
            headers_len = len(table.headers)
            mapping = table.mapping
            # tìm dòng theo địa chỉ
            index = {}
            for row in table.rows:
                key = _row_identity(row, mapping)
                if key:
                    index.setdefault(key, row["excel_row"])
            writes: Dict[int, List[Any]] = {}
            appends: List[List[Any]] = []
            payload_last = None
            for op in ops:
                p = json.loads(op["payload"])
                b = p.get("building", p)
                payload_last = b
                key = _bld_identity(b)
                row_no = index.get(key, 0)
                values = building_to_row_values(b, mapping, headers_len)
                if row_no:
                    writes[row_no] = values
                else:
                    appends.append(values)
            data = [{"range": f"'{sheet}'!A{r}:{_col_letter(headers_len)}{r}", "values": [v]}
                    for r, v in sorted(writes.items())]
            for i in range(0, len(data), MAX_RANGES_PER_BATCH):
                self.client.batch_update_values(data[i:i + MAX_RANGES_PER_BATCH])
            if appends:
                self.client.append_values(sheet, appends, "A1")
            for op in ops:
                self.db.queue_update(op["id"], "done")
                out["done"] += 1
        except Exception as e:  # noqa: BLE001
            self._fail(ops, str(e))
            out["failed"] = len(ops)
        return out

    def _pull_once(self) -> int:
        """Kéo dữ liệu từ Sheets về (phát hiện thay đổi của máy khác)."""
        if not self.remote_applier:
            return 0
        rows = self.client.pull_rooms()
        res = self.remote_applier(rows)
        if res.get("changed"):
            self.emit("pulled", res)
        return int(res.get("changed", 0))


# ------------------------------------------------------------------ helpers
def _num(v) -> float:
    try:
        return float(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _first_data_row(mapping: Dict[str, int], table) -> int:
    return table.header_row + 1


def _row_identity(row: Dict[str, Any], mapping: Dict[str, int]) -> str:
    import text_utils as tu
    cells = row["cells"]

    def g(name):
        i = mapping.get(name)
        return cells[i] if i is not None and i < len(cells) else None

    key = tu.address_key(g("house_number"), g("street"), g("ward"), g("district"))
    if not key:
        return ""
    unit = tu.unit_key(g("unit_code")) or tu.room_code_key(g("room_code"))
    return f"{key}|{unit}"


def _room_identity(room: Dict[str, Any], building: Dict[str, Any]) -> str:
    import text_utils as tu
    key = tu.address_key(room.get("house_number") or building.get("house_number"),
                         room.get("street") or building.get("street"),
                         room.get("ward") or building.get("ward"),
                         room.get("district") or building.get("district"))
    if not key:
        return ""
    unit = tu.unit_key(room.get("unit_code")) or tu.room_code_key(room.get("room_code"))
    return f"{key}|{unit}"


def _bld_identity(b: Dict[str, Any]) -> str:
    import text_utils as tu
    return tu.address_key(b.get("house_number"), b.get("street"), b.get("ward"), b.get("district"))
