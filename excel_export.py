# -*- coding: utf-8 -*-
"""excel_export.py - Xuất Excel đúng cấu trúc gốc (3 sheet, tiêu đề ở dòng 5, công thức Thống Kê).

Dùng chung ``room_to_row_values`` với đường đồng bộ Google Sheets -> Excel và Sheets luôn giống hệt nhau.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import text_utils as tu
from models import RoomStatus

TITLE_FONT = Font(bold=True, size=14, color="1F2937")
SUB_FONT = Font(italic=True, size=10, color="6B7280")
HEAD_FONT = Font(bold=True, size=10, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="2563EB")
THIN = Side(style="thin", color="D1D5DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ------------------------------------------------------------------ giá trị ô
def _field_value(field: str, room: Dict[str, Any], building: Dict[str, Any]) -> Any:
    def bld(key):
        return room.get(key) if room.get(key) not in (None, "") else building.get(key, "")

    if field == "stt":
        return None
    if field == "status":
        return RoomStatus.label(room.get("status", "new"))
    if field == "surveyed":
        v = room.get("surveyed")
        if v is None:
            return "Chưa biết"        # NULL = chưa hỏi -> Excel cũng phải nói rõ
        return "Đã KS 📸" if v else "Chưa KS"
    if field in ("house_number", "street", "ward", "district"):
        return bld(field) or ""
    if field in ("price", "deposit"):
        v = room.get(field)
        return "" if v is None else int(v)   # NULL = Chưa biết -> ô trống (không ghi 0 giả)
    if field == "ev_support":
        v = room.get("ev_support")
        if v is None:
            return "Chưa biết"        # import đọc lại 'Chưa biết' -> None (3 trạng thái)
        return "Có sạc" if v else "Không"
    if field == "pet_policy":
        return room.get("pet_policy") or ""
    if field == "foreign_guest":
        v = room.get("foreign_guest")
        if v is None:
            return "Chưa biết"
        return "Có 🌏" if v else "Không"
    if field == "area":
        return room.get("area") or ""
    return room.get(field, "") if room.get(field) is not None else ""


def room_to_row_values(room: Dict[str, Any], building: Optional[Dict[str, Any]],
                       mapping: Dict[str, int], ncols: int) -> List[Any]:
    """Đưa 1 phòng thành 1 dòng ô theo ánh xạ cột của sheet đích."""
    building = building or {}
    values: List[Any] = [""] * ncols
    for field, idx in mapping.items():
        if idx is None or idx >= ncols:
            continue
        values[idx] = _field_value(field, room, building)
    return values


def building_to_row_values(b: Dict[str, Any], mapping: Dict[str, int], ncols: int) -> List[Any]:
    values: List[Any] = [""] * ncols
    for field, idx in mapping.items():
        if idx is None or idx >= ncols:
            continue
        values[idx] = b.get(field, "") or ""
    return values


# ------------------------------------------------------------------ export workbook
def _write_sheet(ws, title: str, subtitle: str, headers: List[str], rows: List[List[Any]],
                 widths: Optional[List[int]] = None, col_start: int = 2) -> None:
    """Bố cục giống file gốc: cột A trống, tiêu đề lớn ở dòng 2-3, header dòng 5."""
    ws.cell(row=2, column=col_start, value=title).font = TITLE_FONT
    ws.cell(row=3, column=col_start, value=subtitle).font = SUB_FONT
    for j, h in enumerate(headers):
        c = ws.cell(row=5, column=col_start + j, value=h)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, row in enumerate(rows, start=6):
        for j, v in enumerate(row):
            c = ws.cell(row=i, column=col_start + j, value=v)
            c.border = BORDER
            c.alignment = Alignment(vertical="center", wrap_text=False)
    ws.freeze_panes = ws.cell(row=6, column=col_start)
    for j, h in enumerate(headers):
        w = (widths[j] if widths and j < len(widths) else 18)
        ws.column_dimensions[get_column_letter(col_start + j)].width = w


ROOM_HEADERS = ["STT", "Trạng Thái", "Khảo Sát", "Số Nhà", "Tên Đường", "Phường",
                "Quận / Khu Vực Cũ", "Mã Phòng", "Dạng Phòng", "Giá Thuê (VNĐ)", "Cọc (VNĐ)",
                "Tối Đa (Người/Xe)", "Xe Điện ⚡", "Nuôi Pet 🐾", "Đánh Giá / Độ Đẹp ⭐",
                "SĐT Chủ / Admin", "Group Zalo Tòa Nhà", "Link Drive Kho Media",
                "Chính Sách & Ghi Chú Chi Tiết", "Nhận Khách Nước Ngoài 🌏", "Diện Tích (m2)",
                # 2 cột BỔ SUNG cuối bảng (không dịch chuyển cột cũ -> công thức/định dạng gốc giữ nguyên)
                "Số Căn", "Tầng"]
BUILDING_HEADERS = ["STT", "Số Nhà", "Tên Đường", "Phường", "Quận / Khu Vực Cũ",
                    "Chủ Tòa / Admin QLH", "Số Điện Thoại", "Link Group Zalo", "Quy Định Xe Điện",
                    "Quy Định Pet", "Chính Sách Hoa Hồng Sale"]


def export_workbook(path: str, rooms: List[Dict[str, Any]], buildings: List[Dict[str, Any]],
                    stats: Dict[str, Any], stats_formulas: Optional[Dict[str, Any]] = None,
                    include_deleted: bool = False) -> str:
    """Xuất toàn bộ dữ liệu ra file Excel đúng cấu trúc 3 sheet gốc.

    ``stats_formulas``: công thức COUNTIF đọc từ file gốc (nếu có) để GIỮ NGUYÊN khi export.
    """
    wb = Workbook()

    # ---------------- Sheet 1: kho phòng ----------------
    ws = wb.active
    ws.title = "Kho Hàng Phòng Trống"
    bmap = {b["id"]: b for b in buildings}
    mapping = {name: i for i, name in enumerate(
        ["stt", "status", "surveyed", "house_number", "street", "ward", "district", "room_code",
         "room_type", "price", "deposit", "capacity", "ev_support", "pet_policy", "rating",
         "owner_phone", "zalo_group", "drive_link", "notes", "foreign_guest", "area", "unit_code", "floor"])}
    data_rows: List[List[Any]] = []
    for i, r in enumerate(rooms, start=1):
        if r.get("deleted") and not include_deleted:
            continue
        vals = room_to_row_values(r, bmap.get(r.get("building_id"), {}), mapping, len(ROOM_HEADERS))
        vals[0] = i
        data_rows.append(vals)

    _write_sheet(ws, "KHO HÀNG PHÒNG TRỐNG",
                 "Dữ liệu tổng hợp từ phần mềm quản lý kho căn hộ (xuất từ SQLite/Google Sheets)",
                 ROOM_HEADERS, data_rows, widths=[6, 16, 12, 10, 20, 12, 18, 14, 14, 14, 14,
                                                  16, 12, 14, 30, 24, 26, 34, 60, 16, 12, 10, 12, 8])
    # dòng tổng cộng
    total_row = 6 + len(data_rows)
    ws.cell(row=total_row, column=3, value="TỔNG CỘNG / TRUNG BÌNH").font = Font(bold=True)
    ws.cell(row=total_row, column=11, value=f"=AVERAGE(K6:K{total_row - 1})")
    ws.cell(row=total_row, column=12, value=f"=AVERAGE(L6:L{total_row - 1})")

    # ---------------- Sheet 2: danh mục ----------------
    ws2 = wb.create_sheet("Danh Mục Địa Điểm & Chủ Nhà")
    bmap_cols = ["house_number", "street", "ward", "district", "owner_name", "phone",
                 "zalo_group", "ev_policy", "pet_policy", "commission"]
    mapping2 = {name: i for i, name in enumerate(bmap_cols)}
    rows2 = []
    for i, b in enumerate(buildings, start=1):
        if b.get("deleted"):
            continue
        v = building_to_row_values(b, mapping2, len(BUILDING_HEADERS))
        v.insert(0, i)
        rows2.append(v)
    _write_sheet(ws2, "DANH MỤC ĐỊA ĐIỂM, CHỦ NHÀ & QUY ĐỊNH CHUNG",
                 "Danh sách địa điểm nhà/tòa nhà phân loại theo Số Nhà - Tên Đường - Phường - Quận / Khu Vực Cũ",
                 BUILDING_HEADERS, rows2, widths=[6, 12, 22, 14, 20, 24, 26, 28, 18, 16, 34])

    # ---------------- Sheet 3: thống kê ----------------
    ws3 = wb.create_sheet("Thống Kê Nhanh")
    _write_stats_sheet(ws3, stats, stats_formulas, len(data_rows))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _write_stats_sheet(ws, stats: Dict[str, Any], formulas: Optional[Dict[str, Any]], n_rooms: int) -> None:
    status = stats.get("status", {})
    by_type = stats.get("by_type", {}) or {}
    ws.cell(row=2, column=2, value="BÁO CÁO NHANH KHO PHÒNG TRỐNG").font = TITLE_FONT
    ws.cell(row=3, column=2, value="Theo dõi tổng số lượng phòng, loại phòng và điều kiện tiện ích").font = SUB_FONT
    ws.cell(row=5, column=2, value="1. TỔNG QUAN CHỈ SỐ KHO HÀNG").font = Font(bold=True, size=12)
    heads = ["Chỉ Số Kho Hàng", "Số Lượng Phòng", "Ghi Chú Cho Sale"]
    for j, h in enumerate(heads):
        c = ws.cell(row=6, column=2 + j, value=h)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER

    overview = [
        ("Tổng số phòng trong kho", stats.get("total", 0), "Số mã phòng đang quản lý"),
        ("Số phòng TRỐNG Ở NGAY", status.get("vacant", 0), "Ưu tiên chốt dắt khách ngay"),
        ("Số phòng SẮP TRỐNG (Cọc trước)", status.get("soon_vacant", 0), "Chào khách nhận nhà tháng tới"),
        ("Số phòng ĐÃ KHẢO SÁT (Có ảnh/video 📸)", stats.get("surveyed", 0), "Sẵn sàng gửi media cho khách"),
        ("Số phòng HỖ TRỢ XE ĐIỆN ⚡", stats.get("ev", 0), "Dành cho khách đi xe điện"),
        ("Số phòng CHO NUÔI PET 🐾", stats.get("pet", 0), "Dành cho khách nuôi chó/mèo"),
    ]
    for i, (label, val, note) in enumerate(overview, start=7):
        ws.cell(row=i, column=2, value=label).border = BORDER
        ws.cell(row=i, column=3, value=val).border = BORDER
        ws.cell(row=i, column=4, value=note).border = BORDER

    ws.cell(row=14, column=2, value="2. PHÂN LOẠI PHÒNG TRỐNG THEO DẠNG PHÒNG").font = Font(bold=True, size=12)
    heads2 = ["Dạng Phòng", "Tổng Số Phòng", "Trống Ở Ngay", "Có Sạc Xe Điện ⚡", "Cho Nuôi Pet 🐾"]
    for j, h in enumerate(heads2):
        c = ws.cell(row=15, column=2 + j, value=h)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER
    types = ["Studio", "1 Phòng Ngủ", "2 Phòng Ngủ", "Duplex", "Penthouse"]
    for i, t in enumerate(types, start=16):
        d = by_type.get(t, {})
        ws.cell(row=i, column=2, value=t).border = BORDER
        ws.cell(row=i, column=3, value=d.get("total", 0)).border = BORDER
        ws.cell(row=i, column=4, value=d.get("vacant", 0)).border = BORDER
        ws.cell(row=i, column=5, value=d.get("ev", 0)).border = BORDER
        ws.cell(row=i, column=6, value=d.get("pet", 0)).border = BORDER

    # GIỮ NGUYÊN công thức gốc nếu file nguồn có (không làm mất dữ liệu cũ)
    if formulas:
        for coord, formula in formulas.items():
            if not str(formula).startswith("="):
                continue
            try:
                ws[coord] = formula
            except Exception:
                pass

    for col, w in (("B", 40), ("C", 18), ("D", 34), ("E", 20), ("F", 20)):
        ws.column_dimensions[col].width = w


def export_template(path: str) -> str:
    """Xuất file Excel mẫu trống đúng cấu trúc -> dùng cho nhập liệu thủ công."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Kho Hàng Phòng Trống"
    _write_sheet(ws, "KHO HÀNG PHÒNG TRỐNG", "File mẫu nhập liệu", ROOM_HEADERS, [],
                 widths=[6, 16, 12, 10, 20, 12, 18, 14, 14, 14, 14, 16, 12, 14, 30, 24, 26, 34, 60, 12, 8])
    ws2 = wb.create_sheet("Danh Mục Địa Điểm & Chủ Nhà")
    _write_sheet(ws2, "DANH MỤC ĐỊA ĐIỂM, CHỦ NHÀ & QUY ĐỊNH CHUNG", "File mẫu",
                 BUILDING_HEADERS, [], widths=[6, 12, 22, 14, 20, 24, 26, 28, 18, 16, 34])
    ws3 = wb.create_sheet("Thống Kê Nhanh")
    _write_stats_sheet(ws3, {"total": 0, "status": {}, "by_type": {}}, None, 0)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
