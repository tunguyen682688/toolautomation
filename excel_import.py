# -*- coding: utf-8 -*-
"""excel_import.py - Đọc Excel thông minh: nhận diện sheet, phát hiện dòng tiêu đề, ánh xạ cột tự động.

Không phụ thuộc cấu trúc cố định: quét 30 dòng đầu để tìm dòng tiêu đề, cho phép người dùng
hiệu chỉnh ánh xạ cột (mapping) trước khi nhập -> đọc được mọi file Excel cùng loại.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

import text_utils as tu
from models import BUILDING_COLUMNS, ROOM_COLUMNS, RoomStatus
from logger import get_logger

log = get_logger("excel")

_MAX_HEADER_SCAN = 30
_MAX_ROWS = 20000

# bộ alias dùng để nhận diện dòng tiêu đề
_ROOM_ALIASES = set()
for _c in ROOM_COLUMNS:
    _ROOM_ALIASES.add(tu.normalize_header(_c["header"]))
    for a in _c["aliases"]:
        _ROOM_ALIASES.add(tu.normalize_header(a))
_BUILDING_ALIASES = set()
for _c in BUILDING_COLUMNS:
    _BUILDING_ALIASES.add(tu.normalize_header(_c["header"]))
    for a in _c["aliases"]:
        _BUILDING_ALIASES.add(tu.normalize_header(a))


@dataclass
class SheetTable:
    title: str
    kind: str                    # rooms | buildings | other
    header_row: int              # 1-based
    start_col: int               # 1-based
    headers: List[str]
    rows: List[Dict[str, Any]]   # {'excel_row': int, 'cells': List[Any]}
    mapping: Dict[str, int] = field(default_factory=dict)   # field -> index trong headers

    @property
    def header_labels(self) -> List[str]:
        return list(self.headers)


@dataclass
class ParsedFile:
    path: str
    sheets: List[SheetTable] = field(default_factory=list)
    stats_formulas: Dict[str, Any] = field(default_factory=dict)
    stats_sheet: str = ""
    error: str = ""

    @property
    def rooms(self) -> Optional[SheetTable]:
        for s in self.sheets:
            if s.kind == "rooms":
                return s
        return None

    @property
    def buildings(self) -> Optional[SheetTable]:
        for s in self.sheets:
            if s.kind == "buildings":
                return s
        return None


# ------------------------------------------------------------------ đọc file
def read_workbook(path: str) -> ParsedFile:
    """Đọc toàn bộ workbook -> danh sách bảng dữ liệu (không phụ thuộc vị trí cột A, dòng tiêu đề)."""
    out = ParsedFile(path=str(path))
    try:
        wb = load_workbook(str(path), data_only=True, read_only=False)
    except Exception as e:  # file hỏng / sai định dạng
        out.error = f"Không đọc được file Excel: {e}"
        log.exception("read_workbook")
        return out

    for ws in wb.worksheets:
        if "thong ke" in tu.norm(ws.title) or "bao cao" in tu.norm(ws.title):
            if not out.stats_sheet:
                out.stats_sheet = ws.title
            continue  # sheet thống kê -> xử lý riêng bên dưới
        table = _parse_sheet(ws)
        if table and table.headers:
            out.sheets.append(table)

    # đọc sheet thống kê (giữ công thức gốc để export không làm mất dữ liệu cũ)
    parsed_titles = {s.title for s in out.sheets}
    for ws in wb.worksheets:
        if ws.title in parsed_titles:
            continue
        try:
            formulas = _read_stats(ws)
            if formulas:
                out.stats_formulas = formulas
                out.stats_sheet = ws.title
        except Exception:
            pass
    wb.close()
    return out


def _read_stats(ws) -> Dict[str, Any]:
    formulas: Dict[str, Any] = {}
    try:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    formulas[c.coordinate] = v
    except Exception:
        pass
    return formulas


def _parse_sheet(ws) -> Optional[SheetTable]:
    """Đọc 1 sheet openpyxl -> SheetTable (dùng chung parse_grid với dữ liệu từ Google Sheets)."""
    values = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 5000), values_only=True))
    return parse_grid(values, ws.title)


def parse_grid(values: List[List[Any]], title: str) -> Optional[SheetTable]:
    """Nhận diện dòng tiêu đề + kind của một lưới dữ liệu (file Excel hoặc API values của Sheets).

    Không phụ thuộc cột A, dòng tiêu đề hay thứ tự cột.
    """
    if not values:
        return None
    best = None  # (score, row_idx, start_col, kind)
    for r_idx, row in enumerate(values[:_MAX_HEADER_SCAN], start=1):
        cells = list(row)
        # tìm các cột có tiêu đề
        hits_room, hits_build = [], []
        for c_idx, val in enumerate(cells, start=1):
            h = tu.normalize_header(val)
            if not h:
                continue
            if h in _ROOM_ALIASES:
                hits_room.append(c_idx)
            if h in _BUILDING_ALIASES:
                hits_build.append(c_idx)
        score_room, score_build = len(hits_room), len(hits_build)
        if score_room >= 4 and (best is None or score_room > best[0]):
            best = (score_room, r_idx, min(hits_room), "rooms")
        if score_build >= 4 and (best is None or score_build > best[0]):
            best = (score_build, r_idx, min(hits_build), "buildings")

    if best is None:
        return None
    _, header_row, start_col, kind = best

    rows_vals = list(values[header_row - 1:])
    header_cells = list(rows_vals[0]) if rows_vals else []
    # giới hạn cột: từ start_col đến cột cuối có tiêu đề
    last_col = len(header_cells)
    while last_col > start_col and not tu.normalize_header(header_cells[last_col - 1]):
        last_col -= 1
    headers = []
    for i in range(start_col - 1, last_col):
        headers.append(str(header_cells[i]).strip() if header_cells[i] is not None else f"Cột {i + 1}")

    data_rows: List[Dict[str, Any]] = []
    for offset, row in enumerate(rows_vals[1:], start=1):
        cells = list(row)
        values = [cells[i] if i < len(cells) else None for i in range(start_col - 1, last_col)]
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        # bỏ dòng tiêu đề phụ / dòng tổng
        first_text = tu.norm(values[0]) if values else ""
        joined = tu.norm(" ".join(str(v) for v in values[:4]))
        if "tong cong" in joined or "trung binh" in joined:
            continue
        data_rows.append({"excel_row": header_row + offset, "cells": values})

    table = SheetTable(title=title, kind=kind, header_row=header_row, start_col=start_col,
                       headers=headers, rows=data_rows)
    table.mapping = detect_mapping(headers, kind)
    return table


# ------------------------------------------------------------------ ánh xạ cột
def detect_mapping(headers: List[str], kind: str = "rooms") -> Dict[str, int]:
    """Ghép tên cột Excel -> khoá trường. Ưu tiên tên chính xác, sau đó alias."""
    cols = ROOM_COLUMNS if kind == "rooms" else BUILDING_COLUMNS
    norm_headers = [tu.normalize_header(h) for h in headers]
    mapping: Dict[str, int] = {}
    used = set()
    # pass 1: tên chuẩn hoá trùng khớp chính xác
    for c in cols:
        target = tu.normalize_header(c["header"])
        for i, h in enumerate(norm_headers):
            if i in used or not h:
                continue
            if h == target:
                mapping[c["name"]] = i
                used.add(i)
                break
    # pass 2: alias / chứa từ khoá
    for c in cols:
        if c["name"] in mapping:
            continue
        aliases = [tu.normalize_header(a) for a in c.get("aliases", [])]
        for i, h in enumerate(norm_headers):
            if i in used or not h:
                continue
            if h in aliases:
                mapping[c["name"]] = i
                used.add(i)
                break
    # pass 3: chứa alias làm chuỗi con (vd: "Giá Thuê (VNĐ)" đã bắt ở pass1; "Nhà / Số Nhà" bắt ở đây)
    for c in cols:
        if c["name"] in mapping:
            continue
        for i, h in enumerate(norm_headers):
            if i in used or not h:
                continue
            if any(a and (a in h or h in a) for a in [tu.normalize_header(c["header"])] +
                   [tu.normalize_header(a) for a in c.get("aliases", [])]):
                mapping[c["name"]] = i
                used.add(i)
                break
    return mapping


def mapping_report(table: SheetTable) -> Dict[str, Any]:
    """Báo cáo ánh xạ để UI hiển thị: cột đã ghép, cột chưa ghép, cột thừa."""
    mapped = {i for i in table.mapping.values()}
    cols = ROOM_COLUMNS if table.kind == "rooms" else BUILDING_COLUMNS
    unmatched_headers = [h for i, h in enumerate(table.headers) if i not in mapped and h]
    missing_fields = [c["header"] for c in cols
                      if c["name"] not in table.mapping and c["name"] in ("house_number", "street")]
    return {
        "kind": table.kind,
        "mapped": {c["name"]: table.headers[table.mapping[c["name"]]]
                   for c in cols if c["name"] in table.mapping},
        "unmatched_headers": unmatched_headers,
        "missing_required": missing_fields,
        "rows": len(table.rows),
        "header_row": table.header_row,
        "start_col": table.start_col,
    }


# ------------------------------------------------------------------ công thức Thống Kê (giữ dữ liệu cũ)
_STATS_CACHE = None


def _stats_cache_file():
    global _STATS_CACHE
    if _STATS_CACHE is None:
        from config import get_cache_dir
        _STATS_CACHE = get_cache_dir() / "stats_formulas.json"
    return _STATS_CACHE


def save_stats_formulas(formulas: Dict[str, Any], sheet: str = "") -> None:
    """Lưu công thức COUNTIF đọc được từ file Excel gốc -> export vẫn giữ nguyên."""
    if not formulas:
        return
    try:
        import json
        _stats_cache_file().write_text(json.dumps({"sheet": sheet, "formulas": formulas},
                                                  ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.debug("Không lưu được công thức thống kê: %s", e)


def load_stats_formulas() -> Dict[str, Any]:
    try:
        import json
        f = _stats_cache_file()
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


# ------------------------------------------------------------------ -> payload
def cell(row_cells: List[Any], mapping: Dict[str, int], field_name: str) -> Any:
    idx = mapping.get(field_name)
    if idx is None or idx >= len(row_cells):
        return None
    v = row_cells[idx]
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def tri_parse_survey(v: Any) -> Optional[int]:
    """Excel cột Khảo Sát -> 1 | 0 | None.

    Trống hoặc 'Chưa biết' -> None (đang hỏi); 'Đã KS ...' -> 1; 'Chưa KS' -> 0.
    (parse_survey() ép mọi thứ không phải 'đã...' về False -> phải tách ô trống riêng.)
    """
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or tu.norm(s) == "chua biet":
            return None
        return 1 if tu.parse_survey(s) else 0
    return 1 if v else 0


def tri_parse_yes_no(v: Any) -> Optional[int]:
    """Excel cột Yes/No (Xe điện...) -> 1 | 0 | None (trống/không đọc được = Chưa biết)."""
    b = tu.parse_yes_no(v)
    return None if b is None else (1 if b else 0)


def room_payload_from_row(row: Dict[str, Any], mapping: Dict[str, int]) -> Dict[str, Any]:
    """Chuyển 1 dòng Excel -> payload phòng (đã chuẩn hoá kiểu dữ liệu)."""
    c = row["cells"]
    status_raw = cell(c, mapping, "status")
    survey_raw = cell(c, mapping, "surveyed")
    price_raw = cell(c, mapping, "price")
    deposit_raw = cell(c, mapping, "deposit")
    payload = {
        "excel_row": row["excel_row"],
        "house_number": cell(c, mapping, "house_number"),
        "street": cell(c, mapping, "street"),
        "ward": cell(c, mapping, "ward"),
        "district": cell(c, mapping, "district"),
        "room_code": cell(c, mapping, "room_code"),
        "unit_code": cell(c, mapping, "unit_code"),
        "floor": cell(c, mapping, "floor"),
        "room_type": cell(c, mapping, "room_type"),
        # cột không có trong file -> để None (KHÔNG được tự ghi đè dữ liệu cũ khi cập nhật)
        "status": RoomStatus.from_text(status_raw) if "status" in mapping else None,
        "status_text": str(status_raw or ""),
        # 3 trạng thái: None = Chưa biết, 1 = Có/Đã KS, 0 = Không/Chưa KS
        "surveyed": (tri_parse_survey(survey_raw) if "surveyed" in mapping else None),
        "price": tu.normalize_price(price_raw) if price_raw not in (None, "") else None,
        "deposit": tu.normalize_price(deposit_raw) if deposit_raw not in (None, "") else None,
        "capacity": cell(c, mapping, "capacity"),
        "ev_support": (tri_parse_yes_no(cell(c, mapping, "ev_support"))
                       if "ev_support" in mapping else None),
        "pet_policy": tu.parse_pet_policy(cell(c, mapping, "pet_policy")),
        "rating": cell(c, mapping, "rating"),
        "owner_phone": cell(c, mapping, "owner_phone"),
        "zalo_group": cell(c, mapping, "zalo_group"),
        "drive_link": cell(c, mapping, "drive_link"),
        "notes": cell(c, mapping, "notes"),
        "stt": cell(c, mapping, "stt"),
    }
    if "price" not in mapping:
        payload["price"] = None   # cột không có trong file -> để Chưa biết, không tự đoán 0
    if "deposit" not in mapping:
        payload["deposit"] = None
    return payload


def building_payload_from_row(row: Dict[str, Any], mapping: Dict[str, int]) -> Dict[str, Any]:
    c = row["cells"]
    return {
        "excel_row": row["excel_row"],
        "house_number": cell(c, mapping, "house_number"),
        "street": cell(c, mapping, "street"),
        "ward": cell(c, mapping, "ward"),
        "district": cell(c, mapping, "district"),
        "owner_name": cell(c, mapping, "owner_name"),
        "phone": cell(c, mapping, "phone"),
        "zalo_group": cell(c, mapping, "zalo_group"),
        "ev_policy": cell(c, mapping, "ev_policy"),
        "pet_policy": cell(c, mapping, "pet_policy"),
        "commission": cell(c, mapping, "commission"),
    }


# ------------------------------------------------------------------ kết quả phân tích
KIND_LABEL = {
    "new": "Dữ liệu mới",
    "duplicate": "Trùng hoàn toàn",
    "changed": "Có thay đổi",
    "suspect": "Nghi ngờ trùng",
    "error": "Lỗi",
}
KIND_COLOR = {
    "new": "#16a34a",
    "duplicate": "#6b7280",
    "changed": "#2563eb",
    "suspect": "#f97316",
    "error": "#dc2626",
}


@dataclass
class ImportItem:
    excel_row: int
    payload: Dict[str, Any]
    kind: str
    reason: str
    existing: Optional[Dict] = None
    building_id: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)


@dataclass
class ImportPlan:
    filename: str
    items: List[ImportItem] = field(default_factory=list)
    building_items: List[Dict] = field(default_factory=list)
    mapping_rooms: Dict[str, int] = field(default_factory=dict)
    mapping_buildings: Dict[str, int] = field(default_factory=dict)
    error: str = ""

    def counts(self) -> Dict[str, int]:
        out = {"new": 0, "duplicate": 0, "changed": 0, "suspect": 0, "error": 0}
        for it in self.items:
            out[it.kind] = out.get(it.kind, 0) + 1
        out["total"] = len(self.items)
        return out


def build_plan(parsed: ParsedFile, checker, db=None) -> ImportPlan:
    """Đọc file đã parse -> danh sách dòng phân loại (mới / trùng / có thay đổi / nghi ngờ / lỗi)."""
    from duplicate_checker import fingerprint as _fp, DuplicateChecker

    plan = ImportPlan(filename=Path(parsed.path).name)
    table = parsed.rooms
    if table is None:
        plan.error = "Không tìm thấy sheet danh sách phòng (cần cột: Trạng Thái / Mã Phòng / Giá Thuê...)."
        return plan
    plan.mapping_rooms = dict(table.mapping)

    seen_fp: Dict[str, int] = {}            # fingerprint -> dòng đầu tiên
    seen_id: Dict[str, int] = {}            # building|unit -> dòng đầu tiên
    local_buildings: Dict[str, str] = {}    # address_key -> id (thực tế hoặc ảo trong file)

    for row in table.rows:
        payload = room_payload_from_row(row, table.mapping)
        res = checker.classify(payload, seen_fingerprints=seen_fp, seen_identities=seen_id)
        item = ImportItem(excel_row=row["excel_row"], payload=payload, kind=res["kind"],
                          reason=res["reason"], existing=res["existing"])
        if res.get("existing"):
            item.building_id = res["existing"].get("building_id", "")
        plan.items.append(item)

        if res["kind"] == "error":
            continue
        # đăng ký để phát hiện trùng NGAY TRONG FILE (kể cả khi tòa nhà chưa có trong DB)
        fp = _fp(payload)
        if fp not in seen_fp:
            seen_fp[fp] = row["excel_row"]
        addr_key = tu.address_key(payload.get("house_number"), payload.get("street"),
                                  payload.get("ward"), payload.get("district"))
        if addr_key:
            if addr_key not in local_buildings:
                b = res.get("existing") or checker._resolve_building(payload)
                local_buildings[addr_key] = (b.get("id") if isinstance(b, dict) and b.get("id")
                                             else f"LOCAL:{addr_key}")
            ident = DuplicateChecker.identity_key(payload, {"id": local_buildings[addr_key]})
            if ident:
                seen_id.setdefault(f"{local_buildings[addr_key]}|{ident}", row["excel_row"])

    # sheet danh mục địa điểm (nếu có)
    btable = parsed.buildings
    if btable is not None:
        plan.mapping_buildings = dict(btable.mapping)
        for row in btable.rows:
            plan.building_items.append(building_payload_from_row(row, btable.mapping))
    return plan
