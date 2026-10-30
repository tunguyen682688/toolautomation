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
