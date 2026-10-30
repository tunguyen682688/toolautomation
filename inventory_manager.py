# -*- coding: utf-8 -*-
"""inventory_manager.py - Lớp nghiệp vụ trung tâm (Business Logic).

MỌI thay đổi dữ liệu (thêm / sửa / đổi trạng thái / xóa / import / đồng bộ) đều đi qua đây:
  1. Kiểm tra trùng (DuplicateChecker) ngay BÊN TRONG khoá ghi (BEGIN IMMEDIATE)
  2. Ghi SQLite + cập nhật chỉ mục tìm kiếm
  3. Đưa lệnh vào hàng đợi đồng bộ Google Sheets (idempotent)
  4. Phát sự kiện cho giao diện (không cần tải lại trang)

Giao diện KHÔNG được ghi DB trực tiếp - chỉ gọi manager.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Sequence

import text_utils as tu
from config import get_settings, now_iso
from database import Database, build_room_search_norm
from duplicate_checker import CheckResult, DuplicateChecker, fingerprint
from logger import get_logger
from models import Building, Room, RoomFilter, RoomStatus, new_id
from search_engine import SearchIndex

log = get_logger("inventory")

ROOM_INSERT_FIELDS = [
    "id", "building_id", "room_code", "room_code_key", "unit_code", "unit_key", "floor",
    "room_type", "status", "surveyed", "price", "deposit", "capacity", "ev_support",
    "pet_ok", "pet_policy", "rating", "owner_phone", "zalo_group", "drive_link", "notes",
    "foreign_guest", "needs_verify", "search_norm", "external_ref", "sync_state", "version", "deleted",
    "created_at", "updated_at", "updated_by",
]


class DuplicateError(Exception):
    """Ném ra khi phát hiện trùng - kèm toàn bộ thông tin để UI cảnh báo."""

    def __init__(self, result: CheckResult):
        self.result = result
        super().__init__(result.messages(" | ") or "Dữ liệu trùng")


class InventoryManager:
    def __init__(self, db: Optional[Database] = None):
        self.settings = get_settings()
        self.db = db or Database.instance()
        self.index = SearchIndex(self.db)
        self.checker = DuplicateChecker(self.db)
        self._listeners: List[Callable[..., None]] = []
        self._wlock = threading.RLock()          # khóa ghi cấp ứng dụng (nhiều thread UI/worker)
        self._emit_depth = 0                     # buffer sự kiện khi đang trong transaction
        self._pending_events: List[Any] = []
        self.index.rebuild()

    # ---------------------------------------------------------------- events
    def subscribe(self, fn: Callable[..., None]) -> None:
        self._listeners.append(fn)

    @contextmanager
    def defer_events(self):
        """Không bắn sự kiện ra UI khi đang giữ khoá ghi (tránh UI gọi lại gây lồng transaction)."""
        self._emit_depth += 1
        try:
            yield
        finally:
            self._emit_depth -= 1
            if self._emit_depth == 0:
                pending = self._pending_events
                self._pending_events = []
                for ev, data in pending:
                    self._dispatch(ev, data)

    def emit(self, event: str, **data: Any) -> None:
        if self._emit_depth > 0:
            self._pending_events.append((event, data))
        else:
            self._dispatch(event, data)

    def _dispatch(self, event: str, data: Dict[str, Any]) -> None:
        for fn in list(self._listeners):
            try:
                fn(event, data)
            except Exception:  # noqa: BLE001
                log.exception("listener lỗi event=%s", event)

    # ================================================================ ĐỌC
    def stats(self) -> Dict[str, Any]:
        s = self.db.room_counts()
        by_type: Dict[str, Dict[str, int]] = {}
        for r in self.db.query(
            "SELECT room_type, status, COUNT(*) c, SUM(ev_support) e, SUM(pet_ok) p "
            "FROM rooms WHERE deleted=0 GROUP BY room_type, status"
        ):
            t = r["room_type"] or "(chưa rõ)"
            d = by_type.setdefault(t, {"total": 0, "vacant": 0, "ev": 0, "pet": 0})
            d["total"] += r["c"]
            d["ev"] += int(r["e"] or 0)
            d["pet"] += int(r["p"] or 0)
            if r["status"] == "vacant":
                d["vacant"] += r["c"]
        s["by_type"] = by_type
        s["deleted"] = self.db.query_one("SELECT COUNT(*) c FROM rooms WHERE deleted=1")["c"]
        s["needs_verify"] = self.db.query_one(
            "SELECT COUNT(*) c FROM rooms WHERE deleted=0 AND needs_verify=1")["c"]
        s["queue"] = self.db.queue_count()
        return s

    def buildings(self, include_deleted: bool = False, text: str = "") -> List[Dict[str, Any]]:
        rows = self.db.list_buildings(include_deleted=include_deleted)
        counts = self.db.building_counts()
        for b in rows:
            c = counts.get(b["id"], {})
            b["rooms_total"] = c.get("total", 0)
            b["rooms_vacant"] = c.get("vacant", 0)
            b["rooms_rented"] = c.get("rented", 0)
            b["rooms_deposit"] = c.get("deposit", 0) + c.get("holding", 0)
            b["rooms_soon"] = c.get("soon_vacant", 0)
        return self.index.search_buildings(rows, text)

    def building(self, bid: str) -> Optional[Dict[str, Any]]:
        return self.db.get_building(bid)

    def rooms(self, text: str = "", f: Optional[RoomFilter] = None) -> List[Dict[str, Any]]:
        """Tra nhanh: chỉ mục trả id -> tải đúng các dòng cần thiết (không load toàn bộ)."""
        ids = self.index.query(text, f)
        if not ids:
            return []
        return self.db.get_rooms(ids)

    def room(self, rid: str) -> Optional[Dict[str, Any]]:
        return self.db.get_room(rid)

    def history(self, rid: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.db.history(rid, limit)

    def recent_changes(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.db.recent_history(limit)

    def queue_status(self) -> Dict[str, int]:
        return self.db.queue_count()

    # ================================================================ TÒA NHÀ
    def ensure_building(self, payload: Dict[str, Any], actor: str = "",
                        conn=None) -> Dict[str, Any]:
        """Tìm tòa nhà theo địa chỉ; nếu chưa có -> tạo mới (không bao giờ tạo trùng)."""
        key = tu.address_key(payload.get("house_number"), payload.get("street"),
                             payload.get("ward"), payload.get("district"))
        if not key:
            raise ValueError("Thiếu địa chỉ tòa nhà (số nhà / tên đường)")
        existing = self.db.find_building_by_address(key)
        if existing:
            # điền bổ sung thông tin còn trống từ payload (KHÔNG ghi đè dữ liệu cũ)
            patch = {}
            for f in ("owner_name", "phone", "zalo_group", "ev_policy", "pet_policy", "commission"):
                if payload.get(f) and not existing.get(f):
                    patch[f] = payload[f]
            if patch:
                if conn is not None:
                    patch["updated_at"] = now_iso()
                    patch["version"] = int(existing.get("version") or 0) + 1
                    sets = ",".join(f"{k}=?" for k in patch)
                    conn.execute(f"UPDATE buildings SET {sets} WHERE id=?", [*patch.values(), existing["id"]])
                    existing.update({k: patch[k] for k in patch if k not in ("updated_at", "version")})
                    existing["version"] = patch["version"]
                else:
                    existing = self.db.update_building(existing["id"], patch) or existing
                self.emit("buildings_changed", ids=[existing["id"]])
            return existing

        data = {
            "id": new_id("BLD"),
            "code": self._next_building_code(conn),
            "house_number": str(payload.get("house_number") or "").strip(),
            "street": str(payload.get("street") or "").strip(),
            "ward": str(payload.get("ward") or "").strip(),
            "district": str(payload.get("district") or "").strip(),
            "display": tu.building_display(payload.get("house_number"), payload.get("street"),
                                           payload.get("ward"), payload.get("district")),
            "address_key": key,
            "owner_name": str(payload.get("owner_name") or "").strip(),
            "phone": str(payload.get("phone") or payload.get("owner_phone") or "").strip(),
            "zalo_group": str(payload.get("zalo_group") or "").strip(),
            "ev_policy": str(payload.get("ev_policy") or "").strip(),
            "pet_policy": str(payload.get("pet_policy") or "").strip(),
            "commission": str(payload.get("commission") or "").strip(),
            "notes": str(payload.get("notes") or "").strip(),
            "search_norm": " ".join(tu.norm(x) for x in (
                payload.get("house_number"), payload.get("street"), payload.get("ward"),
                payload.get("district"), payload.get("owner_name"), payload.get("phone")) if x),
            "external_ref": "", "sync_state": "pending", "version": 0, "deleted": 0,
            "created_at": now_iso(), "updated_at": now_iso(), "updated_by": actor,
        }
        try:
            if conn is not None:
                self.db.insert_building_tx(conn, data)
            else:
                self.db.insert_building(data)
        except sqlite3.IntegrityError:
            got = self.db.find_building_by_address(key)
            if not got:
                raise
            return got
        self.emit("buildings_changed", ids=[data["id"]])
        return self.db.get_building(data["id"]) or data

    def save_building(self, payload: Dict[str, Any], bid: Optional[str] = None,
                      actor: str = "") -> Dict[str, Any]:
        """Tạo mới (bid=None) hoặc cập nhật một tòa nhà từ form người dùng.

        Không bao giờ cho 2 tòa nhà trùng địa chỉ: nếu đổi địa chỉ sang địa chỉ
        đã có -> gộp vào tòa đó (trả về tòa đích) thay vì tạo bản sao.
        """
        actor = actor or self.settings.get("user_name") or "Admin"
        with self._wlock:
            with self.defer_events():
                if bid:
                    current = self.db.get_building(bid)
                    if not current:
                        raise KeyError(f"Không tìm thấy tòa nhà {bid}")
                    key = tu.address_key(payload.get("house_number"), payload.get("street"),
                                         payload.get("ward"), payload.get("district"))
                    if not key:
                        raise ValueError("Thiếu địa chỉ tòa nhà (số nhà / tên đường)")
                    if key != current.get("address_key"):
                        clash = self.db.find_building_by_address(key)
                        if clash and clash["id"] != bid:
                            # gộp sang tòa trùng địa chỉ -> phòng vẫn liên kết đúng
                            self._merge_building(bid, clash["id"], actor)
                            return self.db.get_building(clash["id"]) or clash
                    changes: Dict[str, Any] = {}
                    for f in ("house_number", "street", "ward", "district", "owner_name",
                              "phone", "zalo_group", "ev_policy", "pet_policy", "commission", "notes"):
                        v = str(payload.get(f) or "").strip()
                        if v != str(current.get(f) or ""):
                            changes[f] = v
                    if changes:
                        if key != current.get("address_key"):
                            changes["address_key"] = key
                            changes["display"] = tu.building_display(
                                payload.get("house_number"), payload.get("street"),
                                payload.get("ward"), payload.get("district"))
                            changes["search_norm"] = " ".join(tu.norm(x) for x in (
                                payload.get("house_number"), payload.get("street"),
                                payload.get("ward"), payload.get("district"),
                                payload.get("owner_name"), payload.get("phone")) if x)
                        changes["updated_by"] = actor
                        changes["sync_state"] = "pending"
                        self.db.update_building(bid, changes)
                    self.enqueue_building(self.db.get_building(bid) or current)
                    self.emit("buildings_changed", ids=[bid])
                    return self.db.get_building(bid) or current

                b = self.ensure_building(payload, actor=actor)
                # ensure_building chỉ điền bổ sung cột trống -> cập nhật nốt phần người dùng sửa
                patch = {}
                for f in ("owner_name", "phone", "zalo_group", "ev_policy", "pet_policy",
                          "commission", "notes"):
                    v = str(payload.get(f) or "").strip()
                    if v and v != str(b.get(f) or ""):
                        patch[f] = v
                if patch:
                    patch["updated_by"] = actor
                    patch["sync_state"] = "pending"
                    b = self.db.update_building(b["id"], patch) or b
                self.enqueue_building(b)
                self.emit("buildings_changed", ids=[b["id"]])
                return b

    def _merge_building(self, from_id: str, to_id: str, actor: str = "") -> int:
        """Gộp tòa từ_id -> to_id (chỉ khi 2 địa chỉ trùng): chuyển toàn bộ phòng sang tòa đích."""
        n = 0
        with self.db.write() as conn:
            rows = conn.execute("SELECT id FROM rooms WHERE building_id=?", (from_id,)).fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE rooms SET building_id=?, sync_state='pending', updated_at=?, "
                    "updated_by=?, version=version+1 WHERE id=?",
                    (to_id, now_iso(), actor, r["id"]))
                n += 1
            conn.execute("UPDATE buildings SET deleted=1, updated_at=?, updated_by=?, "
                         "version=version+1 WHERE id=?", (now_iso(), actor, from_id))
        log.info("Gộp tòa %s -> %s (%d phòng)", from_id, to_id, n)
        self.index.rebuild()
        self.emit("buildings_changed", ids=[to_id, from_id])
        self.emit("rooms_changed", ids=[], action="merge")
        return n

    def _next_building_code(self, conn=None) -> str:
        sql = "SELECT COUNT(*) c FROM buildings WHERE deleted=0"
        row = (conn.execute(sql).fetchone() if conn is not None else self.db.query_one(sql))
        n = int(row["c"] or 0) + 1
        while True:
            code = f"B{n:04d}"
            q = "SELECT 1 FROM buildings WHERE code=? LIMIT 1"
            taken = (conn.execute(q, (code,)).fetchone() if conn is not None
                     else self.db.query_one(q, (code,)))
            if not taken:
                return code
            n += 1

    # ================================================================ PHÒNG
    # ---------------------------------------------------------------- kiểm tra
    def check_new(self, payload: Dict[str, Any], exclude_id: Optional[str] = None) -> CheckResult:
        """Kiểm tra trùng TRƯỚC KHI lưu (dùng cho form thêm/sửa và import)."""
        return self.checker.check_room(payload, exclude_id=exclude_id)

    # ---------------------------------------------------------------- build record
    @staticmethod
    def _identity_keys(payload: Dict[str, Any]) -> Dict[str, str]:
        code = payload.get("room_code") or ""
        code_key = tu.room_code_key(code) if tu.valid_room_code(code) else ""
        unit = tu.unit_key(payload.get("unit_code"))
        unit_key = unit or code_key          # fallback: số căn trống -> dùng mã phòng làm khoá
        needs_verify = 0 if unit else 1      # CHƯA có số căn -> đánh dấu cần xác minh (không suy đoán)
        if not tu.valid_room_code(code):
            needs_verify = 1
        return {"room_code_key": code_key, "unit_key": unit_key, "needs_verify": needs_verify}

    def _room_record(self, payload: Dict[str, Any], building: Dict[str, Any], actor: str,
                     room_id: Optional[str] = None) -> Dict[str, Any]:
        keys = self._identity_keys(payload)
        ts = now_iso()
        record = {
            "id": room_id or new_id("RM"),
            "building_id": building["id"],
            "room_code": str(payload.get("room_code") or "").strip(),
            "unit_code": str(payload.get("unit_code") or "").strip(),
            "floor": str(payload.get("floor") or "").strip(),
            "room_type": str(payload.get("room_type") or "").strip(),
            "status": payload.get("status") or "new",
            "surveyed": 1 if payload.get("surveyed") else 0,
            "price": int(payload.get("price") or 0),
            "deposit": int(payload.get("deposit") or 0),
            "capacity": str(payload.get("capacity") or "").strip(),
            "ev_support": 1 if payload.get("ev_support") else 0,
            "pet_policy": str(payload.get("pet_policy") or "").strip(),
            "pet_ok": 1 if tu.parse_pet_policy(payload.get("pet_policy")) == "Cho nuôi" else 0,
            "rating": str(payload.get("rating") or "").strip(),
            "owner_phone": str(payload.get("owner_phone") or building.get("phone") or "").strip(),
            "zalo_group": str(payload.get("zalo_group") or building.get("zalo_group") or "").strip(),
            "drive_link": str(payload.get("drive_link") or "").strip(),
            "notes": str(payload.get("notes") or "").strip(),
            "foreign_guest": int(payload.get("foreign_guest") or 0),
            "external_ref": str(payload.get("external_ref") or "").strip(),
            "sync_state": "pending",
            "version": 1,
            "deleted": 0,
            "created_at": ts,
            "updated_at": ts,
            "updated_by": actor,
        }
        record.update(keys)
        record["search_norm"] = build_room_search_norm(
            {**record, "address": building.get("display", "")}, building)
        return record

    @staticmethod
    def _existing_finding(building: Optional[Dict[str, Any]], existing: Optional[Dict[str, Any]]) -> CheckResult:
        """Tạo CheckResult 'phòng đã tồn tại' (dùng khi DB chặn bằng unique index)."""
        from duplicate_checker import Finding
        if not existing:
            return CheckResult(findings=[Finding(kind="room_exists", severity="block",
                                                 message="Phòng đã tồn tại (khóa chống trùng của cơ sở dữ liệu)")])
        st = RoomStatus.label(existing.get("status", ""))
        return CheckResult(
            findings=[Finding(
                kind="room_exists", severity="block",
                message=(f"PHÒNG ĐÃ TỒN TẠI: {existing.get('room_code') or existing.get('unit_code')} - "
                         f"{existing.get('address') or (building or {}).get('display', '')} | trạng thái: {st} | "
                         f"cập nhật: {existing.get('updated_at')}"),
                room_id=existing.get("id"), building_id=(building or {}).get("id"), room=existing)],
            existing_room=existing,
        )

    # ---------------------------------------------------------------- thêm mới
    def add_room(self, payload: Dict[str, Any], actor: str = "", force: bool = False) -> Dict[str, Any]:
        """Thêm phòng mới. Ném DuplicateError nếu trùng (trừ khi người dùng đã xác nhận = force).

        Kiểm tra trùng + ghi xảy ra trong CÙNG khoá ghi -> an toàn khi 2 máy/thread cùng thêm.
        """
        actor = actor or self.settings.get("user_name") or "Admin"
        with self._wlock:
            with self.defer_events():
                with self.db.write() as conn:
                    building = self.ensure_building(payload, actor, conn=conn)
                    p = dict(payload)
                    p["building_id"] = building["id"]
                    res = self.checker.check_room(p)
                    if (res.has_block or res.has_warn) and not force:
                        raise DuplicateError(res)
                    record = self._room_record(p, building, actor)
                    try:
                        self.db.insert_room_tx(conn, record)
                    except sqlite3.IntegrityError as e:
                        # unique index (building_id, unit_key) -> chốt chặn cuối chống trùng
                        exist = self.db.find_room_identity(building["id"], record["unit_key"])
                        log.warning("Chèn phòng bị chặn bởi unique index: %s", e)
                        raise DuplicateError(self._existing_finding(building, exist or res.existing_room))
                    rid = record["id"]

        room = self.db.get_room(rid)
        self.index.update_room(room)
        self._enqueue_room(room, building)
        self.db.add_undo_log(rid, {}, action="add", actor=actor,
                             note=f"Thêm phòng {record.get('room_code','')}")
        self.emit("rooms_changed", ids=[rid], action="add")
        return room

    # ---------------------------------------------------------------- cập nhật
    def update_room(self, rid: str, changes: Dict[str, Any], actor: str = "",
                    force: bool = False, note: str = "") -> Dict[str, Any]:
        """Cập nhật một phần trường của phòng (tự lưu + tự đồng bộ)."""
        actor = actor or self.settings.get("user_name") or "Admin"
        with self._wlock:
            with self.defer_events():
                with self.db.write() as conn:
                    current = self.db.get_room(rid)
                    if not current:
                        raise KeyError(f"Không tìm thấy phòng {rid}")
                    merged = {**current, **{k: v for k, v in changes.items() if k not in
                                            ("id", "version", "created_at", "search_norm",
                                             "address", "building_code", "sync_state")}}
                    # đổi địa chỉ -> cần kiểm tra lại trùng + đổi tòa
                    building = None
                    address_changed = any(k in changes for k in
                                          ("house_number", "street", "ward", "district", "building_id"))
                    if address_changed:
                        payload = {**merged, **{k: changes[k] for k in changes}}
                        building = self.ensure_building(payload, actor, conn=conn)
                        payload["building_id"] = building["id"]
                        res = self.checker.check_room(payload, exclude_id=rid)
                        if (res.has_block or res.has_warn) and not force:
                            raise DuplicateError(res)
                        merged["building_id"] = building["id"]
                    else:
                        building = self.db.get_building(merged["building_id"])

                    rec = self._room_record(merged, building, actor, room_id=rid)
                    rec["id"] = rid
                    rec["created_at"] = current["created_at"]
                    rec["version"] = current["version"]
                    rec["deleted"] = current["deleted"]
                    update_fields = {k: rec[k] for k in ROOM_INSERT_FIELDS
                                     if k not in ("id", "created_at", "deleted")}
                    # update_room_tx sẽ tính version = version hiện tại + 1
                    update_fields["version"] = current["version"]
                    update_fields["sync_state"] = "pending"

                    old_status = current["status"]
                    new_status = rec["status"]
                    # --- GHI UNDO LOG TRƯỚC KHI GHI DB (để Ctrl+Z hoàn tác) ---
                    self.db.add_undo_log(
                        rid, current,
                        action="status" if old_status != new_status else "update",
                        actor=actor, note=note or "")
                    self.db.update_room_tx(conn, rid, update_fields)
                    if old_status != new_status:
                        # lưu LỊCH SỬ thay đổi (trạng thái cũ -> mới, thời gian, người thực hiện, ghi chú)
                        conn.execute(
                            "INSERT INTO status_history(room_id, old_status, new_status, changed_at, actor, note) "
                            "VALUES(?,?,?,?,?,?)", (rid, old_status, new_status, now_iso(), actor,
                                                    note or "Sửa trực tiếp"))
                    version = rec["version"] + 1  # update_room_tx đã +1

        room = self.db.get_room(rid)
        self.index.update_room(room)
        self._enqueue_room(room, building or self.db.get_building(room["building_id"]))
        self.emit("rooms_changed", ids=[rid], action="update",
                  status_changed=old_status != new_status, version=version)
        return room

    def change_status(self, rid: str, new_status: str, note: str = "",
                      actor: str = "") -> Dict[str, Any]:
        """Chuyển trạng thái nhanh - KHÔNG tạo bản ghi phòng mới, chỉ ghi lịch sử."""
        if new_status not in RoomStatus.LABEL:
            raise ValueError(f"Trạng thái không hợp lệ: {new_status}")
        return self.update_room(rid, {"status": new_status}, actor=actor,
                                note=note or f"Đổi trạng thái -> {RoomStatus.label(new_status)}")

    def try_update(self, rid: str, changes: Dict[str, Any], actor: str = "") -> bool:
        """Cập nhật an toàn cho sửa trực tiếp trên bảng: trả False nếu bị chặn trùng/lỗi.

        (UI không cần try/except cho các thao tác inline.)
        """
        try:
            self.update_room(rid, changes, actor=actor, note="Sửa trực tiếp trên bảng")
            return True
        except DuplicateError as e:
            log.warning("Chặn cập nhật %s (trùng): %s", rid, e)
            return False
        except Exception as e:  # noqa: BLE001
            log.exception("try_update lỗi %s", rid)
            return False

    def delete_room(self, rid: str, actor: str = "") -> None:
        actor = actor or self.settings.get("user_name") or "Admin"
        with self._wlock:
            current = self.db.get_room(rid)
            if not current:
                return
            # --- UNDO LOG trước khi xóa mềm (để khôi phục được) ---
            self.db.add_undo_log(rid, current, action="delete",
                                 actor=actor, note=f"Xóa phòng {current.get('room_code','')}")
            self.db.soft_delete_room(rid, actor)
        self.index.remove_room(rid)
        self._enqueue_room({**current, "deleted": 1, "version": current["version"] + 1},
                           self.db.get_building(current["building_id"]), op="delete")
        self.emit("rooms_changed", ids=[rid], action="delete")

    def restore_room(self, rid: str, actor: str = "") -> None:
        actor = actor or self.settings.get("user_name") or "Admin"
        with self._wlock:
            current = self.db.get_room(rid)
            if not current:
                return
            # --- UNDO LOG trước khi khôi phục ---
            self.db.add_undo_log(rid, current, action="restore",
                                 actor=actor, note=f"Khôi phục phòng {current.get('room_code','')}")
            # khôi phục phải không vi phạm unique -> nếu trùng thì báo
            exist = self.db.find_room_identity(current["building_id"], current["unit_key"])
            if exist and exist["id"] != rid:
                raise DuplicateError(CheckResult(findings=[], existing_room=exist))
            self.db.restore_room(rid, actor)
        room = self.db.get_room(rid)
        self.index.update_room(room)
        self._enqueue_room(room, self.db.get_building(room["building_id"]))
        self.emit("rooms_changed", ids=[rid], action="restore")

    def duplicate_room(self, rid: str, actor: str = "") -> Dict[str, Any]:
        """Nhân bản phòng: tạo bản ghi MỚI (id mới) với mã phòng mới - đánh dấu cần xác minh."""
        src = self.db.get_room(rid)
        if not src:
            raise KeyError(f"Không tìm thấy phòng {rid}")
        building = self.db.get_building(src["building_id"]) or {}
        payload = {k: src.get(k) for k in ROOM_INSERT_FIELDS}
        payload["room_code"] = (f"{src['room_code']}-COPY" if src.get("room_code") else "")
        payload["unit_code"] = ""      # không được đoán số căn -> người dùng phải nhập
        payload["status"] = "new"
        payload["excel_row"] = None
        return self.add_room(payload, actor=actor, force=False)

    # ------------------------------------------------------------------ hoàn tác (Ctrl+Z)
    def undo_last(self, actor: str = "", room_id: Optional[str] = None
                  ) -> Dict[str, Any]:
        """Hoàn tác 1 thao tác gần nhất (Ctrl+Z): xóa/restore/sửa/thêm.

        Trả về dict {ok, message, room_id, action} để UI hiển thị toast.
        """
        actor = actor or self.settings.get("user_name") or "Admin"
        entries = self.db.list_undo(room_id=room_id, undone=0, limit=1)
        if not entries:
            return {"ok": False, "message": "Không có thao tác nào để hoàn tác."}
        entry = entries[0]
        qid = entry["id"]
        rid = entry["room_id"]
        action = entry["action"]
        old_values = json.loads(entry["old_values"] or "{}")
        try:
            if action == "delete":
                self.restore_room(rid, actor=actor)
                msg = f"Đã khôi phục phòng {rid}"
            elif action == "restore":
                self.delete_room(rid, actor=actor)
                msg = f"Đã xóa mềm lại phòng {rid}"
            elif action == "add":
                self.delete_room(rid, actor=actor)
                msg = f"Đã hủy thao tác thêm phòng {rid}"
            elif action in ("update", "status"):
                if old_values:
                    # loại bỏ các trường không nên hoàn tác ngược
                    safe = {k: v for k, v in old_values.items()
                            if k not in ("id", "created_at", "search_norm", "sync_state")}
                    self.update_room(rid, safe, actor=actor, note="Hoàn tác (Ctrl+Z)")
                msg = f"Đã hoàn tác thay đổi phòng {rid}"
            else:
                msg = f"Bỏ qua thao tác '{action}' (không hỗ trợ hoàn tác)"
            self.db.mark_undone(qid)
            self.emit("rooms_changed", ids=[rid], action="undo")
            self.emit("stats_changed")
            return {"ok": True, "message": msg, "room_id": rid, "action": action}
        except Exception as e:  # noqa: BLE001
            log.exception("undo thất bại qid=%s", qid)
            return {"ok": False, "message": f"Không hoàn tác được: {e}"}

    def backup_database(self, label: str = "") -> str:
        """Proxy sang Database.backup_database."""
        return self.db.backup_database(label)
        """Nhân bản phòng: tạo bản ghi MỚI (id mới) với mã phòng mới - đánh dấu cần xác minh."""
        src = self.db.get_room(rid)
        if not src:
            raise KeyError(f"Không tìm thấy phòng {rid}")
        building = self.db.get_building(src["building_id"]) or {}
        payload = {k: src.get(k) for k in ROOM_INSERT_FIELDS}
        payload["room_code"] = (f"{src['room_code']}-COPY" if src.get("room_code") else "")
        payload["unit_code"] = ""      # không được đoán số căn -> người dùng phải nhập
        payload["status"] = "new"
        payload["excel_row"] = None
        return self.add_room(payload, actor=actor, force=False)

    # ---------------------------------------------------------------- xóa / import
    def import_apply(self, plan, include_kinds: Sequence[str], actor: str = "") -> Dict[str, int]:
        """Áp dụng kế hoạch import theo các loại người dùng chọn. Không bao giờ ghi đè khi chưa xác nhận."""
        actor = actor or self.settings.get("user_name") or "Admin"
        counts = {"total": len(plan.items), "new": 0, "duplicate": 0, "changed": 0,
                  "suspect": 0, "error": 0, "failed": 0, "skipped": 0}
        changed_rooms: List[str] = []
        # --- Tự backup trước khi import lớn để có điểm khôi phục ---
        if len(plan.items) >= 10:
            try:
                self.db.backup_database(label="import")
                log.info("Đã tự backup DB trước import %d dòng", len(plan.items))
            except Exception:  # noqa: BLE001
                log.exception("Không backup được DB trước import")
        for item in plan.items:
            kind = item.kind
            if kind not in include_kinds:
                counts["skipped"] += 1
                continue
            try:
                if kind == "changed" and item.existing:
                    changes = self._payload_to_changes(item.payload, item.existing)
                    if changes:
                        self.update_room(item.existing["id"], changes, actor=actor,
                                         force=True, note="Cập nhật từ Excel import")
                        changed_rooms.append(item.existing["id"])
                    counts["changed"] += 1
                elif kind in ("new", "suspect", "duplicate"):
                    if kind == "duplicate":
                        counts["duplicate"] += 1
                        continue
                    self.add_room(item.payload, actor=actor, force=(kind == "suspect"))
                    counts["new" if kind == "new" else "suspect"] += 1
                elif kind == "error":
                    counts["error"] += 1
            except DuplicateError as e:
                if e.result.room_exists:
                    # bản ghi trùng đã tồn tại -> KHÔNG thêm lại (không tính là lỗi hệ thống)
                    counts["duplicate"] += 1
                    item.reason = f"Đã tồn tại - bỏ qua: {e}"
                else:
                    counts["failed"] += 1
                    item.reason = f"Chặn trùng khi ghi: {e}"
                log.info("Import bỏ qua dòng %s: %s", item.excel_row, e)
            except Exception as e:  # noqa: BLE001
                counts["failed"] += 1
                item.reason = f"Lỗi ghi: {e}"
                log.exception("import row %s", item.excel_row)

        # sheet danh mục tòa nhà (nếu file có)
        if getattr(plan, "building_items", None):
            counts["buildings"] = self.import_buildings(plan.building_items, actor=actor)

        self.db.log_import(plan.filename, counts, actor)
        self.emit("rooms_changed", ids=changed_rooms, action="import", counts=counts)
        self.emit("stats_changed")
        return counts

    @classmethod
    def _payload_to_changes(cls, payload: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
        """Chỉ lấy các trường THỰC SỰ khác -> không ghi đè dữ liệu cũ vô ích."""
        from duplicate_checker import DuplicateChecker
        changes: Dict[str, Any] = {}
        for pf, ef in DuplicateChecker.COMPARE_MAP.items():
            if pf not in payload or ef not in existing:
                continue
            a, b = payload.get(pf), existing.get(ef)
            if a in (None, ""):
                continue
            if pf in ("price", "deposit"):
                if int(a or 0) != int(b or 0):
                    changes[pf] = int(a or 0)
            elif pf == "ev_support":
                if bool(a) != bool(b):
                    changes[pf] = 1 if a else 0
            elif DuplicateChecker._norm_val(pf, a) != DuplicateChecker._norm_val(pf, b):
                changes[pf] = a
        if payload.get("status") and RoomStatus.from_text(payload["status"]) != existing.get("status"):
            changes["status"] = RoomStatus.from_text(payload["status"])
        if payload.get("surveyed") is not None and bool(payload.get("surveyed")) != bool(existing.get("surveyed")):
            changes["surveyed"] = 1 if payload["surveyed"] else 0
        if payload.get("pet_policy") and tu.parse_pet_policy(payload["pet_policy"]) != \
                ("Cho nuôi" if existing.get("pet_ok") else "Không nuôi" if existing.get("pet_policy") else ""):
            changes["pet_policy"] = payload["pet_policy"]
        return changes

    def import_buildings(self, payloads: Sequence[Dict[str, Any]], actor: str = "") -> int:
        n = 0
        for p in payloads:
            if not (p.get("street") or p.get("house_number")):
                continue
            self.ensure_building(p, actor=actor)
            n += 1
        if n:
            self.emit("buildings_changed")
        return n

    # ================================================================ ĐỒNG BỘ
    def enqueue_all_pending(self) -> int:
        """Đưa toàn bộ bản ghi chờ sync vào hàng đợi (dùng khi vừa bật Google Sheets)."""
        n = 0
        for r in self.db.query("SELECT * FROM rooms WHERE sync_state='pending' AND deleted=0"):
            room = dict(r)
            self._enqueue_room(room, self.db.get_building(room["building_id"]))
            n += 1
        return n

    def _enqueue_room(self, room: Dict[str, Any], building: Optional[Dict[str, Any]],
                      op: str = "upsert") -> bool:
        if not self.settings.get("google_enabled"):
            return False            # chưa bật -> không tích lũy rác vào hàng đợi
        payload = {"room": {k: room.get(k) for k in ROOM_INSERT_FIELDS},
                   "building": building or {}, "address_key": (building or {}).get("address_key", "")}
        idem = f"room:{room['id']}:v{int(room.get('version') or 0)}:{op}"
        ok = self.db.queue_push(idem, "room", room["id"], op, payload)
        if ok:
            self.emit("queue_changed", **self.db.queue_count())
        return ok

    def enqueue_building(self, building: Dict[str, Any]) -> bool:
        if not self.settings.get("google_enabled"):
            return False
        idem = f"building:{building['id']}:v{int(building.get('version') or 0)}"
        return self.db.queue_push(idem, "building", building["id"], "upsert",
                                  {"building": building})

    def enqueue_stats(self, stats: Dict[str, Any]) -> bool:
        if not self.settings.get("google_enabled"):
            return False
        return self.db.queue_push(f"stats:{now_iso()}", "stats", "all", "upsert", {"stats": stats})

    # ---------------------------------------------------------------- pull merge
    def apply_remote_rows(self, remote_rows: List[Any]) -> Dict[str, int]:
        """Gộp dữ liệu kéo từ Google Sheets (máy khác đã sửa) vào local.

        Nguyên tắc an toàn:
        - local đang có lệnh chờ sync  -> GIỮ local (sẽ đẩy lên sau)
        - remote khác hash lần sync cuối -> remote đổi -> cập nhật local
        - cả 2 cùng đổi -> giữ local + báo conflict (không ghi đè ngầm)
        """
        out = {"added": 0, "updated": 0, "unchanged": 0, "conflicts": 0}
        idmap = self.db.idmap_all()
        pending = {r["entity_id"] for r in self.db.query(
            "SELECT DISTINCT entity_id FROM sync_queue WHERE state IN ('pending','failed','running')")}
        actor = "Google Sheets (sync)"

        with self._wlock:
            for rr in remote_rows:
                payload = dict(rr.payload)
                key = payload.get("_address_key") or ""
                try:
                    building = self.ensure_building(payload, actor=actor)
                except ValueError:
                    out["conflicts"] += 1
                    continue
                payload["building_id"] = building["id"]
                ident = DuplicateChecker.identity_key(payload, building)
                existing = (self.db.find_room_identity(building["id"], ident) if ident else None)
                info = idmap.get(existing["id"]) if existing else None

                if existing:
                    if existing["id"] in pending:
                        out["unchanged"] += 1
                        continue
                    stored_hash = (info or {}).get("remote_hash") or ""
                    if stored_hash == rr.content_hash:
                        out["unchanged"] += 1
                        continue
                    if stored_hash and info and info.get("local_hash") and \
                            info.get("local_hash") != stored_hash:
                        # local đã đổi sau lần sync cuối + remote cũng đổi -> xung đột
                        out["conflicts"] += 1
                        log.warning("Xung đột đồng bộ tại phòng %s - giữ bản local", existing["id"])
                        continue
                    changes = self._payload_to_changes(payload, existing)
                    if changes:
                        try:
                            self.update_room(existing["id"], changes, actor=actor,
                                             force=True, note="Đồng bộ từ Google Sheets")
                            out["updated"] += 1
                        except DuplicateError:
                            out["conflicts"] += 1
                    else:
                        out["unchanged"] += 1
                    with self.db.write() as conn:
                        self.db.idmap_upsert_tx(conn, existing["id"], "", 0, 0, 0,
                                                rr.content_hash, rr.content_hash, now_iso())
                else:
                    try:
                        self.add_room(payload, actor=actor, force=True)
                        out["added"] += 1
                        rid = (self.db.find_room_identity(building["id"], ident) or {}).get("id")
                        if rid:
                            with self.db.write() as conn:
                                self.db.idmap_upsert_tx(conn, rid, "", 0, 0, 0,
                                                        rr.content_hash, rr.content_hash, now_iso())
                    except DuplicateError:
                        out["conflicts"] += 1
        if out["added"] or out["updated"]:
            self.emit("rooms_changed", ids=[], action="pull")
            self.emit("stats_changed")
            self.emit("buildings_changed")
        return out

    # ================================================================ TIỆN ÍCH
    def sync_push_stats(self) -> None:
        """Đưa bảng Thống Kê Nhanh lên Sheets (1 lệnh)."""
        self.enqueue_stats(self.stats())

    def export_rooms(self, text: str = "", f: Optional[RoomFilter] = None) -> List[Dict[str, Any]]:
        return self.rooms(text, f)
