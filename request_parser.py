# -*- coding: utf-8 -*-
"""request_parser.py - Hiểu yêu cầu khách bằng tiếng Việt (được phép không dấu)
và tìm kiếm MỞ RỘNG KHU VỰC theo 4 vòng.

Ví dụ khách hỏi:
    "phòng 7tr full nội thất có thang máy, gửi xe, quanh P13 hay đường Bình Lợi"
-> parse_request():
    giá 6.3tr-7.7tr (7tr +/-10%), tiện ích [nội thất, thang máy, gửi xe],
    phường ["13"], đường ["binh loi"], nearby=True.

-> search_tiers(mgr, req):
    Vòng 1 - ĐÚNG KHU VỰC : đúng phường / đúng đường / đúng quận khách nói
    Vòng 2 - LÂN CẬN      : cùng quận với khu vực khách hỏi
    Vòng 3 - GIÁP RANH    : các quận liền kề (bảng ước tính NEIGHBORS)
    Vòng 4 - TOÀN KHO     : còn lại vẫn khớp giá / tiện ích

Mỗi vòng trả về list phòng + RoomFilter để mở thẳng trên Bảng phòng.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import text_utils as tu

# ------------------------------------------------------------------ từ điển tiện ích
# (một nhóm = các từ đồng nghĩa; khớp BẤT KỲ từ nào trong nhóm;
#  các nhóm phải khớp TOÀB - AND giữa nhóm, OR trong nhóm)
AMENITY_GROUPS = [
    ("Thang máy", ["thang may"]),
    ("Nội thất", ["noi that"]),
    ("Gửi xe", ["gui xe", "do xe", "giu xe", "bai xe"]),
    ("Máy lạnh", ["may lanh", "dieu hoa"]),
    ("Nước nóng", ["nuoc nong", "nong lanh"]),
    ("Wifi", ["wifi"]),
    ("Giặt nước", ["giat nuoc"]),
    ("Gần metro", ["metro", "ga tau"]),
]

# tiện ích ánh xạ sang trường có cấu trúc của phòng
STRUCTURED = [
    ("Xe điện", ["xe dien"], "ev"),
    ("Thú cưng", ["thu cung", "cho nuoi", "pet"], "pet"),
    ("Khách nước ngoài", ["nuoc ngoai", "khach tay"], "foreign"),
]

_TYPE_PATTERNS = [
    ("studio", "Studio"),
    (r"1\s*(?:pn|phong ngu)", "1 Phòng Ngủ"),
    (r"2\s*(?:pn|phong ngu)", "2 Phòng Ngủ"),
    (r"3\s*(?:pn|phong ngu)", "3 Phòng Ngủ"),
    ("duplex", "Duplex"),
    ("penthouse", "Penthouse"),
    ("can ho dich vu", "Căn hộ dịch vụ"),
]

# quận quen biết (để nhận diện "bình thạnh" không cần tiền tố "quận")
KNOWN_DISTRICTS = [
    "binh thanh", "go vap", "phu nhuan", "thu duc", "tan binh", "tan phu",
    "binh tan", "binh chanh", "nha be", "can gio", "hoc mon", "cu chi",
]

# bảng giáp ranh ƯỚC TÍNH (không chính thức - chỉ để gợi ý mở rộng)
NEIGHBORS: Dict[str, Set[str]] = {
    "binh thanh": {"go vap", "phu nhuan", "thu duc", "1", "3", "10", "12"},
    "go vap": {"binh thanh", "phu nhuan", "12", "thu duc"},
    "phu nhuan": {"binh thanh", "go vap", "1", "3", "10", "tan binh"},
    "thu duc": {"binh thanh", "go vap", "9", "2"},
    "1": {"3", "4", "binh thanh", "phu nhuan"},
    "2": {"9", "thu duc", "7"},
    "3": {"1", "10", "binh thanh", "phu nhuan", "5", "11"},
    "4": {"1", "5", "7"},
    "5": {"4", "6", "11", "3"},
    "6": {"5", "11", "binh tan", "tan phu"},
    "7": {"4", "2", "binh chanh"},
    "9": {"2", "thu duc"},
    "10": {"3", "11", "5", "phu nhuan", "tan binh", "go vap"},
    "11": {"3", "10", "5", "6", "binh tan", "tan binh"},
    "12": {"go vap", "binh tan", "tan binh", "binh chanh"},
    "tan binh": {"phu nhuan", "go vap", "10", "11", "tan phu"},
    "tan phu": {"tan binh", "6", "binh tan", "11"},
    "binh tan": {"tan phu", "6", "11", "12", "binh chanh"},
}

_NEARBY_WORDS = ("xung quanh", "gan", "lan can", "quanh", "vic", "vung lan can")
_STOP_STREETS = {
    "hay", "hoac", "va", "o", "gan", "xung", "quanh", "lan", "can", "quan",
    "phuong", "p", "kp", "khu", "vuc", "pho", "duong", "so", "tram", "mat",
    "tien", "phia", "ven", "thanh", "pho", "lat", "nha", "cho", "truong",
}


def _round100k(v: float) -> int:
    return int(round(v / 100000.0)) * 100000


# ------------------------------------------------------------------ mô hình yêu cầu
@dataclass
class Request:
    raw: str = ""
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    price_label: str = ""
    keyword_groups: List[List[str]] = field(default_factory=list)   # AND giữa nhóm
    keyword_names: List[str] = field(default_factory=list)          # nhãn tương ứng từng nhóm
    keywords_label: List[str] = field(default_factory=list)          # nhãn dễ đọc
    ev: Optional[bool] = None
    pet: Optional[bool] = None
    foreign: Optional[bool] = None
    room_types: List[str] = field(default_factory=list)
    ward_keys: List[str] = field(default_factory=list)               # "13"
    street_keys: List[str] = field(default_factory=list)             # "binh loi"
    district_keys: List[str] = field(default_factory=list)           # "binh thanh"
    area_label: str = ""
    nearby: bool = False

    def is_empty(self) -> bool:
        return not any([
            self.price_min, self.price_max, self.keyword_groups, self.ward_keys,
            self.street_keys, self.district_keys, self.room_types,
            self.ev, self.pet, self.foreign,
        ])


# ------------------------------------------------------------------ parse giá
_MONEY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(trieu|tr|nghin|n|k)\b")
_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[-~to]+\s*(\d+(?:[.,]\d+)?)\s*(trieu|tr)\b")
_MAX_WORDS = ("duoi", "toi da", "khong qua", "khong hon", "nho hon", "xuong", "toi da")
_MIN_WORDS = ("tu", "tren", "toi thieu", "tro len")


def _to_vnd(num: float, unit: str) -> float:
    if unit in ("trieu", "tr"):
        return num * 1_000_000
    return num * 1_000      # nghin / n / k


def _parse_price(req: Request, s: str):
    # 1) khoảng "6-8 trieu" / "6-8tr"
    m = _RANGE_RE.search(s)
    if m:
        req.price_min = _round100k(_to_vnd(float(m.group(1).replace(",", ".")), "tr"))
        req.price_max = _round100k(_to_vnd(float(m.group(2).replace(",", ".")), "tr"))
        req.price_label = f"{req.price_min / 1e6:g}–{req.price_max / 1e6:g} triệu"
        return
    # 2) từng con số có đơn vị (bỏ qua nếu đứng sau "cọc/đặt cọc")
    hits = []
    for m in _MONEY_RE.finditer(s):
        before = s[max(0, m.start() - 14):m.start()]
        if re.search(r"\b(coc|dat coc|tien coc)\W*$", before):
            continue
        val = _to_vnd(float(m.group(1).replace(",", ".")), m.group(2))
        if val < 100_000:      # "500k" trong ngữ cảnh này là giá trị khác, bỏ qua
            continue
        hits.append((m, val))
    if not hits:
        return
    # nếu có nhiều con số -> lấy con đầu làm mốc giá chính
    m, val = hits[0]
    before = s[max(0, m.start() - 16):m.start()]
    if any(w in before for w in _MAX_WORDS):
        req.price_max = _round100k(val)
        req.price_label = f"≤ {req.price_max / 1e6:g} triệu"
    elif any(w in before for w in _MIN_WORDS):
        req.price_min = _round100k(val)
        req.price_label = f"≥ {req.price_min / 1e6:g} triệu"
    else:
        # "phòng 7tr" = tầm giá 7 triệu -> +/-10%
        req.price_min = _round100k(val * 0.9)
        req.price_max = _round100k(val * 1.1)
        req.price_label = f"≈ {val / 1e6:g} triệu (±10%)"


# ------------------------------------------------------------------ parse khu vực
def _extract_streets(s: str) -> List[str]:
    out: List[str] = []
    toks = s.split()
    i = 0
    while i < len(toks):
        if toks[i] in ("duong", "du", "d"):
            j, words = i + 1, []
            while j < len(toks) and len(words) < 3 and toks[j] not in _STOP_STREETS \
                    and not toks[j].isdigit():
                words.append(toks[j])
                j += 1
            if words:
                out.append(" ".join(words))
            i = j
        else:
            i += 1
    return out


def parse_request(text: str) -> Request:
    """Tách yêu cầu khách tự nhiên thành Request có cấu trúc."""
    req = Request(raw=str(text or ""))
    s = tu.norm(req.raw)
    if not s:
        return req

    _parse_price(req, s)

    # tiện ích có cấu trúc (xe điện / pet / khách nước ngoài)
    for label, syns, attr in STRUCTURED:
        if any(x in s for x in syns):
            setattr(req, attr, True)
            req.keywords_label.append(label)

    # tiện ích text (đối chiếu với search_norm của phòng)
    for label, syns in AMENITY_GROUPS:
        if any(x in s for x in syns):
            req.keyword_groups.append(list(syns))
            req.keyword_names.append(label)
            req.keywords_label.append(label)

    # loại phòng
    for pat, name in _TYPE_PATTERNS:
        if re.search(r"\b" + pat + r"\b", s):
            req.room_types.append(name)

    # phường: "p13", "p.13", "phuong 13", "phường 13"
    for m in re.finditer(r"\b(?:p|phuong)\.?\s*(\d{1,2})\b", s):
        if m.group(1) not in req.ward_keys:
            req.ward_keys.append(m.group(1))

    # quận số: "q1", "quan 3"
    for m in re.finditer(r"\b(?:q|quan)\.?\s*(\d{1,2})\b", s):
        if m.group(1) not in req.district_keys:
            req.district_keys.append(m.group(1))

    # quận tên: "bình thạnh", "gò vấp"... (không cần tiền tố)
    for name in KNOWN_DISTRICTS:
        if re.search(r"\b" + re.escape(name) + r"\b", s) and name not in req.district_keys:
            req.district_keys.append(name)

    # đường: "đường Bình Lợi" / "duong binh loi"
    for st in _extract_streets(s):
        if st not in req.street_keys:
            req.street_keys.append(st)

    # từ khóa lân cận
    req.nearby = any(w in s for w in _NEARBY_WORDS)

    # nhãn khu vực hiển thị
    parts = ([f"P. {k}" for k in req.ward_keys]
             + [f"Đường {k.title()}" for k in req.street_keys]
             + [f"Q. {k.title()}" for k in req.district_keys])
    req.area_label = " · ".join(parts)
    return req


# ------------------------------------------------------------------ tìm kiếm mở rộng
def _hay(room: Dict[str, Any]) -> str:
    if room.get("search_norm"):
        return str(room["search_norm"])
    return tu.norm(" ".join(str(room.get(k) or "") for k in
                            ("address", "room_type", "notes", "room_code", "unit_code")))


def _match_keywords(room: Dict[str, Any], groups: List[List[str]]) -> bool:
    hay = _hay(room)
    return all(any(syn in hay for syn in g) for g in groups)


def _anchor_districts(mgr, req: Request) -> Set[str]:
    """Quận của khu vực khách hỏi (tìm qua tòa nhà: phường/đường -> quận)."""
    anchors: Set[str] = set(req.district_keys)
    if not req.ward_keys and not req.street_keys:
        return anchors
    for b in mgr.buildings():
        d = tu.canon_district(b.get("district"))
        if not d:
            continue
        if req.ward_keys and tu.canon_ward(b.get("ward")) in req.ward_keys:
            anchors.add(d)
        for sk in req.street_keys:
            if sk in tu.norm_key(b.get("street") or ""):
                anchors.add(d)
    return anchors


def _tier_of(room: Dict[str, Any], req: Request, anchors: Set[str],
             neighbors: Set[str]) -> int:
    """0=đúng khu vực, 1=cùng quận, 2=giáp ranh, 3=còn lại."""
    if req.ward_keys or req.street_keys or req.district_keys:
        w = tu.canon_ward(room.get("ward"))
        if req.ward_keys and w in req.ward_keys:
            return 0
        street = tu.norm_key(room.get("street") or "")
        if req.street_keys and any(k in street for k in req.street_keys):
            return 0
        d = tu.canon_district(room.get("district"))
        if req.district_keys and d in req.district_keys:
            return 0
        if d in anchors:
            return 1
        if d in neighbors:
            return 2
    return 3


def tier_room_filter(req: Request, rooms: List[Dict[str, Any]],
                     statuses: Optional[List[str]]) -> Any:
    """RoomFilter mở thẳng trên Bảng phòng cho đúng tập phòng của vòng."""
    from models import RoomFilter
    kw: Dict[str, Any] = dict(
        price_min=req.price_min, price_max=req.price_max,
        statuses=statuses or None,
        ev_support=req.ev, pet_allowed=req.pet, foreign_guest=req.foreign,
        room_types=list(req.room_types) or None,
    )
    wards = {tu.canon_ward(r.get("ward")) for r in rooms} - {""}
    districts = {tu.canon_district(r.get("district")) for r in rooms} - {""}
    if len(wards) == 1:
        kw["ward"] = next(iter(wards))
    elif len(districts) == 1:
        kw["district"] = next(iter(districts))
    return RoomFilter(**kw)


TIER_TITLES = {
    0: "🏆 Đúng khu vực",
    1: "📍 Lân cận — cùng quận",
    2: "🔀 Giáp ranh — quận liền kề",
    3: "🌐 Toàn kho — khu vực khác",
}


def search_tiers(mgr, req: Request, statuses: Optional[List[str]] = ("vacant",),
                 limit: int = 60) -> List[Dict[str, Any]]:
    """Tìm phòng theo yêu cầu, trả về các vòng kết quả (chỉ giữ vòng không rỗng).

    Mỗi phần tử: {key, title, hint, rooms, total, filter}
    """
    from models import RoomFilter
    if req.is_empty():
        return []
    statuses = list(statuses) if statuses else None
    f = RoomFilter(
        price_min=req.price_min, price_max=req.price_max,
        statuses=statuses,
        ev_support=req.ev, pet_allowed=req.pet, foreign_guest=req.foreign,
        room_types=list(req.room_types) or None,
    )
    rooms = mgr.rooms("", f)
    relaxed: List[str] = []          # tiện ích đã tự nới (khách yêu cầu nhưng kho không đủ)
    if req.keyword_groups:
        base_rooms = rooms
        groups = [list(g) for g in req.keyword_groups]
        names = list(req.keyword_names)
        while groups:
            rooms = [r for r in base_rooms if _match_keywords(r, groups)]
            if rooms:
                break
            relaxed.append(names.pop())      # bỏ bớt 1 tiện ích (lấy từ cuối) rồi thử lại
            groups.pop()
    if not rooms:
        return []

    anchors = _anchor_districts(mgr, req)
    neighbors: Set[str] = set()
    for a in anchors:
        neighbors |= NEIGHBORS.get(a, set())
    neighbors -= anchors

    buckets: Dict[int, List[Dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
    for r in rooms:
        buckets[_tier_of(r, req, anchors, neighbors)].append(r)

    anchor_label = " · ".join("Q. " + a.title() for a in sorted(anchors))
    hints = {
        0: req.area_label or "Khu vực khách yêu cầu",
        1: f"Gần {anchor_label}" if anchor_label else "",
        2: "Quận giáp ranh (ước tính)" if neighbors else "",
        3: "Khớp giá/tiện ích nhưng ở nơi khác",
    }

    out: List[Dict[str, Any]] = []
    for key in (0, 1, 2, 3):
        rs = sorted(buckets[key], key=lambda r: (int(r.get("price") or 0),
                                                 str(r.get("room_code") or "")))
        if not rs:
            continue
        out.append({
            "key": key,
            "title": TIER_TITLES[key],
            "hint": hints[key],
            "rooms": rs[:limit],
            "total": len(rs),
            "filter": tier_room_filter(req, rs, statuses),
        })
    if relaxed:
        out.append({
            "key": 4,
            "title": "💡 Gợi ý nới lỏng",
            "hint": "Kho không đủ điều kiện, đã tự bỏ bớt: " + ", ".join(relaxed),
            "rooms": [],
            "total": 0,
            "filter": None,
        })
    return out
