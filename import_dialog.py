# -*- coding: utf-8 -*-
"""import_dialog.py - Hộp thoại Nhập Excel: chọn file -> ánh xạ cột -> xem trước phân loại -> áp dụng.

5 loại dòng: new / duplicate / changed / suspect / error (màu theo KIND_COLOR).
KHÔNG BAO GHI DÙNG khi người dùng chưa xác nhận: mặc định chỉ tick "Dữ liệu mới".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QTableView, QVBoxLayout, QWidget,
)

import text_utils as tu
from excel_import import (KIND_COLOR, KIND_LABEL, ParsedFile, build_plan,
                          read_workbook, save_stats_formulas)
from models import ROOM_COLUMNS


# ------------------------------------------------------------------ model ánh xạ cột
class MappingModel(QAbstractTableModel):
    """2 cột: Tên trường phần mềm | Cột Excel tương ứng (sửa được)."""

    def __init__(self, headers: List[str], mapping: Dict[str, int], parent=None):
        super().__init__(parent)
        self.headers = headers
        self.mapping = dict(mapping)
        self.order = [c["name"] for c in ROOM_COLUMNS]
        self.label = {c["name"]: c["header"] for c in ROOM_COLUMNS}
        self.required = {"house_number", "street"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.order)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ["Trường dữ liệu", "Cột Excel tương ứng", "Bắt buộc"][section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 1:
            f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        name = self.order[index.row()]
        col = index.column()
        if col == 0:
            if role == Qt.DisplayRole:
                return self.label[name]
            if role == Qt.ForegroundRole and name in self.required and name not in self.mapping:
                from PySide6.QtGui import QColor
                return QColor("#DC2626")
            return None
        if col == 1:
            if role == Qt.DisplayRole:
                i = self.mapping.get(name)
                if i is None:
                    return "— (không ghép) —"
                return self.headers[i]
            if role == Qt.EditRole:
                return self.mapping.get(name, -1)
            return None
        if col == 2 and role == Qt.DisplayRole:
            return "⭐" if name in self.required else ""
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != 1 or not index.isValid():
            return False
        name = self.order[index.row()]
        v = int(value)
        # giải phóng cột đang gán cho trường khác
        if v >= 0:
            for k, i in list(self.mapping.items()):
                if i == v and k != name:
                    del self.mapping[k]
            self.mapping[name] = v
        else:
            self.mapping.pop(name, None)
        self.dataChanged.emit(index, index)
        return True

    def combo_items(self) -> List[str]:
        return ["— (không ghép) —"] + list(self.headers)


# ------------------------------------------------------------------ delegate chọn cột
class ColumnDelegate:
    """Bấm đúp -> chọn cột từ QComboBox (không cần thư viện giao diện bổ sung)."""

    @staticmethod
    def edit(model: MappingModel, index: QModelIndex, widget) -> None:
        from PySide6.QtWidgets import QInputDialog
        items = model.combo_items()
        cur = model.data(index, Qt.EditRole)
        cur = int(cur) + 1 if cur is not None and int(cur) >= 0 else 0
        item, ok = QInputDialog.getItem(widget, "Chọn cột Excel",
                                        f"Trường: {model.label[model.order[index.row()]]}",
                                        items, cur, False)
        if ok:
            model.setData(index, items.index(item) - 1)


# ------------------------------------------------------------------ model xem trước
class PreviewModel(QAbstractTableModel):
    COLS = ["Loại", "Dòng", "Mã phòng", "Địa chỉ", "Số căn", "Giá", "Trạng thái", "Lý do"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Any] = []

    def set_items(self, items: List[Any]):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLS[section]
        return None

    def item_at(self, row):
        return self.items[row] if 0 <= row < len(self.items) else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        p = it.payload
        col = self.COLS[index.column()]
        if role == Qt.ForegroundRole and col == "Loại":
            from PySide6.QtGui import QColor
            return QColor(KIND_COLOR.get(it.kind, "#000000"))
        if role == Qt.BackgroundRole:
            from PySide6.QtGui import QColor
            alpha = {"new": 0x00, "duplicate": 0x00, "changed": 0x00,
                     "suspect": 0x14, "error": 0x14}.get(it.kind, 0)
            if alpha:
                return QColor(KIND_COLOR.get(it.kind, "#000000").lstrip("#") + f"{alpha:02X}")
            return None
        if role == Qt.FontRole and col == "Loại":
            from PySide6.QtGui import QFont
            f = QFont()
            f.setBold(True)
            return f
        if role != Qt.DisplayRole:
            return None
        addr = tu.building_display(p.get("house_number"), p.get("street"),
                                   p.get("ward"), p.get("district"))
        vals = {
            "Loại": KIND_LABEL.get(it.kind, it.kind),
            "Dòng": it.excel_row,
            "Mã phòng": p.get("room_code") or "",
            "Địa chỉ": addr,
            "Số căn": p.get("unit_code") or "",
            "Giá": tu.format_money(p.get("price") or 0),
            "Trạng thái": p.get("status_text") or "",
            "Lý do": it.reason,
        }
        return vals.get(col, "")


# ------------------------------------------------------------------ hộp thoại
class ImportDialog(QDialog):
    imported = Signal(dict)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.parsed: Optional[ParsedFile] = None
        self.plan = None
        self.setWindowTitle("Nhập dữ liệu từ Excel")
        self.setMinimumSize(1100, 700)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(14, 12, 14, 10)
        self.layout().setSpacing(9)

        self._build_top()
        self._build_body()
        self._build_bottom()

    # ------------------------------------------------------------------ UI
    def _build_top(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_browse = QPushButton("📁 Chọn file Excel...")
        self.btn_browse.setObjectName("Primary")
        self.btn_browse.clicked.connect(self._choose_file)
        row.addWidget(self.btn_browse)
        self.lbl_file = QLabel("Chưa chọn file")
        self.lbl_file.setObjectName("Muted")
        row.addWidget(self.lbl_file, 1)
        self.btn_reload = QPushButton("🔄 Đọc lại")
        self.btn_reload.clicked.connect(self._reload)
        row.addWidget(self.btn_reload)
        self.layout().addLayout(row)

        hint = QLabel(
            "Cách dùng: chọn file → kiểm tra ÁNH XẠ CỘT (bấm đúp ô cột Excel) → "
            "xem trước kết quả phân loại → tick loại cần nhập → bấm Áp dụng. "
            "Hệ thống <b>không tự ghi đè</b> dữ liệu cũ khi chưa có xác nhận.")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setObjectName("Muted")
        self.layout().addWidget(hint)

    def _build_body(self):
        split = QSplitter(Qt.Horizontal)

        # --- bảng ánh xạ ---
        left = QFrame()
        left.setObjectName("Card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 10, 12, 10)
        t1 = QLabel("Ánh xạ cột Excel")
        t1.setObjectName("SectionTitle")
        ll.addWidget(t1)
        self.lbl_sheet = QLabel("")
        self.lbl_sheet.setObjectName("Muted")
        ll.addWidget(self.lbl_sheet)
        self.map_model = MappingModel([], {})
        self.map_table = QTableView()
        self.map_table.setModel(self.map_model)
        self.map_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.doubleClicked.connect(self._edit_mapping)
        ll.addWidget(self.map_table, 1)
        left.setMinimumWidth(380)
        split.addWidget(left)

        # --- bảng xem trước ---
        right = QFrame()
        right.setObjectName("Card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 10, 12, 10)
        t2 = QLabel("Xem trước kết quả phân loại")
        t2.setObjectName("SectionTitle")
        rl.addWidget(t2)
        self.counts_label = QLabel("Chưa có dữ liệu")
        self.counts_label.setTextFormat(Qt.RichText)
        rl.addWidget(self.counts_label)
        self.prev_model = PreviewModel()
        self.prev_table = QTableView()
        self.prev_table.setModel(self.prev_model)
        self.prev_table.setAlternatingRowColors(True)
        self.prev_table.verticalHeader().setVisible(False)
        self.prev_table.setSelectionBehavior(QTableView.SelectRows)
        self.prev_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.prev_table.setColumnWidth(0, 110)
        self.prev_table.setColumnWidth(1, 55)
        self.prev_table.setColumnWidth(2, 100)
        self.prev_table.setColumnWidth(3, 240)
        rl.addWidget(self.prev_table, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        self.layout().addWidget(split, 1)

    def _build_bottom(self):
        box = QFrame()
        box.setObjectName("Toolbar")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 9, 12, 9)
        bl.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(14)
        lbl = QLabel("<b>Chọn loại dòng cần áp dụng:</b>")
        row1.addWidget(lbl)
        self.kind_checks: Dict[str, QCheckBox] = {}
        for kind in ("new", "duplicate", "changed", "suspect", "error"):
            cb = QCheckBox(f"{KIND_LABEL[kind]}")
            cb.setProperty("kind", kind)
            # CHỈ tick mặc định "dữ liệu mới" -> không bao giờ ghi đè khi chưa xác nhận
            cb.setChecked(kind == "new")
            if kind in ("duplicate", "error"):
                cb.setEnabled(False)
                cb.setToolTip("Không bao giờ tự ghi đè / tự sửa dòng lỗi - hãy sửa file Excel.")
            self.kind_checks[kind] = cb
            row1.addWidget(cb)
        row1.addStretch(1)
        bl.addLayout(row1)

        self.lbl_result = QLabel("")
        self.lbl_result.setTextFormat(Qt.RichText)
        bl.addWidget(self.lbl_result)

        bb = QDialogButtonBox()
        self.btn_apply = bb.addButton("✅ Áp dụng vào kho", QDialogButtonBox.AcceptRole)
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.setEnabled(False)
        bb.addButton("Đóng", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.accept)
        row2 = QHBoxLayout()
        row2.addWidget(bb, 1)
        self.layout().addWidget(box)
        box.layout().addLayout(row2)

    # ------------------------------------------------------------------ logic
    def _choose_file(self):
        start = str(self.mgr.settings.get("last_import_dir") or "") or str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file Excel", start,
            "Excel (*.xlsx *.xlsm);;All files (*)")
        if not path:
            return
        self.mgr.settings.set("last_import_dir", str(Path(path).parent))
        self._load(path)

    def load_file(self, path: str):
        self._load(path)

    def _load(self, path: str):
        self.path = path
        self._reload()

    def _reload(self):
        path = getattr(self, "path", None)
        if not path:
            return
        self.lbl_file.setText(path)
        self.parsed = read_workbook(path)
        if self.parsed.error:
            QMessageBox.critical(self, "Không đọc được file", self.parsed.error)
            return
        if self.parsed.stats_formulas:
            save_stats_formulas(self.parsed.stats_formulas, self.parsed.stats_sheet)
        if self.parsed.rooms is None:
            QMessageBox.warning(
                self, "Không tìm thấy sheet phòng",
                "Không nhận diện được sheet danh sách phòng.\n"
                "Cần có các cột như: Trạng Thái, Số Nhà, Tên Đường, Mã Phòng, Giá Thuê...")
            return
        t = self.parsed.rooms
        self.lbl_sheet.setText(
            f"Sheet: «{t.title}» · dòng tiêu đề: {t.header_row} · "
            f"{len(t.headers)} cột · {len(t.rows)} dòng dữ liệu")
        # map model
        self.map_model.beginResetModel()
        self.map_model.headers = list(t.headers)
        self.map_model.mapping = dict(t.mapping)
        self.map_model.endResetModel()

        self._build_plan()

    def _edit_mapping(self, index: QModelIndex):
        if index.column() != 1:
            index = index.sibling(index.row(), 1)
        ColumnDelegate.edit(self.map_model, index, self)
        # áp mapping mới vào table rồi phân loại lại
        if self.parsed and self.parsed.rooms:
            self.parsed.rooms.mapping = dict(self.map_model.mapping)
            self._build_plan()

    def _build_plan(self):
        if not self.parsed:
            return
        self.plan = build_plan(self.parsed, self.mgr.checker, self.mgr.db)
        if self.plan.error:
            QMessageBox.warning(self, "Không phân tích được", self.plan.error)
            self.plan = None
            return
        counts = self.plan.counts()
        parts = []
        for kind in ("new", "duplicate", "changed", "suspect", "error"):
            n = counts.get(kind, 0)
            parts.append(f"<b style='color:{KIND_COLOR[kind]}'>{KIND_LABEL[kind]}: {n}</b>")
        self.counts_label.setText(f"Tổng {counts['total']} dòng &nbsp;|&nbsp; " + " &nbsp;·&nbsp; ".join(parts))
        self.prev_model.set_items(self.plan.items)
        self.btn_apply.setEnabled(bool(self.plan.items))
        # gợi ý tick an toàn
        for kind, cb in self.kind_checks.items():
            if kind in ("duplicate", "error"):
                cb.setChecked(False)
                cb.setEnabled(False)
            else:
                cb.setEnabled(counts.get(kind, 0) > 0)
                cb.setChecked(kind == "new" and counts.get(kind, 0) > 0)

    def _apply(self):
        if not self.plan:
            return
        kinds = [k for k, cb in self.kind_checks.items() if cb.isChecked()]
        if not kinds:
            QMessageBox.information(self, "Chưa chọn loại",
                                    "Hãy tick ít nhất 1 loại dòng cần áp dụng.")
            return
        counts_sel = sum(self.plan.counts().get(k, 0) for k in kinds)
        warn = [k for k in kinds if k in ("changed", "suspect") ]
        msg = f"Áp dụng {counts_sel} dòng với các loại: {', '.join(KIND_LABEL[k] for k in kinds)}?"
        if "changed" in kinds:
            msg += "\n\n⚠ Dòng 'Có thay đổi' sẽ CẬP NHẬT bản ghi hiện có (theo trường khác biệt)."
        if "suspect" in kinds:
            msg += "\n⚠ Dòng 'Nghi ngờ trùng' sẽ được thêm với cờ xác minh."
        if QMessageBox.question(self, "Xác nhận nhập", msg) != QMessageBox.Yes:
            return
        try:
            res = self.mgr.import_apply(self.plan, kinds)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi nhập", str(e))
            return
        self.lbl_result.setText(
            f"<b style='color:#16A34A;'>✓ Hoàn tất:</b> thêm {res.get('new', 0)} · "
            f"cập nhật {res.get('changed', 0)} · bỏ qua trùng {res.get('duplicate', 0)} · "
            f"suspect {res.get('suspect', 0)} · lỗi {res.get('error', 0) + res.get('failed', 0)} · "
            f"giữ nguyên {res.get('skipped', 0)}")
        self.imported.emit(res)
        self.mgr.emit("stats_changed")
