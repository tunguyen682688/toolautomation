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


def address_sort_key(row) -> tuple:
    """Khối sort ĐỊA CHỈ cho danh sách phòng: TÊN ĐƯỜNG -> SỐ NHÀ -> mã -> id.

    - đường: bỏ dấu + chữ thường ('xô viết nghệ tĩnh' ...)
    - số nhà: đếm số TỰ NHIÊN ('2' < '10', '31/32/52' sort theo từng đoạn)
      (ép string thuần sẽ ra '10' < '2' -> sai thứ tự)
    """
    street = norm_key(str(row.get("street") or ""))
    hnum = re.sub(r"\d+", lambda m: m.group().zfill(9),
                  str(row.get("house_number") or "").lower())
    unit = norm_key(str(row.get("unit_code") or row.get("room_code") or ""))
    return (street, hnum, unit, str(row.get("id") or ""))


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
             4tr5 (=4,5 triệu) | 5tr5 | 11.6Tr | '5.200 K' (=5,2 triệu) | 4K | 3,8k
    """
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    s = norm(str(value))
    if not s:
        return 0
    s = s.replace("vnd", "").replace("dong", "").replace("d", "").strip()

    def _num(num_s: str) -> float:
        """'5.200' (nhóm nghìn) -> 5200 | '3,8' (thập phân) -> 3.8 | '7.5' -> 7.5"""
        num_s = num_s.replace(",", ".")
        grouped = bool(re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num_s))
        if grouped:
            return float(num_s.replace(".", ""))
        return float(num_s)

    # (a) 4tr5 / 5tr5 -> 4,5 triệu / 5,5 triệu (chữ số DÍNH sau "tr" = thập phân)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:trieu|tr)(\d)", s)
    if m:
        num = float(m.group(1).replace(",", "."))
        if num == int(num):          # 4tr5 -> 4 + 5/10 = 4.5
            num += int(m.group(2)) / 10
        return int(round(num * 1_000_000))
    # (b) 7tr / 11.6Tr / 5.200 K / 4K / 3,8k
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(trieu|tr|nghin|n|k)\b", s)
    if m:
        num = _num(m.group(1))
        unit = m.group(2)
        if unit in ("trieu", "tr"):
            return int(round(num * 1_000_000))
        if unit in ("nghin", "n", "k"):
            # '5.200 K' = 5200 nghìn = 5.200.000 (nhóm nghìn x1000)
            return int(round(num * 1_000))
        return int(round(num))
    # (c) 7.000.000 / 7,000,000 / 7000000
    cleaned = s.replace(".", "").replace(",", "")
    digits = re.sub(r"[^0-9]", "", cleaned)
    return int(digits) if digits else 0


def format_money(value) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def money_words(value) -> str:
    """Đọc số tiền bằng chữ để khỏi phải đếm số 0.

    5000000 -> "5 triệu" | 7500000 -> "7,5 triệu" | 850000 -> "850 nghìn"
    0 / None / không hợp lệ -> "" (chưa biết -> không hiển thị gì)
    """
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if v >= 1_000_000:
        n = v / 1_000_000
        s = f"{n:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{s} triệu"
    if v >= 1_000:
        n = v / 1_000
        s = f"{n:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{s} nghìn"
    return f"{v} đồng"


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
    s = norm(value)                      # s đã BỎ DẤU -> so sánh không dấu
    if not s:
        return ""
    if s.startswith("khong") or "ko nuoi" in s:
        return "Không nuôi"
    if "cho nuoi" in s or "nhan pet" in s or "nuoi duoc" in s or s.startswith("co"):
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
    ("thanh my tay", "Q. Bình Thạnh"),   # khu cũ ở Bình Thạnh - hay gặp trong tin Zalo
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
# 8.700.000 / 6.400.000 (nhóm nghìn, có thể kèm đơn vị 'K' -> '5.200 K')
_MONEY_DOTS_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})+(?:[.,]\d+)?\s*(?:trieu|tr|nghin|k)?", re.IGNORECASE)
# đơn vị dính liền + chữ số thập phân: 4tr5 / 5tr5
_MONEY_TRDIG_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:trieu|tr)\d", re.IGNORECASE)

# từ KHÔNG phải tên đường (tránh nhầm "2 người 2xe giá 7tr" thành địa chỉ)
_NON_STREET_HEADS = {
    "nguoi", "ng", "xe", "x", "gia", "thue", "cho", "coc", "pet", "m2",
    "tang", "lau", "t", "sdt", "dt", "lien he", "full", "view", "wc",
}


def _money_near(n: str, anchors: tuple, after_len: int = 40,
                skip_before: tuple = ()) -> int:
    """Tìm số tiền NGAY SAU từ khóa (vd 'gia', 'coc') trong text đã norm.

    Nhận mọi dạng: 7tr | 4tr5 | 8.700.000 | 5.200 K | 7000000.
    skip_before: từ khoá NGAY TRƯỚC số tiền -> bỏ qua (vd tìm 'gia' nhưng gặp
    'cọc 3tr' -> không lấy nhầm tiền cọc làm giá).
    """
    for anchor in anchors:
        m = re.search(rf"\b{anchor}\b", n)
        if not m:
            continue
        seg = n[m.end(): m.end() + after_len]
        for pat in (_MONEY_TRDIG_RE, _MONEY_UNIT_RE, _MONEY_DOTS_RE, _MONEY_PLAIN_RE):
            mm = pat.search(seg)
            if not mm:
                continue
            token = mm.group(0)
            pre = n[max(0, m.end() + mm.start() - 14): m.end() + mm.start()]
            if skip_before and any(w in pre for w in skip_before):
                continue
            v = normalize_price(token)
            if v:
                return v
    return 0


def _window(text: str, pos: int, before: int = 30, after: int = 150) -> str:
    """Cắt cửa sổ quanh vị trí ``pos`` trên ``text`` - không cắt giữa từ, tối đa ~200 ký tự."""
    if not text:
        return ""
    pos = max(0, min(int(pos or 0), len(text) - 1))
    start = max(0, pos - before)
    # đang cắt giữa từ -> nhảy tới đầu từ kế; nếu đã đứng ĐÚNG đầu từ thì GIỮ NGUYÊN
    if start > 0 and text[start - 1].isalnum():
        sp = text.find(" ", start)
        if sp != -1:
            start = sp + 1
    end = min(len(text), pos + after)
    sp = text.find(" ", end)
    if sp != -1:
        end = sp
    return collapse_space(text[start:end])[:200]


_FEE_KW_RE = re.compile(r"\b(?:dien|nuoc|wifi|internet|phi dich vu|phi dv|phi quan ly|"
                        r"phi dich|phi giu xe|phi gui xe|giu xe|gui xe|cham soc|giat do|"
                        r"dich vu|dv)\b|\bxe\s*:")
_FEE_MONEY_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:trieu|tr|nghin|k)\b"          # 4k / 100k / 7tr
    r"|\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?(?!\d)"        # 4.000 / 3.500đ / 8.700.000
    r"|\b\d{4,}(?!\d)"                                    # 4000 / 15000 / 4000đ
    r"|\b(?:free|mien phi)\b", re.IGNORECASE)             # free / miễn phí


def _is_fee_text(t: str) -> bool:
    """Đoạn/cụm có từ khoá phí TIỀN + có số tiền (hoặc 'free') -> là dòng chi phí."""
    ns = norm(t)
    return bool(ns and _FEE_KW_RE.search(ns) and _FEE_MONEY_RE.search(ns))


def _parse_fee_hours_amenities(lines: list, n: str) -> dict:
    """Tách chi phí dịch vụ / giờ giấc / tiện ích tòa nhà theo TỪNG DÒNG tin.

    - service_fee: mỗi DÒNG (hoặc cụm sau dấu ',' nếu ≥2 cụm hợp lệ) có
      từ khoá phí + số tiền -> gom lại, nối ' · ' (giữ nguyên văn tiếng Việt).
    - access_hours: ưu tiên dòng có 'giờ giấc/ra vào tự do/giới nghiêm'
      (vòng quanh từ khoá đến hết dòng), sau đó mới 'mở cửa / 24/7 / 24/24'.
    - amenities: gom từ khoá tiện ích trên toàn tin (text đã norm).
    """
    out = {"service_fee": "", "access_hours": "", "amenities": ""}

    # ---- chi phí dịch vụ: quét TỪNG DÒNG (không dùng text gộp -> không lẫn rác)
    fee_items: List[str] = []
    for line in lines:
        clean = collapse_space(str(line).strip(" \t-+•●·*>#=["))   # bỏ bullet/markdown
        if not clean:
            continue
        # tách cụm theo ', ' '; ' '. ' -> '3.500đ/kWh' KHÔNG bị tách (không có '. ')
        clauses = [c.strip() for c in re.split(r"[,;]\s*|\.\s+", clean) if c.strip()]
        hit = [c for c in clauses if _is_fee_text(c)]
        if len(hit) >= 2:
            fee_items.extend(hit)          # 1 dòng nhiều phí -> tách cụm cho gọn
        elif _is_fee_text(clean):
            # tin gộp THÀNH MỘT DÒNG (không xuống dòng/dấu phẩy) -> cắt từ TỪ KHOÁ PHÍ
            # đầu tiên: 'Đầu tháng... Giá 12tr Điện 4k Nước...' -> chỉ lấy từ 'Điện 4k'
            if len(clean) > 100:
                mk = _FEE_KW_RE.search(strip_accents(clean).lower())
                if mk and mk.start() > 0:
                    clean = clean[mk.start():]
            fee_items.append(clean)        # giữ nguyên cả dòng (vd chứa '(rác, wifi...)')
        if len(fee_items) >= 12:
            break
    out["service_fee"] = unique_seq(fee_items) and " · ".join(unique_seq(fee_items))[:400] or ""

    # ---- giờ giấc: pass 1 = từ khoá MẠNH, pass 2 = từ khoá YẾU (tránh
    #     'Camera 24/24' lọt vào trước 'Giờ giấc tự do')
    strong = ("gio giac", "gio ra vao", "gioi nghiem", "gio mo cua", "gio cham cong",
              "gio canh", "ra vao tu do")
    weak = ("mo cua", "24/7", "24/24")
    hour_range = re.compile(r"\b\d{1,2}\s*h(?:\s*[:.]?\s*\d{2})?\s*(?:-|–|—|đến|tới|den|toi)\s*\d{1,2}\s*h")
    for pats in (strong, weak):
        for line in lines:
            low = str(line).lower()
            low_na = strip_accents(low)          # BỎ DẤU nhưng GIỮ NGUYÊN độ dài -> map vị trí về low
            pos, kw = -1, ""
            for pat in pats:
                if pat in low_na:
                    kw, pos = pat, low_na.find(pat)
                    break
            if pos < 0:
                m = hour_range.search(low_na)
                if m and pats is weak:
                    kw, pos = "range", m.start()
            if pos >= 0:
                win = _window(low, pos, before=0, after=80) or kw
                # cắt tại câu kế ('. ') -> không kéo theo rác phía sau
                dot = win.find(". ")
                if dot > 8:
                    win = win[:dot]
                out["access_hours"] = win
                break
        if out["access_hours"]:
            break

    # ---- tiện ích tòa nhà: gom từ khoá trên toàn tin (n = text đã norm)
    amen = (("thang may", "Thang máy"), ("camera", "Camera"), ("dieu hoa", "Điều hòa"),
            ("be boi", "Hồ bơi"), ("truyen hinh", "Truyền hình"),
            ("wifi", "Wifi"), ("internet", "Internet"), ("giu xe", "Giữ xe"),
            ("bao ve", "Bảo vệ"), ("an ninh", "An ninh"), ("san vuon", "Sân vườn"),
            ("ham do xe", "Hầm để xe"), ("sieu thi", "Siêu thị"), ("choi game", "Chơi game"),
            ("khoa cong van tay", "Khóa vân tay"), ("khoa van tay", "Khóa vân tay"),
            ("van tay", "Vân tay"), ("pccc", "PCCC"),
            ("giac xay", "Giặt sấy"), ("giat xay", "Giặt sấy"), ("giat phoi", "Giặt phơi"),
            ("may giat chung", "Máy giặt chung"))
    found = [disp for kw, disp in amen if kw in n]
    if "Khóa vân tay" in found and "Vân tay" in found:
        found.remove("Vân tay")           # không liệt kê 2 lần cùng 1 tính năng
    out["amenities"] = ", ".join(found)
    return out


_ADDR_ANCHOR_RE = re.compile(r"\bdia chi\b|\bdu an\b|\btoa nha\b|\bnha tai\b|\bdia diem\b")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?!\s*/\d)")
_WARD_RAW_RE = re.compile(r"\bp\.?\s*\d{1,2}\b|\bph[uư]\S*ng\s+\d{1,2}\b", re.IGNORECASE)
_WARD_WORD_RE = re.compile(r"^\s*(?:ph[uư]\S*ng\b|\bp\b\.?\s*[a-zà-ỹ])", re.IGNORECASE)
_WARD_NAME_RE = re.compile(r"\bph[uư]\S*ng\s+([A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]{0,30})", re.IGNORECASE)
_ROOM_TOK_RE = re.compile(r"^[A-Za-z]\d{1,4}$")
# từ kết thúc tên đường: giá / thuê / SĐT / liên hệ / chính chủ
_STOP_RAW_RE = re.compile(r"\b[Gg]i[áa]\b|\b[Gg]ia\b|\b[Tt]hu[êe]\b|\b[Ss][ĐD][Tt]\b"
                          r"|li[êe]n h[ệe]|\b[Cc]h[íi]nh ch[ủu]\b|\bdt\b|\bmobile\b")
# tên đường viết tắt hay gặp -> tên đầy đủ (khớp địa chỉ với tin khác không cách viết)
_STREET_ABBR = {"xvnt": "Xô Viết Nghệ Tĩnh", "nxc": "Nguyễn Xí", "hvt": "Hoàng Văn Thụ"}


def _extract_address(lines) -> tuple:
    """Quét TỪNG DÒNG tin -> (điểm, số nhà, tên đường, phường theo tên).

    Điểm = tiêu chí dòng ĐỊA CHỈ (≥2 mới chấp nhận):
      +4 có 'địa chỉ / dự án / tòa nhà' | +2 có phường | +2 có quận quen thuộc
      +2 có tên đường viết tắt (XVNT...) | +1 số nhà có '/'
    Dòng ngày tháng ('3/11', 'M8/11 TRỐNG'), 'Mã phòng: 403', 'Giá: 6 tr'
    không đủ điểm -> KHÔNG bị nhận nhầm làm địa chỉ (lỗi cũ: địa chỉ lẫn rác).
    """
    best = (0, "", "", "")
    for line in lines:
        raw_line = str(line or "")
        # MỌI ứng viên số nhà trong dòng (bug cũ: re.match chỉ lấy ứng viên ĐẦU TIÊN ->
        # '...Lâu 1 Ngay 31/32/52 ung văn khiêm...' bị bỏ sót vì ứng viên đầu là '12')
        for hm in re.finditer(r"(?<![\d/A-Za-z])(\d[\d/A-Za-z]*)(?=\s+[A-Za-zÀ-ỹ])",
                              raw_line):
            hnum = hm.group(1)
            label, rest = raw_line[:hm.start()], raw_line[hm.end():]
            # '3/11' | '26/11' (≤31/≤12, không có phần thứ 3) = NGÀY -> bỏ
            dm = _DATE_RE.search(hnum)
            if (re.fullmatch(r"\d{1,2}/\d{1,2}", hnum) and dm
                    and int(dm.group(1)) <= 31 and int(dm.group(2)) <= 12):
                continue
            score = 0
            ns_label, ns_rest = norm(label), norm(rest)
            if _ADDR_ANCHOR_RE.search(ns_label):
                score += 4
            # đầu tin đăng: 'Cho thuê 319 Đường Quick Add giá...' (đủ điểm để tự điền)
            if re.search(r"\b(?:cho thue|nha cho thue|can ho cho thue|phong tro|mat bang)\b",
                         ns_label):
                score += 2
            if _WARD_RAW_RE.search(rest) or _WARD_NAME_RE.search(rest):
                score += 2
            if any(re.search(rf"\b{pat}\b", ns_rest) for pat, _ in _KNOWN_DISTRICTS):
                score += 2
            if any(t in _STREET_ABBR for t in ns_rest.split()):
                score += 2
            if "/" in hnum:
                score += 1
            if score < 2 or score <= best[0]:
                continue

            # ---- cắt tên đường tại ranh giới phường/quận/giá/SĐT/mã phòng
            rest2 = re.sub(r"(?:0|\+84)[\d\s.\-]{8,13}\d", " ", rest)
            rest2 = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:trieu|tr|nghin|k)\b", " ", rest2)
            rest2 = re.sub(r"\b\d{6,9}\b", " ", rest2)
            cut = len(rest2)
            wm = _WARD_RAW_RE.search(rest2)
            if wm:
                cut = min(cut, wm.start())
            # ranh giới DẤU PHẨY: chunk kế tiếp bắt đầu bằng phường/quận -> cắt tại đó
            pos = 0
            for i, chunk in enumerate(rest2.split(",")):
                if i:
                    cns = norm(chunk)
                    cns_bare = re.sub(r"^(?:q|quan)\.?\s+", "", cns)     # 'q. binh thanh' -> 'binh thanh'
                    if (_WARD_RAW_RE.search(chunk) or _WARD_WORD_RE.match(chunk)
                            or any(cns_bare.startswith(p) for p, _ in _KNOWN_DISTRICTS)):
                        cut = min(cut, pos)
                        break
                pos += len(chunk) + 1
            sm = _STOP_RAW_RE.search(rest2)
            if sm:
                cut = min(cut, sm.start())
            # token: cắt tại phường/quận theo token (cũ) + mã phòng dạng 'T23'/'P402'
            tokens = rest2.split()
            starts, p = [], 0
            for tok in tokens:
                idx = rest2.find(tok, p)
                starts.append(idx if idx >= 0 else p)
                p = (idx if idx >= 0 else p) + len(tok)
            _QNUM = re.compile(r"^[Qq]\.?\d{1,2}$")
            for i, tok in enumerate(tokens):
                one, two = norm(tok), norm(" ".join(tokens[i:i + 2]))
                hit = (any(one == pat or two == pat or two.startswith(pat + " ")
                           for pat, _ in _KNOWN_DISTRICTS)
                       or one in _KNOWN_DISTRICT_ABBR or _QNUM.match(tok)
                       or _ROOM_TOK_RE.match(tok))
                if hit and 0 <= starts[i] < cut:
                    cut = starts[i]

            street = collapse_space(rest2[:cut].strip(" ,.;:-"))
            street = re.sub(r"^(cho thue|can ho|phong|nha)\s+", "", street, flags=re.IGNORECASE)
            words = norm(street).split()
            if not street or not words:
                continue
            if words[0] in _NON_STREET_HEADS or words[0] in ("ma", "phong", "dang", "trong", "sap"):
                continue
            street = _STREET_ABBR.get(words[0], street) if len(words) == 1 else street
            ward_name = ""
            wn = _WARD_NAME_RE.search(rest)
            if wn:
                ward_name = collapse_space(wn.group(1)).strip(" ,.;:-")
            best = (score, hnum, street, ward_name)
    return best


def parse_listing_text(text: str) -> dict:
    """Phân tích tin đăng thuê nhà dạng text tự do -> dict các trường của form.

    Trả về dict có các khóa (None nếu không tách được -> "Chưa biết"):
    house_number, street, ward, district, price, deposit, room_type, area,
    floor, capacity, ev_support, pet_policy, owner_phone, notes,
    service_fee (chi phí dịch vụ), access_hours (giờ giấc),
    amenities (tiện ích tòa nhà)
    """
    out = {k: "" for k in ("house_number", "street", "ward", "district", "room_code",
                           "room_type", "area", "floor", "capacity", "pet_policy",
                           "owner_phone", "notes", "service_fee", "access_hours", "amenities")}
    # không tách được -> None (Chưa biết), KHÔNG được gán 0 (sẽ thành "Không")
    out.update({"price": None, "deposit": None, "ev_support": None})
    if not text or not str(text).strip():
        return out

    # GIỮ NGUYÊN xuống dòng theo TỪNG DÒNG -> tách địa chỉ/chi phí không lẫn rác
    lines = [collapse_space(strip_emoji(l)) for l in str(text).splitlines()]
    lines = [l for l in lines if l]
    raw = collapse_space(strip_emoji(str(text)))
    n = norm(raw)
    # bỏ số điện thoại khỏi n để không nhầm với giá (CHỈ khi là SĐT Việt Nam thật:
    # 03/05/07/08/09xxx hoặc 02xxx... - tránh '6.400.000 103' thành SĐT giả)
    phone_m = _PHONE_RE.search(raw)
    if phone_m:
        pk = phone_key(phone_m.group())
        if re.match(r"^0(?:3|5|7|8|9)\d{8}$|^0\d{2,3}\d{7,8}$", pk) and pk[:2] != "00":
            out["owner_phone"] = pk
            n = re.sub(r"(?:0|\+84)[\d\s.\-]{8,13}\d", " ", n)

    # ---- TIN NHIỀU PHÒNG: 'Mã 501_502: 6.400.000' | '103_104: 7.300.000'
    out["_rooms"] = []
    for line in lines:
        mm = re.match(r"^(?:ma(?:\s*phong)?)?\s*:?\s*(\d{3,4}(?:\s*[_\-]\s*\d{3,4})+)\s*:?\s*(.+)$",
                      norm(line))
        if not mm:
            continue
        price_g = normalize_price(mm.group(2))
        for code in re.split(r"[\s_\-]+", mm.group(1)):
            if code:
                out["_rooms"].append({"room_code": code,
                                      "price": price_g or None})

    # ---- giá thuê: ưu tiên 'giá chốt'/'giá'; bỏ qua 'cọc 3tr' (không phải giá)
    price = _money_near(n, ("gia chot", "gia cho thue", "gia thue", "gia", "thue", "price"),
                        skip_before=("coc",))
    if not price:
        for mm in re.finditer(
                r"\d{1,3}(?:\.\d{3})+(?:[.,]\d+)?\s*(?:trieu|tr|nghin|k)?"
                r"|\d+(?:[.,]\d+)?\s*(?:trieu|tr)(?:\d|\b(?!ng))"
                r"|\b\d{6,9}\b", n):
            if "coc" in n[max(0, mm.start() - 14):mm.start()]:
                continue        # 'cọc 3tr' -> không lấy làm giá
            v = normalize_price(mm.group(0))
            if v:
                price = v
                break
    # 'giá 4.8 triệu, giảm còn 4.5 triệu' -> giá HIỆN TẠI = mức giảm còn
    gm = re.search(r"giam\s+(?:con|di|gia con)?\s*:?\s*"
                   r"(\d+(?:[.,]\d+)?\s*(?:trieu|tr)\d?|\d{1,3}(?:\.\d{3})+)", n)
    if gm:
        gv = normalize_price(gm.group(1))
        if gv:
            price = gv
    out["price"] = price or None      # không tách được -> None (Chưa biết), không phải 0
    if out["_rooms"] and not out["price"]:
        out["price"] = out["_rooms"][0]["price"]

    # ---- tiền cọc: 'cọc 3tr' (tiền thật) | 'cọc 1th/1.5 tháng' (x số tiền THUÊ)
    deposit = 0
    for cm in re.finditer(r"\b(?:dat\s+)?coc\b", n):
        seg = n[cm.end(): cm.end() + 44]
        for pat in (_MONEY_TRDIG_RE, _MONEY_UNIT_RE, _MONEY_DOTS_RE, _MONEY_PLAIN_RE):
            mm = pat.search(seg)
            if mm and "gia" not in seg[max(0, mm.start() - 14):mm.start()]:
                v = normalize_price(mm.group(0))
                if v:
                    deposit = v
                    break
        if deposit:
            break
        if price:
            months = [float(x.group(1).replace(",", "."))
                      for x in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:thang|th)\b", seg)]
            months = [x for x in months if 0.5 <= x <= 3]
            if not months:
                mm = re.search(r"(\d+[.,]\d+)", seg)      # 'cọc 1.5' (không ghi 'tháng')
                if mm and 0.5 <= float(mm.group(1).replace(",", ".")) <= 3:
                    months = [float(mm.group(1).replace(",", "."))]
            if months:
                deposit = int(round(price * months[0]))
                break
    out["deposit"] = deposit or None

    # ---- dạng phòng
    for pat, label in _ROOM_TYPE_PATTERNS:
        if re.search(rf"\b{pat}\b", n):
            out["room_type"] = label
            break

    # ---- sức chứa: "2 người 2 xe" trước, sau đó "ở tối đa: 4 người"
    cm = _CAPACITY_RE.search(n)
    if cm:
        out["capacity"] = f"{cm.group(1)} Ng/{cm.group(2)} Xe"
    else:
        tm = re.search(r"toi da\s*:?\s*(\d{1,2})\s*(?:nguoi|ng)\b", n)
        if tm:
            out["capacity"] = f"{tm.group(1)} Ng"

    # ---- diện tích / tầng
    am = _AREA_RE.search(n)
    if am:
        out["area"] = am.group(1).replace(",", ".")
    fm = _FLOOR_RE.search(n)
    if fm:
        out["floor"] = fm.group(1)

    # ---- xe điện / thú cưng (ưu tiên PHỦ ĐỊNH: 'không xe điện' -> 0, không phải 1)
    if re.search(r"\bkhong (xe dien|sac xe|co sac)\b|\bxe dien\s*:?\s*khong\b", n):
        out["ev_support"] = 0
    elif re.search(r"\bxe dien\b|\bsac xe\b|\bco sac\b", n):
        out["ev_support"] = 1
    if re.search(r"\bkhong (pet|nuoi|thu cung)\b|\bcam pet\b|\bthu cung\s*:?\s*khong\b", n):
        out["pet_policy"] = "Không nuôi"
    elif re.search(r"\bthu cung\b", n):
        tc = re.search(r"\bthu cung\s*:?\s*(khong|co)\b", n)
        out["pet_policy"] = ("Không nuôi" if tc and tc.group(1) == "khong"
                             else "Cho nuôi (chó/mèo)")
    elif re.search(r"\b(pet|meo|cho nuoi|nuoi)\b", n):
        out["pet_policy"] = "Cho nuôi (chó/mèo)"

    # ---- khách nước ngoài (ưu tiên PHỦ ĐỊNH: 'không nhận khách nước ngoài' -> 0)
    if re.search(r"\bkhong (?:nhan |cho )?khach nuoc ngoai\b|\bkhach nuoc ngoai\s*:?\s*khong\b", n):
        out["foreign_guest"] = 0
    elif re.search(r"\b(?:nhan|cho)\s+khach nuoc ngoai\b|\bkhach nuoc ngoai\b", n):
        out["foreign_guest"] = 1

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

    # ---- dòng địa chỉ: số nhà + tên đường (QUÉT TỪNG DÒNG + CHẤM ĐIỂM)
    score, house, street, ward_name = _extract_address(lines)
    if score >= 2:
        out["house_number"], out["street"] = house, street
        if not out["ward"] and ward_name:
            out["ward"] = (ward_name if norm(ward_name).startswith(("p ", "p."))
                           else f"Phường {ward_name}")
        if not out["ward"]:
            wm = _WARD_RE.search(norm(street))
            if wm:
                out["ward"] = f"P. {wm.group(1) or wm.group(2)}"
        if not out["district"]:
            np_ = norm(street)
            for pat, name in _KNOWN_DISTRICTS:
                if re.search(rf"\b{pat}\b", np_):
                    out["district"] = name
                    break

    # ---- mã phòng: 'Mã phòng: 403' / 'Phòng 302' / 'P402 (...)' / 'Sắp trống: 402'
    out["room_code"] = ""
    for line in lines:
        ln = norm(line)
        m = re.match(r"^p(\d{3,4})\b", ln) or re.search(
            r"\b(?:ma(?:\s*phong)?|phong(?:\s*trong)?|sap trong|trong)\s*:?\s*"
            r"(p?[a-z]?\d{3,4})\b", ln)
        if m:
            code = m.group(1)
            if re.fullmatch(r"p\d{3,4}", code):
                code = code[1:]
            elif not code.isdigit():
                code = code.upper()
            out["room_code"] = code
            break
    if not out["room_code"] and out["_rooms"]:
        out["room_code"] = out["_rooms"][0]["room_code"]   # tin nhiều phòng: lấy mã đầu

    # ---- chi phí dịch vụ / giờ giấc / tiện ích tòa nhà (theo TỪNG DÒNG)
    out.update(_parse_fee_hours_amenities(lines, n))

    # ---- ghi chú: phần text còn lại (nguyên văn, không phân tích được)
    out["notes"] = collapse_space(strip_emoji(str(text)))[:500]
    return out
