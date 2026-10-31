# -*- coding: utf-8 -*-
"""models.py - Mô hình dữ liệu nghiệp vụ: trạng thái phòng, cột dữ liệu, filter, dataclass."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

import text_utils as tu


# ---------------------------------------------------------------- Identifiers
def new_id(prefix: str) -> str:
    """ID nội bộ duy nhất, không phụ thuộc Google Sheets (không bao giờ sinh lại khi đổi trạng thái)."""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------- Room status
class RoomStatus:
    """10 trạng thái theo đặc tả. KEY lưu DB, label hiển thị, color cho bảng."""

    ORDER: List[str] = [
        "new", "unsurveyed", "surveyed", "vacant", "soon_vacant",
        "holding", "deposit", "rented", "suspended", "maintenance",
    ]
    LABEL: Dict[str, str] = {
        "new": "Phòng mới nhập",
        "unsurveyed": "Chưa khảo sát",
        "surveyed": "Đã khảo sát",
        "vacant": "Trống ở ngay",
        "soon_vacant": "Sắp trống",
        "holding": "Đang giữ chỗ",
        "deposit": "Đã nhận cọc",
        "rented": "Đã cho thuê",
        "suspended": "Tạm ngưng",
        "maintenance": "Bảo trì",
    }
    # Màu trạng thái: xanh lá / vàng / cam / đỏ / xám / xanh dương
    COLOR: Dict[str, str] = {
        "new": "#2563eb",
        "unsurveyed": "#0ea5e9",
        "surveyed": "#0d9488",
        "vacant": "#16a34a",
        "soon_vacant": "#eab308",
        "holding": "#f97316",
        "deposit": "#f97316",
        "rented": "#dc2626",
        "suspended": "#6b7280",
        "maintenance": "#6b7280",
    }
    BG: Dict[str, str] = {
        "new": "#dbeafe",
        "unsurveyed": "#e0f2fe",
        "surveyed": "#ccfbf1",
        "vacant": "#dcfce7",
        "soon_vacant": "#fef9c3",
        "holding": "#ffedd5",
        "deposit": "#ffedd5",
        "rented": "#fee2e2",
        "suspended": "#e5e7eb",
        "maintenance": "#e5e7eb",
    }
    # Từ khoá nhận diện tiếng Việt (không dấu) -> key
    ALIAS: List[Tuple[str, str]] = [
        ("tam ngung", "suspended"), ("ngung kinh doanh", "suspended"), ("dung cho thue", "suspended"),
        ("bao tri", "maintenance"), ("dang sua", "maintenance"),
        ("da cho thue", "rented"), ("cho thue", "rented"), ("dang thue", "rented"), ("da thue", "rented"),
        ("da nhan coc", "deposit"), ("da coc", "deposit"), ("nhan coc", "deposit"),
        ("dang giu cho", "holding"), ("giu cho", "holding"), ("dat coc", "holding"),
        ("sap trong", "soon_vacant"), ("sap tra phong", "soon_vacant"),
        ("trong o ngay", "vacant"), ("trong", "vacant"), ("con trong", "vacant"), ("trong day", "vacant"),
        ("da khaosat", "surveyed"), ("da ks", "surveyed"),
        ("chua khaosat", "unsurveyed"), ("chua ks", "unsurveyed"),
        ("moi nhap", "new"), ("phong moi", "new"), ("new", "new"),
    ]

    @classmethod
    def label(cls, key: str) -> str:
        return cls.LABEL.get(key, key or "-")

    @classmethod
    def color(cls, key: str) -> str:
        return cls.COLOR.get(key, "#6b7280")

    @classmethod
    def bg(cls, key: str) -> str:
        return cls.BG.get(key, "#e5e7eb")

    @classmethod
    def from_text(cls, text) -> str:
        """Ánh xạ chuỗi tiếng Việt (Excel) -> key trạng thái. Không đoán bừa: mặc định 'new'."""
        s = tu.norm(text)
        if not s:
            return "new"
        if s in cls.LABEL:  # đã là key
            return s
        for alias, key in cls.ALIAS:
            if alias in s:
                return key
        return "new"


# ---------------------------------------------------------------- Filters
@dataclass
class RoomFilter:
    building_id: Optional[str] = None
    district: Optional[str] = None          # khu vực (quận) - so sánh qua canon_district
    ward: Optional[str] = None              # phường - so sánh qua canon_ward
    statuses: Optional[Sequence[str]] = None
    room_types: Optional[Sequence[str]] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    ev_support: Optional[bool] = None
    foreign_guest: Optional[bool] = None
    pet_allowed: Optional[bool] = None
    surveyed: Optional[bool] = None
    needs_verify: Optional[bool] = None
    include_deleted: bool = False
    text: str = ""

    def key(self) -> Tuple:
        return (
            self.building_id, tu.canon_district(self.district), tu.canon_ward(self.ward),
            tuple(self.statuses or ()), tuple(self.room_types or ()),
            self.price_min, self.price_max, self.ev_support, self.foreign_guest, self.pet_allowed,
            self.surveyed, self.needs_verify, self.include_deleted, tu.norm(self.text),
        )


# ---------------------------------------------------------------- Dataclasses
@dataclass
class Building:
    id: str = ""
    code: str = ""
    house_number: str = ""
    street: str = ""
    ward: str = ""
    district: str = ""
    display: str = ""
    address_key: str = ""
    owner_name: str = ""
    phone: str = ""
    zalo_group: str = ""
    ev_policy: str = ""
    pet_policy: str = ""
    commission: str = ""
    notes: str = ""
    sync_state: str = "local"
    version: int = 0
    deleted: int = 0
    created_at: str = ""
    updated_at: str = ""
    updated_by: str = ""

    @classmethod
    def from_row(cls, row) -> "Building":
        d = dict(row)
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def full_address(self) -> str:
        return self.display or tu.building_display(self.house_number, self.street, self.ward, self.district)


@dataclass
class Room:
    id: str = ""
    building_id: str = ""
    room_code: str = ""
    unit_code: str = ""
    floor: str = ""
    room_type: str = ""
    status: str = "new"
    surveyed: int = 0
    price: int = 0
    deposit: int = 0
    area: str = ""          # diện tích phòng (m2)
    capacity: str = ""
    ev_support: int = 0
    pet_policy: str = ""
    pet_ok: int = 0
    rating: str = ""
    owner_phone: str = ""
    zalo_group: str = ""
    drive_link: str = ""
    notes: str = ""
    foreign_guest: int = 0   # 1 = phòng nhận khách nước ngoài
    needs_verify: int = 0
    search_norm: str = ""
    external_ref: str = ""
    sync_state: str = "local"
    version: int = 0
    deleted: int = 0
    created_at: str = ""
    updated_at: str = ""
    updated_by: str = ""
    # được join thêm từ buildings (không nằm trong DB rooms)
    address: str = ""
    building_code: str = ""
    house_number: str = ""
    street: str = ""
    ward: str = ""
    district: str = ""

    @classmethod
    def from_row(cls, row) -> "Room":
        d = dict(row)
        keys = cls.__dataclass_fields__
        return cls(**{k: d.get(k, keys[k].default) for k in keys})

    def to_dict(self) -> Dict:
        d = asdict(self)
        for k in ("address", "building_code", "house_number", "street", "ward", "district"):
            d.pop(k, None)
        return d


# ---------------------------------------------------------------- Cột dữ liệu (ánh xạ Excel <-> DB)
# name: khoá field; header: tên cột gốc theo file Excel mẫu; aliases: các biến thể tên cột khác
ROOM_COLUMNS: List[Dict] = [
    {"name": "stt",         "header": "STT",                        "aliases": ["stt", "so thu tu"], "type": "int", "editable": False},
    {"name": "status",      "header": "Trạng Thái",                 "aliases": ["trang thai", "trangthai", "status"], "type": "status", "editable": True},
    {"name": "surveyed",    "header": "Khảo Sát",                   "aliases": ["khaosat", "khao sat", "survey"], "type": "survey", "editable": True},
    {"name": "house_number","header": "Số Nhà",                     "aliases": ["so nha", "sonha", "house number", "address1"], "type": "text", "editable": True},
    {"name": "street",      "header": "Tên Đường",                  "aliases": ["ten duong", "tenduong", "street", "duong"], "type": "text", "editable": True},
    {"name": "ward",        "header": "Phường",                     "aliases": ["phuong", "ward"], "type": "text", "editable": True},
    {"name": "district",    "header": "Quận / Khu Vực Cũ",          "aliases": ["quan", "khu vuc", "khu vuc cu", "quan khu vuc cu", "district", "q"], "type": "text", "editable": True},
    {"name": "room_code",   "header": "Mã Phòng",                   "aliases": ["ma phong", "maphong", "room code", "ma can"], "type": "text", "editable": True},
    {"name": "room_type",   "header": "Dạng Phòng",                 "aliases": ["dang phong", "dangphong", "loai phong", "room type"], "type": "text", "editable": True},
    {"name": "price",       "header": "Giá Thuê (VNĐ)",             "aliases": ["gia thue", "giathue", "gia", "price", "gia thue vnd"], "type": "money", "editable": True},
    {"name": "deposit",     "header": "Cọc (VNĐ)",                  "aliases": ["coc", "tien coc", "tiencoc", "deposit"], "type": "money", "editable": True},
    {"name": "area",        "header": "Diện Tích (m2)",             "aliases": ["dien tich", "dientich", "area", "m2"], "type": "text", "editable": True},
    {"name": "capacity",    "header": "Tối Đa (Người/Xe)",          "aliases": ["suc chua", "toi da", "suc chua nguoi xe", "capacity"], "type": "text", "editable": True},
    {"name": "ev_support",  "header": "Xe Điện ⚡",                  "aliases": ["xe dien", "xedien", "ev", "ho tro xe dien"], "type": "bool", "editable": True},
    {"name": "pet_policy",  "header": "Nuôi Pet 🐾",                "aliases": ["nuoi pet", "thu cung", "pet", "chinh sach pet"], "type": "pet", "editable": True},
    {"name": "rating",      "header": "Đánh Giá / Độ Đẹp ⭐",        "aliases": ["danh gia", "do dep", "rating", "danh gia do dep"], "type": "text", "editable": True},
    {"name": "owner_phone", "header": "SĐT Chủ / Admin",            "aliases": ["sdt chu admin", "sdt", "so dien thoai", "sdt chu nha", "phone"], "type": "text", "editable": True},
    {"name": "zalo_group",  "header": "Group Zalo Tòa Nhà",         "aliases": ["group zalo", "zalo", "zalo toa nha"], "type": "text", "editable": True},
    {"name": "drive_link",  "header": "Link Drive Kho Media",       "aliases": ["link drive", "drive", "link google drive", "media"], "type": "text", "editable": True},
    {"name": "notes",       "header": "Chính Sách & Ghi Chú Chi Tiết", "aliases": ["chinh sach", "ghi chu", "notes", "chinh sach ghi chu", "ghi chu chi tiet"], "type": "text", "editable": True},
    {"name": "foreign_guest","header": "Nhận Khách Nước Ngoài",        "aliases": ["nuoc ngoai", "khach nuoc ngoai", "foreign", "foreign guest", "nhan nuoc ngoai"], "type": "bool", "editable": True},
    {"name": "unit_code",   "header": "Số Căn",                     "aliases": ["so can", "socc", "so can ho", "unit", "ma can"], "type": "text", "editable": True},
    {"name": "floor",       "header": "Tầng",                       "aliases": ["tang", "floor", "lau"], "type": "text", "editable": True},
]

# Cột bảng phòng hiển thị trên giao diện (order + tiêu đề)
# Địa chỉ TÁCH RIÊNG 4 cột giống file Excel: Số Nhà | Tên Đường | Phường | Quận/Khu Vực
ROOM_TABLE_COLUMNS: List[Tuple[str, str, int]] = [
    ("room_code",    "Mã phòng",       105),
    ("status",       "Trạng thái",      125),
    ("house_number", "Số nhà",           70),
    ("street",       "Tên đường",       150),   # cột co giãn (stretch)
    ("ward",         "Phường",           70),
    ("district",     "Quận / Khu vực",  105),
    ("unit_code",    "Số căn",           85),
    ("floor",        "Tầng",             55),
    ("room_type",    "Dạng phòng",      105),
    ("price",        "Giá thuê",        105),
    ("deposit",      "Tiền cọc",        100),
    ("area",         "Diện tích",        80),
    ("surveyed",     "Khảo sát",         85),
    ("ev_support",   "Xe điện",          75),
    ("foreign_guest","Khách NGO",        75),
    ("capacity",     "Người/Xe",         90),
    ("owner_phone",  "SĐT chủ nhà",     155),
    ("updated_at",   "Cập nhật",        140),
]

BUILDING_COLUMNS: List[Dict] = [
    {"name": "house_number", "header": "Số Nhà",                "aliases": ["so nha", "sonha"]},
    {"name": "street",       "header": "Tên Đường",             "aliases": ["ten duong", "tenduong", "duong"]},
    {"name": "ward",         "header": "Phường",                "aliases": ["phuong", "ward"]},
    {"name": "district",     "header": "Quận / Khu Vực Cũ",     "aliases": ["quan", "khu vuc", "quan khu vuc cu"]},
    {"name": "owner_name",   "header": "Chủ Tòa / Admin QLH",   "aliases": ["chu toa", "admin", "chu nha", "admin qlh"]},
    {"name": "phone",        "header": "Số Điện Thoại",         "aliases": ["so dien thoai", "sdt", "phone"]},
    {"name": "zalo_group",   "header": "Link Group Zalo",       "aliases": ["group zalo", "zalo"]},
    {"name": "ev_policy",    "header": "Quy Định Xe Điện",      "aliases": ["quy dinh xe dien", "xe dien"]},
    {"name": "pet_policy",   "header": "Quy Định Pet",          "aliases": ["quy dinh pet", "thu cung", "pet"]},
    {"name": "commission",   "header": "Chính Sách Hoa Hồng Sale", "aliases": ["hoa hong", "chinh sach hoa hong", "commission"]},
]

# Danh mục gợi ý
ROOM_TYPES = ["Studio", "1 Phòng Ngủ", "2 Phòng Ngủ", "3 Phòng Ngủ", "Duplex", "Penthouse", "Căn hộ dịch vụ"]
