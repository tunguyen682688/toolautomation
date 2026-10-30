# -*- coding: utf-8 -*-
"""export_dialog.py - Hộp thoại Xuất Excel: giữ nguyên cấu trúc 3 sheet + công thức Thống Kê gốc."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

import text_utils as tu
from excel_export import export_template, export_workbook
from excel_import import load_stats_formulas
from models import RoomFilter, RoomStatus


class ExportDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle("Xuất dữ liệu ra Excel")
        self.setMinimumWidth(620)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(16, 14, 16, 12)
        self.layout().setSpacing(10)

        info = QLabel(
            "File xuất giữ <b>đúng cấu trúc gốc</b>: 3 sheet, tiêu đề ở dòng 5, "
            "công thức <i>COUNTIF/COUNTIFS</i> của sheet Thống Kê được <b>giữ nguyên</b>, "
            "và thêm 2 cột <b>Số Căn / Tầng</b> ở CUỐI bảng (không dịch chuyển cột cũ) "
            "để nhập lại vẫn nhận đúng khoá nhận diện.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setObjectName("Muted")
        self.layout().addWidget(info)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        row = QHBoxLayout()
        start = str(self.mgr.settings.get("last_export_dir") or "") or str(Path.home() / "Downloads")
        self.ed_path = QLineEdit(str(Path(start) / "Kho_Phong_Xuat.xlsx"))
        btn = QPushButton("Chọn vị trí...")
        btn.clicked.connect(self._pick)
        row.addWidget(self.ed_path, 1)
        row.addWidget(btn)
        form.addRow("File xuất:", row)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Tất cả trạng thái", None)
        for k in RoomStatus.ORDER:
            self.cmb_status.addItem(f"● {RoomStatus.label(k)}", k)
        form.addRow("Lọc trạng thái:", self.cmb_status)

        self.cmb_building = QComboBox()
        self.cmb_building.addItem("Tất cả tòa nhà", None)
        for b in self.mgr.buildings():
            self.cmb_building.addItem(b.get("display", b.get("code", "")), b["id"])
        form.addRow("Lọc tòa nhà:", self.cmb_building)

        self.chk_deleted = QCheckBox("Bao gồm cả phòng đã xóa mềm")
        form.addRow("", self.chk_deleted)
        self.layout().addLayout(form)

        self.btn_template = QPushButton("📄 Xuất file MẪU trống (điền tay)")
        self.btn_template.clicked.connect(self._export_template)
        self.layout().addWidget(self.btn_template)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setTextFormat(Qt.RichText)
        self.layout().addWidget(self.lbl_result)

        preview = QTextEdit()
        preview.setReadOnly(True)
        self.preview = preview
        self.layout().addWidget(preview, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_export = bb.addButton("📤 Xuất Excel", QDialogButtonBox.AcceptRole)
        self.btn_export.setObjectName("Primary")
        bb.accepted.connect(self._export)
        bb.rejected.connect(self.reject)
        self.layout().addWidget(bb)

        self._update_preview()

    # ------------------------------------------------------------------
    def _pick(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất Excel", self.ed_path.text(),
            "Excel (*.xlsx)")
        if path:
            self.ed_path.setText(path)

    def _collect(self):
        statuses = [self.cmb_status.currentData()] if self.cmb_status.currentData() else None
        bid = self.cmb_building.currentData()
        f = RoomFilter(building_id=bid, statuses=statuses,
                       include_deleted=self.chk_deleted.isChecked())
        rooms = self.mgr.rooms("", f)
        buildings = self.mgr.buildings()
        return rooms, buildings

    def _update_preview(self):
        rooms, _ = self._collect()
        st: Dict[str, int] = {}
        for r in rooms:
            st[r.get("status", "")] = st.get(r.get("status", ""), 0) + 1
        lines = [f"<b>Số dòng sẽ xuất: {len(rooms)}</b>"]
        for k in RoomStatus.ORDER:
            if st.get(k):
                lines.append(f"· {RoomStatus.label(k)}: {st[k]}")
        total_price = sum(int(r.get("price") or 0) for r in rooms)
        avg = total_price // len(rooms) if rooms else 0
        lines.append(f"· Giá TB: {tu.format_money(avg)} ₫")
        self.preview.setHtml("<br>".join(lines))

    def _export_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu file mẫu", "Mau_Nhap_Phong.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            export_template(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không tạo được file mẫu", str(e))
            return
        self.lbl_result.setText(f"<span style='color:#16A34A;'>✓ Đã tạo file mẫu: {path}</span>")

    def _export(self):
        path = self.ed_path.text().strip()
        if not path.lower().endswith((".xlsx", ".xlsm")):
            path += ".xlsx"
        rooms, buildings = self._collect()
        if not rooms:
            QMessageBox.information(self, "Không có dữ liệu",
                                    "Bộ lọc hiện tại không có phòng nào để xuất.")
            return
        formulas = load_stats_formulas().get("formulas", {})
        try:
            self.mgr.settings.set("last_export_dir", str(Path(path).parent))
            export_workbook(path, rooms, buildings, self.mgr.stats(),
                            stats_formulas=formulas,
                            include_deleted=self.chk_deleted.isChecked())
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Xuất thất bại", str(e))
            return
        self.lbl_result.setText(
            f"<span style='color:#16A34A;'>✓ Đã xuất {len(rooms)} phòng "
            f"({len(buildings)} tòa) → {path}</span>")
        self._update_preview()
