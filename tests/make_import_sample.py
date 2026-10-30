# -*- coding: utf-8 -*-
"""Tạo file Excel mẫu dùng để kiểm thử Nhập Excel (chứa cả dòng mới / trùng / đổi / lỗi).

Chạy:  python tests/make_import_sample.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

HEADERS = ["STT", "Trạng Thái", "Khảo Sát", "Số Nhà", "Tên Đường", "Phường",
           "Quận / Khu Vực Cũ", "Mã Phòng", "Dạng Phòng", "Giá Thuê (VNĐ)", "Cọc (VNĐ)",
           "Tối Đa (Người/Xe)", "Xe Điện ⚡", "Nuôi Pet 🐾", "Đánh Giá / Độ Đẹp ⭐",
           "SĐT Chủ / Admin", "Group Zalo Tòa Nhà", "Link Drive Kho Media",
           "Chính Sách & Ghi Chú Chi Tiết"]

# (loại dòng, dữ liệu) - dùng để đối chiếu với kết quả phân loại khi import
ROWS = [
    # 1) DỮ LIỆU MỚI - địa chỉ chưa có trong hệ thống
    ("new", ["Trống ở ngay", "Chưa KS", "12", "Nguyễn Văn C", "P. 14", "Q. Phú Nhuận cũ",
             "P-12NC", "Studio", 5500000, 5500000, "2 Ng/2 Xe", "Có sạc", "Cho nuôi Mèo",
             "⭐⭐⭐⭐ Máy lạnh mới", "0900000001", "zalo.me/g/tunguyenland",
             "drive.google.com/folder/p-12nc", "Nội thất: cơ bản"]),
    ("new", ["Trống ở ngay", "Đã KS 📸", "45/2", "Nguyễn Văn C", "P. 14", "Q. Phú Nhuận cũ",
             "P-452NC", "1 Phòng Ngủ", 7000000, 7000000, "2 Ng/2 Xe", "Có sạc", "Cho nuôi Mèo",
             "⭐⭐⭐⭐⭐ Ban công đẹp", "0900000002", "zalo.me/g/tunguyenland",
             "drive.google.com/folder/p-452nc", "Nội thất: full nội thất"]),
    # 2) TRÙNG HOÀN TOÀN với dữ liệu đang có (86 Nguyễn Thượng Hiền - P-86)
    ("duplicate", ["Trống ở ngay", "Đã KS 📸", "86", "Nguyễn Thượng Hiền", "P. 13",
                   "Q. Bình Thạnh cũ", "P-86", "1 Phòng Ngủ", 7000000, 7000000, "2 Ng/2 Xe",
                   "Có sạc", "Cho nuôi Mèo", "⭐⭐⭐⭐ Ban công rộng, thoáng đẹp",
                   "0868328147 (Tú Nguyễn Land)", "zalo.me/g/tunguyenland",
                   "drive.google.com/folder/p-86", "Nội thất: phòng trống | Tiện ích: thang máy"]),
    # 3) ĐÃ CÓ nhưng ĐỔI GIÁ THUÊ -> đề xuất cập nhật bản ghi cũ
    ("changed", ["Trống ở ngay", "Chưa KS", "170", "Nguyễn Thượng Hiền", "P. 13",
                 "Q. Bình Thạnh cũ", "P-170", "Studio", 7800000, 7800000, "2 Ng/2 Xe",
                 "Có sạc", "Cho nuôi Mèo", "⭐⭐⭐⭐ Ban công rộng, thoáng đẹp",
                 "ht anh minh sơn", "zalo.me/g/tunguyenland", "drive.google.com/folder/p-170",
                 "Giá điều chỉnh 7.800.000"]),
    # 4) NGHI NGỜ TRÙNG - khác cách viết địa chỉ (Phường 13 vs P. 13, số nhà cách nhau)
    ("suspect", ["Trống ở ngay", "Chưa KS", " 404 ", "Nguyễn Xí", "Phường 13",
                 "Bình Thạnh", "P-404-MOI", "1 Phòng Ngủ", 8000000, 8000000, "2 Ng/2 Xe",
                 "Có sạc", "Cho nuôi Mèo", "⭐⭐⭐⭐ Máy lạnh mới", "342123429",
                 "zalo.me/g/tunguyenland", "drive.google.com/folder/p-404-moi",
                 "Cùng số căn với P-404 nhưng gõ khác cách"]),
    # 5) LỖI - thiếu địa chỉ
    ("error", ["Trống ở ngay", "Chưa KS", "", "", "P. 13", "Q. Bình Thạnh cũ", "P-KHONGDIA",
               "Studio", 5000000, 5000000, "2 Ng/2 Xe", "Không", "Không pet", "⭐⭐⭐", "",
               "", "", "Dòng thiếu số nhà và tên đường"]),
    # 6) MỚI - tòa nhà mới
    ("new", ["Sắp trống", "Chưa KS", "210", "Hoàng Văn Thụ", "P. 15", "Q. Phú Nhuận cũ",
             "P-210HVT", "Duplex", 9500000, 9500000, "3 Ng/2 Xe", "Không", "Không pet",
             "⭐⭐⭐⭐⭐ Duplex mặt tiền", "0911111111", "zalo.me/g/tunguyenland",
             "drive.google.com/folder/p-210hvt", "Nội thất: duplex full"]),
]

BUILDING_HEADERS = ["STT", "Số Nhà", "Tên Đường", "Phường", "Quận / Khu Vực Cũ",
                    "Chủ Tòa / Admin QLH", "Số Điện Thoại", "Link Group Zalo", "Quy Định Xe Điện",
                    "Quy Định Pet", "Chính Sách Hoa Hồng Sale"]


def build(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Kho Hàng Phòng Trống"
    ws.cell(row=2, column=2, value="KHO HÀNG PHÒNG TRỐNG - FILE KIỂM THỬ IMPORT")
    ws.cell(row=3, column=2, value="Chứa dòng mới / trùng hoàn toàn / có thay đổi / nghi ngờ trùng / lỗi")
    for j, h in enumerate(HEADERS, start=2):
        ws.cell(row=5, column=j, value=h)
    for i, (_, row) in enumerate(ROWS, start=6):
        ws.cell(row=i, column=2, value=i - 5)          # STT
        for j, v in enumerate(row, start=3):
            ws.cell(row=i, column=j, value=v)

    ws2 = wb.create_sheet("Danh Mục Địa Điểm & Chủ Nhà")
    for j, h in enumerate(BUILDING_HEADERS, start=2):
        ws2.cell(row=5, column=j, value=h)
    ws2.cell(row=6, column=2, value=1)
    for j, v in enumerate(["12", "Nguyễn Văn C", "P. 14", "Q. Phú Nhuận cũ", "Chủ Nhà / Admin Tòa",
                           "0900000001", "zalo.me/g/tunguyenland", "Có sạc", "Cho nuôi Mèo",
                           "HH Sale 1 tháng tiền thuê (HĐ 12T)"], start=3):
        ws2.cell(row=6, column=j, value=v)

    ws3 = wb.create_sheet("Thống Kê Nhanh")
    ws3.cell(row=2, column=2, value="BÁO CÁO NHANH KHO PHÒNG TRỐNG")

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    p = build(ROOT / "samples" / "import_them_mau.xlsx")
    print(f"Đã tạo: {p} ({len(ROWS)} dòng: "
          f"new={sum(1 for k, _ in ROWS if k == 'new')}, "
          f"duplicate={sum(1 for k, _ in ROWS if k == 'duplicate')}, "
          f"changed={sum(1 for k, _ in ROWS if k == 'changed')}, "
          f"suspect={sum(1 for k, _ in ROWS if k == 'suspect')}, "
          f"error={sum(1 for k, _ in ROWS if k == 'error')})")
