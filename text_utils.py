# -*- coding: utf-8 -*-
"""text_utils.py - Chuẩn hoá văn bản tiếng Việt cho tìm kiếm, khoá nhận diện và chống trùng.

Toàn bộ khoá duy nhất (address_key / unit_key / room_code_key) đều đi qua module này
để đảm bảo: "P. 13" == "phường 13", "79/16" == "79-16", "Nguyễn Thượng Hiền" == "nguyen thuong hien".
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_DIGITS_RE = re.compile(r"\d+")

# Chỉ giữ lại chữ cái/thường + số, bỏ dấu phân cách
_KEEP_RE = re.compile(r"[^0-9a-zA-Z]+")


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt (đ/Đ -> d/D)."""
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def collapse_space(text: str) -> str:
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", str(text)).strip()


def norm(text: str) -> str:
    """Chuẩn hoá tìm kiếm: bỏ dấu, hạ chữ thường, gộp khoảng trắng."""
    if text is None:
        return ""
    return collapse_space(strip_accents(str(text)).lower())


def norm_key(text: str) -> str:
    """Khoá so khớp cứng: chỉ chữ thường + số, không dấu, không phân cách."""
    if text is None:
        return ""
    return _NON_ALNUM_RE.sub("", norm(text))


def unit_key(value) -> str:
    """Khoá số căn: '79/16' -> '7916', '3 /335' -> '3335', '371A' -> '371a'."""
    if value is None:
        return ""
    return norm_key(value)


def room_code_key(value) -> str:
    """Khoá mã phòng: 'P-86' -> 'p86'."""
    return norm_key(value)


def valid_room_code(value) -> bool:
    """Mã phòng hợp lệ: có ít nhất 1 chữ số và chỉ chứa ký tự mã hoá được.

    Câu lệch dữ liệu thực tế: 'được' (không có chữ số) -> không hợp lệ, đánh dấu cần xác minh.
    """
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False
    if not any(ch.isdigit() for ch in s):
        return False
    return bool(re.fullmatch(r"[0-9A-Za-z _\-./]+", s))


def digits_only(text: str) -> str:
    if text is None:
        return ""
    return "".join(_DIGITS_RE.findall(str(text)))


def phone_key(text: str) -> str:
    """Chuẩn hoá số điện thoại để so trùng: bỏ dấu gạch, khoảng trắng, đầu 84."""
    d = digits_only(text)
    if len(d) > 10 and d.startswith("84"):
        d = d[2:]
    return d


def canon_ward(text: str) -> str:
    """"P. 13"/"Phường 13"/"13" -> "13" (mã phường)."""
    s = norm(text)
    if not s:
        return ""
    s = re.sub(r"^(phuong|p)\.?\s*", "", s)
    return collapse_space(s)


def canon_district(text: str) -> str:
    """"Q. Bình Thạnh cũ" -> "binh thanh"; "Quận 3" -> "3"."""
    s = norm(text)
    if not s:
        return ""
    s = re.sub(r"^(quan|q)\.?\s*", "", s)
    s = re.sub(r"\bcu\b", "", s)  # bỏ chữ "cũ" trong "Q. Bình Thạnh cũ"
    return collapse_space(s)


def address_key(house_number, street, ward=None, district=None) -> str:
    """Khoá địa chỉ tòa nhà - dùng làm khóa chống trùng địa chỉ."""
    parts = [
        collapse_space(strip_accents(str(house_number or ""))).lower(),
        collapse_space(strip_accents(str(street or ""))).lower(),
        canon_ward(ward),
        canon_district(district),
    ]
    return _WHITESPACE_RE.sub(" ", " ".join(p for p in parts if p)).strip()


def building_display(house_number, street, ward=None, district=None) -> str:
    """Địa chỉ hiển thị: '86 Nguyễn Thượng Hiền, P. 13, Q. Bình Thạnh'."""
    head = collapse_space(f"{house_number or ''} {street or ''}").strip(", ")
    tail = ", ".join(collapse_space(x) for x in (ward, district) if collapse_space(x))
    return f"{head}, {tail}" if tail else head


def tokens(text: str) -> List[str]:
    """Cắt từ cho chỉ mục tìm kiếm (đã bỏ dấu, bỏ ký tự đặc biệt)."""
    if not text:
        return []
    s = norm(text)
    s = re.sub(r"[^0-9a-z\s]", " ", s)
    return [t for t in s.split() if t]


