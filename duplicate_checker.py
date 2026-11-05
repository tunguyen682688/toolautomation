# -*- coding: utf-8 -*-
"""duplicate_checker.py - Hệ thống kiểm tra trùng dữ liệu (5 lớp) cho phòng & địa chỉ.

Các lớp kiểm tra khi THÊM phòng mới:
  L1. Địa chỉ đã tồn tại chưa?           -> building_exists (info / tự liên kết)
  L2. Tòa nhà có trong danh mục chưa?     -> building_exists
  L3. Căn hộ (tòa nhà + số căn) tồn tại? -> room_exists (BLOCK)
  L4. Trùng mã phòng ở TÒA KHÁC          -> room_code_cross (WARN - mã chỉ unique
      trong cùng tòa, 2 tòa cùng mã là hợp lệ NHƯNG phải biết để kiểm tra kỹ)
  L5. Bản ghi tương tự về địa chỉ + căn? -> similar (WARN - "nghi ngờ trùng do khác cách viết")

Kết quả luôn kèm: thông tin phòng hiện có, trạng thái hiện tại, thời gian cập nhật gần nhất
để người dùng MỞ bản ghi cũ thay vì tạo mới.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import text_utils as tu
from logger import get_logger

log = get_logger("dup")

SIMILAR_THRESHOLD = 0.86


@dataclass
class Finding:
    kind: str                 # building_new|building_exists|room_exists|similar|invalid
    severity: str             # info|warn|block
    message: str
    room_id: Optional[str] = None
    building_id: Optional[str] = None
    room: Optional[Dict] = None
    building: Optional[Dict] = None
    similarity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "severity": self.severity, "message": self.message,
            "room_id": self.room_id, "building_id": self.building_id, "similarity": self.similarity,
            "room": {k: self.room.get(k) for k in
                     ("id", "room_code", "unit_code", "status", "updated_at", "price", "address", "room_type")}
            if self.room else None,
        }


@dataclass
class CheckResult:
    findings: List[Finding] = field(default_factory=list)
    building: Optional[Dict] = None
    existing_room: Optional[Dict] = None

    @property
    def has_block(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    @property
    def has_warn(self) -> bool:
        return any(f.severity == "warn" for f in self.findings)

    @property
    def recommended(self) -> str:
        """create | open_existing | confirm"""
        if any(f.kind == "room_exists" for f in self.findings):
            return "open_existing"
        if self.has_warn:
            return "confirm"
        return "create"

    @property
    def room_exists(self) -> bool:
        return any(f.kind == "room_exists" for f in self.findings)

    def messages(self, sep: str = "\n") -> str:
        return sep.join(f.message for f in self.findings)


# Các trường có ý nghĩa đối với "trùng hoàn toàn"
FINGERPRINT_FIELDS = (
    "house_number", "street", "ward", "district", "unit_code", "floor",
    "room_code", "room_type", "price", "deposit", "status", "surveyed",
    "capacity", "ev_support", "pet_policy", "owner_phone",
)


def fingerprint(payload: Dict[str, Any]) -> str:
    """Vân tay bản ghi: địa chỉ + số căn + giá + loại + trạng thái... (đã chuẩn hoá)."""
    parts = []
    for k in FINGERPRINT_FIELDS:
        v = payload.get(k, "")
        if k in ("price", "deposit", "surveyed", "ev_support"):
            # phân biệt NULL (Chưa biết) với 0 (Không) -> "?" cho giá trị chưa rõ
            if v is None or v == "":
                v = "?"
            elif k in ("surveyed", "ev_support"):
                v = str(int(bool(v)))
            else:
                v = int(v or 0)
        else:
            v = tu.norm_key(v) if k in ("house_number", "street", "unit_code", "room_code") else tu.norm(v)
        parts.append(f"{k}={v}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


class DuplicateChecker:
    def __init__(self, db):
        self.db = db

    # ---------------------------------------------------------------- helpers
    def _resolve_building(self, payload: Dict[str, Any]) -> Optional[Dict]:
        bid = payload.get("building_id")
        if bid:
            b = self.db.get_building(bid)
            if b:
                return b
        if payload.get("address_key"):
            return self.db.find_building_by_address(payload["address_key"])
        if payload.get("street") or payload.get("house_number"):
            key = tu.address_key(payload.get("house_number"), payload.get("street"),
                                 payload.get("ward"), payload.get("district"))
            return self.db.find_building_by_address(key) if key else None
        return None

    @staticmethod
    def identity_key(payload: Dict[str, Any], building: Optional[Dict]) -> str:
        """Khoá nhận diện căn hộ: số căn thực tế, fallback mã phòng (KHÔNG suy đoán)."""
        unit = tu.unit_key(payload.get("unit_code"))
        if unit:
            return unit
        code = payload.get("room_code")
        return tu.room_code_key(code) if tu.valid_room_code(code) else ""

    # ---------------------------------------------------------------- main check
    def check_room(self, payload: Dict[str, Any], exclude_id: Optional[str] = None) -> CheckResult:
        res = CheckResult()
        building = self._resolve_building(payload)
        res.building = building

        # L1/L2 - địa chỉ / tòa nhà
        if building:
            res.findings.append(Finding(
                kind="building_exists", severity="info",
                message=f"Địa chỉ đã có trong hệ thống: {building.get('display')} "
                        f"(tòa {building.get('code')}) -> sẽ tự liên kết.",
                building_id=building["id"], building=building,
            ))
        else:
            addr = tu.building_display(payload.get("house_number"), payload.get("street"),
                                       payload.get("ward"), payload.get("district"))
            res.findings.append(Finding(
                kind="building_new", severity="info",
                message=f"Địa chỉ mới chưa có trong danh mục: {addr} -> sẽ tạo tòa nhà mới.",
            ))
            # L5 - địa chỉ tương tự (khác cách viết) vẫn cần soát
            for b in self._similar_buildings(payload):
                res.findings.append(Finding(
                    kind="similar", severity="warn",
                    message=f"Nghi ngờ trùng địa chỉ (tương đồng {int(b['_ratio'] * 100)}%): "
                            f"{b.get('display')} - kiểm tra bạn có đang nhập lại tòa này không.",
                    building_id=b["id"], building=b, similarity=b["_ratio"],
                ))

        if not building and not (payload.get("street") or payload.get("house_number")):
            res.findings.append(Finding(kind="invalid", severity="block",
                                        message="Thiếu thông tin địa chỉ (số nhà/tên đường) -> không thể xác định tòa nhà."))
            return res

        # L3 - căn hộ đã tồn tại (khóa: building_id + số căn / mã phòng)
        ident = self.identity_key(payload, building)
        if building and ident:
            existing = self.db.find_room_identity(building["id"], ident)
            if existing and existing["id"] != exclude_id:
                if existing.get("address") is None:
                    existing = self.db.get_room(existing["id"]) or existing
                res.existing_room = existing
                res.findings.append(Finding(
                    kind="room_exists", severity="block",
                    message=(f"PHÒNG ĐÃ TỒN TẠI: {existing.get('room_code') or existing.get('unit_code')} - "
                             f"{existing.get('address')} | trạng thái: {RoomStatusLabel(existing.get('status'))} | "
                             f"cập nhật: {existing.get('updated_at')}"),
                    room_id=existing["id"], building_id=building["id"], room=existing,
                ))
            # L4 "trùng mã phòng ở tòa khác" xử lý RIÊNG bên dưới ở mức WARN
            # (mã phòng vẫn chỉ cần unique TRONG CÙNG TÒA - khóa building_id + unit_key).
        # L4 - TRÙNG MÃ PHÒNG Ở TÒA KHÁC (WARN, KHÔNG chặn): mã phòng chỉ cần unique
        # TRONG CÙNG TÒA - 2 tòa khác nhau cùng mã là hợp lệ, nhưng người nhập phải
        # BIẾT mã đó đang dùng ở tòa nào để kiểm tra kỹ trước khi lưu.
        code_key = tu.room_code_key(payload.get("room_code") or "")
        if code_key and any(c.isdigit() for c in str(payload.get("room_code") or "")):
            others = self.db.search_rooms_sql(
                "r.deleted=0 AND r.room_code_key=? AND r.building_id<>? AND r.id<>?",
                (code_key, (building or {}).get("id") or "", exclude_id or ""))
            if others:
                seen_b, parts = set(), []
                for o in others:
                    if o.get("building_id") in seen_b:
                        continue           # 1 dòng/tòa là đủ (tòa nhiều phòng cùng mã)
                    seen_b.add(o.get("building_id"))
                    parts.append(f"{o.get('room_code') or o.get('unit_code')} - "
                                 f"{o.get('address')} ({RoomStatusLabel(o.get('status'))})")
                    if len(parts) >= 3:
                        break
                res.findings.append(Finding(
                    kind="room_code_cross", severity="warn",
                    message=(f"Mã phòng '{payload.get('room_code')}' đã có ở "
                             f"{len(seen_b)} tòa khác: " + " · ".join(parts)
                             + (" …" if len(others) > len(parts) else "")
                             + " -> kiểm tra kỹ có phải phòng này không (vẫn được lưu)."),
                ))

        # L3b - THIẾU số căn + mã phòng không hợp lệ: không có khoá duy nhất ->
        # chặn theo "cùng tòa + trùng văn bản mã phòng" (tránh nhập trùng vô hạn)
        if building and not ident:
            code_raw = tu.norm(payload.get("room_code"))
            if code_raw:
                for other in self.db.search_rooms_sql(
                        "r.building_id=? AND r.deleted=0", (building["id"],)):
                    if other["id"] == (exclude_id or ""):
                        continue
                    if tu.norm(other.get("room_code")) == code_raw and not (other.get("unit_key") or ""):
                        res.existing_room = other
                        res.findings.append(Finding(
                            kind="room_exists", severity="block",
                            message=(f"PHÒNG ĐÃ TỒN TẠI (chưa có số căn): mã '{payload.get('room_code')}' "
                                     f"tại {other.get('address')} | trạng thái: "
                                     f"{RoomStatusLabel(other.get('status'))} | cập nhật: {other.get('updated_at')}"),
                            room_id=other["id"], building_id=building["id"], room=other,
                        ))
                        break

        # L5 - bản ghi tương tự cùng tòa (khác cách gõ số căn)
        if building:
            for other in self._similar_rooms(building, payload, exclude_id, ident):
                res.findings.append(Finding(
                    kind="similar", severity="warn",
                    message=(f"Nghi ngờ trùng căn hộ cùng tòa: '{other.get('unit_code') or other.get('room_code')}' "
                             f"(trạng thái: {RoomStatusLabel(other.get('status'))}, "
                             + (f"giá {tu.format_money(other.get('price'))}đ)."
                                if other.get("price") not in (None, "") else "giá chưa rõ).")),
                    room_id=other["id"], building_id=building["id"], room=other,
                ))
        return res

    # ---------------------------------------------------------------- similarity scans
    def _similar_buildings(self, payload: Dict[str, Any]) -> List[Dict]:
        key = tu.address_key(payload.get("house_number"), payload.get("street"),
                             payload.get("ward"), payload.get("district"))
        if not key:
            return []
        out = []
        for b in self.db.list_buildings():
            ratio = tu.similar_address(key, b.get("address_key", ""))
            if ratio >= SIMILAR_THRESHOLD:
                b = dict(b)
                b["_ratio"] = ratio
                out.append(b)
        out.sort(key=lambda x: -x["_ratio"])
        return out[:3]

    def _similar_rooms(self, building: Dict, payload: Dict[str, Any],
                       exclude_id: Optional[str], ident: str) -> List[Dict]:
        rows = self.db.search_rooms_sql(
            "r.building_id=? AND r.deleted=0", (building["id"],), order="r.unit_key"
        )
        out = []
        digits_in = tu.digits_only(payload.get("unit_code")) or tu.digits_only(payload.get("room_code"))
        code_in = tu.norm(payload.get("room_code"))
        for other in rows:
            if exclude_id and other["id"] == exclude_id:
                continue
            if ident and (other.get("unit_key") or "") == ident:
                continue  # đã bắt ở L3
            od = tu.digits_only(other.get("unit_code")) or tu.digits_only(other.get("room_code"))
            if digits_in and od and digits_in == od:
                out.append(other)
                continue
            # mã phòng KHÔNG hợp lệ (thiếu số căn) nhưng cùng tòa trùng đúng văn bản mã phòng
            if code_in and not ident and tu.norm(other.get("room_code")) == code_in:
                out.append(other)
                continue
            # cùng tòa + 1 trong 2 thiếu số căn -> nghi ngờ
            if not ident and not (other.get("unit_key") or ""):
                out.append(other)
        return out[:5]

    # ---------------------------------------------------------------- import classification
    def classify(self, payload: Dict[str, Any], check: Optional[CheckResult] = None,
                 seen_fingerprints: Optional[Dict[str, int]] = None,
                 seen_identities: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """Phân loại 1 dòng dữ liệu khi import Excel.

        Trả về {'kind': new|duplicate|changed|suspect|error, 'reason': str, 'existing': dict|None}
        - new:       thêm mới
        - duplicate: trùng hoàn toàn -> KHÔNG thêm lại
        - changed:   trùng khoá nhưng có trường khác -> đề xuất cập nhật bản ghi cũ
        - suspect:   nghi ngờ trùng (khác cách viết / trùng mã phòng) -> cần xác nhận
        - error:     thiếu/không hợp lệ -> không nhập
        """
        seen_fingerprints = seen_fingerprints if seen_fingerprints is not None else {}
        seen_identities = seen_identities if seen_identities is not None else {}

        if not (payload.get("street") or payload.get("house_number")):
            return {"kind": "error", "reason": "Thiếu địa chỉ (số nhà / tên đường)", "existing": None}

        check = check or self.check_room(payload)
        fp = fingerprint(payload)

        # Trùng ngay trong file Excel
        if fp in seen_fingerprints:
            return {"kind": "duplicate", "reason": f"Trùng hoàn toàn với dòng {seen_fingerprints[fp]} trong file",
                    "existing": None}
        building = check.building
        ident = self.identity_key(payload, building)
        # Trùng khoá NGAY TRONG FILE - hoạt động cả khi tòa nhà chưa có trong DB
        addr_key = tu.address_key(payload.get("house_number"), payload.get("street"),
                                  payload.get("ward"), payload.get("district"))
        bkey = building["id"] if building else (f"LOCAL:{addr_key}" if addr_key else "")
        if ident and bkey and f"{bkey}|{ident}" in seen_identities:
            return {"kind": "suspect",
                    "reason": f"Trùng số căn/mã phòng với dòng {seen_identities[f'{bkey}|{ident}']} "
                              f"trong file Excel (cùng địa chỉ {addr_key})",
                    "existing": None}

        invalid = [f for f in check.findings if f.kind == "invalid"]
        if invalid:
            return {"kind": "error", "reason": invalid[0].message, "existing": None}

        existing = check.existing_room
        if existing:
            if self._same_significant(payload, existing):
                return {"kind": "duplicate",
                        "reason": "Trùng hoàn toàn với bản ghi đang có (đã có sẵn, không thêm lại)",
                        "existing": existing}
            diff = self._diff_fields(payload, existing)
            return {"kind": "changed",
                    "reason": "Đã tồn tại, có thay đổi: " + ", ".join(diff[:6]),
                    "existing": existing}

        if any(f.kind == "similar" for f in check.findings):
            return {"kind": "suspect",
                    "reason": "Nghi ngờ trùng do khác cách viết địa chỉ/số căn - cần xác nhận",
                    "existing": None}
        return {"kind": "new", "reason": "Dữ liệu mới", "existing": None}

    # ---------------------------------------------------------------- field compare
    COMPARE_MAP = {
        "house_number": "house_number", "street": "street", "ward": "ward", "district": "district",
        "unit_code": "unit_code", "floor": "floor", "room_code": "room_code", "room_type": "room_type",
        "price": "price", "deposit": "deposit", "capacity": "capacity", "rating": "rating",
        "owner_phone": "owner_phone", "zalo_group": "zalo_group", "drive_link": "drive_link",
        "notes": "notes", "pet_policy": "pet_policy",
        "ev_support": "ev_support", "surveyed": "surveyed", "foreign_guest": "foreign_guest",
        "area": "area",
        "service_fee": "service_fee", "access_hours": "access_hours", "amenities": "amenities",
    }

    @classmethod
    def _norm_val(cls, field_name: str, v: Any) -> str:
        if v is None:
            return ""
        if field_name in ("price", "deposit"):
            return str(int(v or 0))
        if field_name == "ev_support":
            return "1" if v else "0"
        if field_name == "surveyed":
            return "1" if v else "0"
        if field_name == "foreign_guest":
            return "1" if v else "0"
        if field_name == "area":
            return tu.norm(v)
        return tu.norm(v)

    def _diff_fields(self, payload: Dict, existing: Dict) -> List[str]:
        """Trả về danh sách tên trường khác nhau giữa payload và bản ghi hiện có."""
        label = {c["name"]: c["header"] for c in _room_cols()}
        diffs = []
        for pf, ef in self.COMPARE_MAP.items():
            if pf not in payload:
                continue
            if ef not in existing:      # bản ghi không chứa cột này (vd: địa chỉ nằm ở buildings) -> bỏ qua
                continue
            a = self._norm_val(pf, payload.get(pf))
            b = self._norm_val(pf, existing.get(ef))
            if a and a != b:
                diffs.append(label.get(pf, pf))
        # trạng thái
        if payload.get("status") and RoomStatusKey(payload.get("status")) != existing.get("status"):
            diffs.append("Trạng thái")
        # lưu ý: surveyed/ev_support đã nằm trong vòng COMPARE_MAP ở trên -
        # _norm_val phân biệt None ("" = Chưa biết) vs 0 ("0" = Không) -> không cần so tay,
        # so tay kiểu bool() cũ còn làm nhãn "Xe điện"/"Khảo sát" xuất hiện 2 lần.
        return diffs

    def _same_significant(self, payload: Dict, existing: Dict) -> bool:
        """So sánh các trường chính để quyết định 'trùng hoàn toàn'."""
        pairs = [
            ("room_type", tu.norm), ("unit_code", tu.norm_key), ("floor", tu.norm_key),
            ("room_code", tu.room_code_key), ("owner_phone", tu.phone_key),
            ("pet_policy", tu.norm),
        ]
        for f, fn in pairs:
            pv = payload.get(f)
            if pv in (None, ""):
                continue
            if fn(pv) != fn(existing.get(f) or ""):
                return False
        for f in ("price", "deposit"):
            pv = payload.get(f)
            if pv in (None, "", 0):
                continue
            if int(pv or 0) != int(existing.get(f) or 0):
                return False
        if payload.get("status"):
            if RoomStatusKey(payload.get("status")) != existing.get("status"):
                return False
        # 3 trạng thái: payload nói RÕ (0/1) mà bản ghi hiện có khác (kể cả NULL=Chưa biết)
        # -> không phải "trùng hoàn toàn". Payload None -> bỏ qua (chưa rõ thì không kết luận).
        for f in ("ev_support", "surveyed"):
            pv = payload.get(f)
            if pv is None:
                continue
            ev = existing.get(f)
            na, nb = 1 if pv else 0, (None if ev is None else (1 if ev else 0))
            if na != nb:
                return False
        return True

    @staticmethod
    def _enrich(payload: Dict, existing: Dict) -> Dict:
        merged = dict(existing)
        merged.update({k: v for k, v in payload.items() if v not in (None, "")})
        return merged


# tiny wrappers để tránh import vòng với models
def RoomStatusLabel(key: str) -> str:
    try:
        from models import RoomStatus
        return RoomStatus.label(key)
    except Exception:
        return key or "-"


def RoomStatusKey(text) -> str:
    from models import RoomStatus
    return RoomStatus.from_text(text)


def _room_cols():
    from models import ROOM_COLUMNS
    return ROOM_COLUMNS