def normalize_price(value) -> int:
    """Đưa mọi dạng giá về số nguyên VNĐ.

    Hỗ trợ: 7000000 | 7.000.000 | 7,000,000 | 7.5 | 7tr | 7 triệu | '7.500.000đ'
    """
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    s = norm(str(value))
    if not s:
        return 0
    s = s.replace("vnd", "").replace("dong", "").replace("d", "").strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(trieu|tr|nghin|n|k)\b", s)
    if m:
        num = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        if unit in ("trieu", "tr"):
            return int(round(num * 1_000_000))
        if unit in ("nghin", "n", "k"):
            return int(round(num * 1_000))
        return int(round(num))
    # 7.000.000 / 7,000,000 / 7000000
    cleaned = s.replace(".", "").replace(",", "")
    digits = re.sub(r"[^0-9]", "", cleaned)
    return int(digits) if digits else 0


def format_money(value) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def parse_yes_no(value) -> Optional[bool]:
    """"Có sạc"/"Không"/"Có"/None -> True/False/None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = norm(value)
    if not s:
        return None
    if s.startswith("khong") or s in ("no", "0", "false", "khong co"):
        return False
    if s.startswith("co") or s in ("yes", "1", "true"):
        return True
    return None


def parse_pet_policy(value) -> str:
    """Chuẩn hoá chính sách thú cưng về: 'Cho nuôi' / 'Không nuôi' / ''."""
    s = norm(value)
    if not s:
        return ""
    if s.startswith("khong") or "ko nuôi" in s:
        return "Không nuôi"
    if "cho nuôi" in s or "nhan pet" in s or "nuoi duoc" in s or s.startswith("co"):
        return "Cho nuôi"
    return str(value).strip()


def parse_survey(value) -> bool:
    s = norm(value)
    if not s:
        return False
    return s.startswith("da")  # "đã ks", "đã khảo sát"


def similarity(a: str, b: str) -> float:
    """Độ tương đồng 0..1 trên chuỗi đã chuẩn hoá (SequenceMatcher)."""
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def similar_address(a: str, b: str) -> float:
    """So khớp 2 địa chỉ: ưu tiên khoá cứng, sau đó tương đồng."""
    ka, kb = norm_key(a), norm_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ratio = SequenceMatcher(None, ka, kb).ratio()
    # Một địa chỉ là chuỗi con của địa chỉ kia (vd: "26/14" vs "26/14/6-8") -> cẩn thận
    if ka in kb or kb in ka:
        ratio = max(ratio, 0.72)
    return ratio


def strip_emoji(text: str) -> str:
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ord(ch) < 0x2500 or ch in "⭐⚡🐾📸")


def normalize_header(header) -> str:
    """Chuẩn hoá tên cột Excel để ánh xạ tự động: bỏ emoji, bỏ dấu, gộp khoảng trắng."""
    if header is None:
        return ""
    s = strip_emoji(str(header))
    s = re.sub(r"[\(\)\[\]]", " ", s)
    return norm(s)


def unique_seq(items: Iterable) -> list:
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ==================================================================== PHÂN TÍCH TIN ĐĂNG (dán text)
# Mục đích: dán nguyên văn tin cho thuê (Zalo/Facebook) -> tự tách các trường
# địa chỉ / giá / cọc / dạng phòng / sức chứa / diện tích / tầng / pet / xe điện / SĐT.

_KNOWN_DISTRICTS = [
    # (chuỗi tìm trong text đã norm -> tên hiển thị)
    ("binh thanh", "Q. Bình Thạnh"),
    ("go vap", "Q. Gò Vấp"),
    ("phu nhuan", "Q. Phú Nhuận"),
    ("tan binh", "Q. Tân Bình"),
    ("tan phu", "Q. Tân Phú"),
    ("thu duc", "TP. Thủ Đức"),
    ("binh tan", "Q. Bình Tân"),
    ("nha be", "H. Nhà Bè"),
    ("hoc mon", "H. Hóc Môn"),
    ("cu chi", "H. Củ Chi"),
    ("binh chanh", "H. Bình Chánh"),
    ("can gio", "H. Cần Giờ"),
]
_KNOWN_DISTRICT_ABBR = {"bt": "Q. Bình Thạnh", "gv": "Q. Gò Vấp", "pn": "Q. Phú Nhuận"}

_ROOM_TYPE_PATTERNS = [
    ("can ho dich vu", "Căn hộ dịch vụ"),
    ("penthouse", "Penthouse"),
    ("duplex", "Duplex"),
    ("studio", "Studio"),
    ("3 phong ngu", "3 Phòng Ngủ"), ("3pn", "3 Phòng Ngủ"), ("3 pn", "3 Phòng Ngủ"),
    ("2 phong ngu", "2 Phòng Ngủ"), ("2pn", "2 Phòng Ngủ"), ("2 pn", "2 Phòng Ngủ"),
    ("1 phong ngu", "1 Phòng Ngủ"), ("1pn", "1 Phòng Ngủ"), ("1 pn", "1 Phòng Ngủ"),
    ("phong tro", "Phòng trọ"), ("nguyen can", "Nguyên căn"),
]

_PHONE_RE = re.compile(r"(?:0|\+84)[\d\s.\-]{8,13}\d")
_HOUSE_NUM_RE = re.compile(r"^(\d+[A-Za-z]?(?:\s*/\s*\d+[A-Za-z0-9]?)*)\s+([A-Za-zÀ-ỹ].+)$")
_WARD_RE = re.compile(r"(?:\bp\.?\s*(\d{1,2})\b|\bphuong\s+(\d{1,2})\b)")
_DIST_Q_RE = re.compile(r"\bq\.?\s*(\d{1,2})\b")
_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|met vuong)")
_FLOOR_RE = re.compile(r"(?:\btang|\blau)\s*(\d{1,2})\b")
_CAPACITY_RE = re.compile(r"(\d{1,2})\s*(?:nguoi|ng)\D{0,8}?(\d{1,2})\s*(?:xe|x)\b")
_MONEY_UNIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:trieu|tr)\b")
_MONEY_PLAIN_RE = re.compile(r"\b(\d{6,9})\b")

# từ KHÔNG phải tên đường (tránh nhầm "2 người 2xe giá 7tr" thành địa chỉ)
_NON_STREET_HEADS = {
    "nguoi", "ng", "xe", "x", "gia", "thue", "cho", "coc", "pet", "m2",
    "tang", "lau", "t", "sdt", "dt", "lien he", "full", "view", "wc",
}


def _money_near(n: str, anchors: tuple, after_len: int = 40) -> int:
    """Tìm số tiền NGAY SAU từ khóa (vd 'gia', 'coc') trong text đã norm."""
    for anchor in anchors:
        m = re.search(rf"\b{anchor}\b", n)
        if not m:
            continue
        seg = n[m.end(): m.end() + after_len]
        mm = _MONEY_UNIT_RE.search(seg)
        if mm:
            return normalize_price(mm.group(0))
        mm = _MONEY_PLAIN_RE.search(seg)
        if mm:
            return int(mm.group(1))
    return 0


def parse_listing_text(text: str) -> dict:
    """Phân tích tin đăng thuê nhà dạng text tự do -> dict các trường của form.

    Trả về dict có các khóa (None nếu không tách được -> "Chưa biết"):
    house_number, street, ward, district, price, deposit, room_type, area,
    floor, capacity, ev_support, pet_policy, owner_phone, notes
    """
    out = {k: "" for k in ("house_number", "street", "ward", "district", "room_type",
                           "area", "floor", "capacity", "pet_policy", "owner_phone", "notes")}
    # không tách được -> None (Chưa biết), KHÔNG được gán 0 (sẽ thành "Không")
    out.update({"price": None, "deposit": None, "ev_support": None})
    if not text or not str(text).strip():
        return out

    raw = collapse_space(strip_emoji(str(text)))
    n = norm(raw)
    # bỏ số điện thoại khỏi n để không nhầm với giá
    phone_m = _PHONE_RE.search(raw)
    if phone_m:
        out["owner_phone"] = phone_key(phone_m.group())
        n = re.sub(r"(?:0|\+84)[\d\s.\-]{8,13}\d", " ", n)

    # ---- giá thuê: ưu tiên sau từ 'gia'/'thue'; nếu không có -> đơn vị 'tr' đầu tiên
    price = _money_near(n, ("gia", "gia thue", "thue", "price"))
    if not price:
        mm = _MONEY_UNIT_RE.search(n)
        if mm:
            price = normalize_price(mm.group(0))
        else:
            mm = _MONEY_PLAIN_RE.search(n)
            if mm:
                price = int(mm.group(1))
    out["price"] = price or None      # không tách được -> None (Chưa biết), không phải 0

    # ---- tiền cọc: sau từ 'coc' / 'dat coc'
    out["deposit"] = _money_near(n, ("coc", "dat coc")) or None

    # ---- dạng phòng
    for pat, label in _ROOM_TYPE_PATTERNS:
        if re.search(rf"\b{pat}\b", n):
            out["room_type"] = label
            break

    # ---- sức chứa: "2 người 2 xe" / "2n2x"
    cm = _CAPACITY_RE.search(n)
    if cm:
        out["capacity"] = f"{cm.group(1)} Ng/{cm.group(2)} Xe"

    # ---- diện tích / tầng
    am = _AREA_RE.search(n)
    if am:
        out["area"] = am.group(1).replace(",", ".")
    fm = _FLOOR_RE.search(n)
    if fm:
        out["floor"] = fm.group(1)

    # ---- xe điện / thú cưng
    if re.search(r"\bxe dien\b|\bsac xe\b|\bco sac\b", n):
        out["ev_support"] = 1
    if re.search(r"\bkhong (pet|nuoi)\b|\bcam pet\b", n):
        out["pet_policy"] = "Không nuôi"
    elif re.search(r"\b(pet|meo|cho nuoi|nuoi)\b", n):
        out["pet_policy"] = "Cho nuôi (chó/mèo)"

    # ---- phường / quận (trên text toàn bộ, dùng cho dòng địa chỉ)
    ward_m = _WARD_RE.search(n)
    district_disp = ""
    if ward_m:
        out["ward"] = f"P. {ward_m.group(1) or ward_m.group(2)}"
    for pat, name in _KNOWN_DISTRICTS:
        if re.search(rf"\b{pat}\b", n):
            district_disp = name
            break
    if not district_disp:
        for abbr, name in _KNOWN_DISTRICT_ABBR.items():
            if re.search(rf"\b{abbr}\b", n):
                district_disp = name
                break
    if not district_disp:
        qm = _DIST_Q_RE.search(n)
        if qm:
            district_disp = f"Q. {qm.group(1)}"
    if district_disp:
        out["district"] = district_disp

    # ---- dòng địa chỉ: số nhà + tên đường
    house, street = "", ""
    candidates = []
    for line in raw.splitlines():
        m = _HOUSE_NUM_RE.match(line)
        if m:
            candidates.append((m.group(1), m.group(2)))
    if not candidates:
        # cả text là 1 dòng: tìm pattern số nhà + chữ (lấy đến hết dòng, cắt sau)
        m = re.search(r"(\d+[A-Za-z]?(?:/\d+[A-Za-z0-9]?)*)\s+([A-Za-zÀ-ỹ].+)", raw)
        if m:
            candidates.append((m.group(1), m.group(2)))

    _WARD_RAW_RE = re.compile(r"[Pp]\.?\s*\d{1,2}\b|[Pp]h[àa]ng\s+\d{1,2}\b")
    _STOP_RAW_RE = re.compile(r"\b[Gg]i[áa]\b|\b[Tt]hu[êe]\b|\b[Ss][ĐD][Tt]\b|li[êe]n h[ệe]|\b[Cc]h[íi]nh ch[ủu]\b")
    _QNUM_RE = re.compile(r"^[Qq]\.?\d{1,2}$")

    for hnum, rest in candidates:
        rest = re.sub(r"(?:0|\+84)[\d\s.\-]{8,13}\d", " ", rest)
        rest = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:tr|trieu|triệu|nghin|nghìn|k)\b", " ", rest)
        rest = re.sub(r"\b\d{6,9}\b", " ", rest)

        # cắt street tại vị trí XUẤT HIỆN ĐẦU TIÊN của: phường / quận / từ khóa kết thúc
        cut = len(rest)
        wm2 = _WARD_RAW_RE.search(rest)
        if wm2:
            cut = min(cut, wm2.start())
        sm = _STOP_RAW_RE.search(rest)
        if sm:
            cut = min(cut, sm.start())
        tokens = rest.split()
        # vị trí ký tự bắt đầu của từng token trong rest
        pos = 0
        starts = []
        for tok in tokens:
            idx = rest.find(tok, pos)
            starts.append(idx if idx >= 0 else pos)
            pos = (idx if idx >= 0 else pos) + len(tok)
        for i, tok in enumerate(tokens):
            one = norm(tok)
            two = norm(" ".join(tokens[i:i + 2]))
            hit = any(one == pat or two == pat or two.startswith(pat + " ")
                      for pat, _n in _KNOWN_DISTRICTS)
            if one in _KNOWN_DISTRICT_ABBR or _QNUM_RE.match(tok):
                hit = True
            if hit and 0 <= starts[i] < cut:
                cut = min(cut, starts[i])

        street_cand = collapse_space(rest[:cut].strip(" ,.;:-"))
        # KHÔNG strip tiền tố "đường" - "Đường Số 30", "Đường Mới" là tên đường hợp lệ
        street_cand = re.sub(r"^(cho thue|cho thuê|can ho|căn hộ|phong|phòng|nha|nhà)\s+",
                             "", street_cand, flags=re.IGNORECASE)
        words = norm(street_cand).split()
        if not street_cand or not words or len(words) < 2:
            continue
        if words[0] in _NON_STREET_HEADS:
            continue
        house, street = hnum, street_cand
        break

    if house:
        out["house_number"], out["street"] = house, street
    # nếu chưa có phường/quận và dòng địa chỉ còn sót -> thử tách từ street
    if house:
        out["house_number"], out["street"] = house, street
    if not out["ward"] and street:
        wm = _WARD_RE.search(norm(street))
        if wm:
            out["ward"] = f"P. {wm.group(1) or wm.group(2)}"
    if not out["district"] and street:
        np_ = norm(street)
        for pat, name in _KNOWN_DISTRICTS:
            if re.search(rf"\b{pat}\b", np_):
                out["district"] = name
                break

    # ---- ghi chú: phần text còn lại (nguyên văn, không phân tích được)
    out["notes"] = collapse_space(strip_emoji(str(text)))[:500]
    return out
