# -*- coding: utf-8 -*-
"""grouped_table.py - Model bảng Qt có HÀNG NHÓM (phân cụm) xen giữa dòng dữ liệu.

Dùng cho CẢ HAI danh sách Phòng và Tòa nhà: mỗi PHƯỜNG là 1 hàng tiêu đề
"📍 P.13 (Bình Thạnh)   ·   24 phòng · 6 trống" nằm trên đầu cụm dòng của phường đó.

Cách hoạt động:
- `rows`     = dữ liệu THUẦN (không đổi so với bảng thường) - test đọc trực tiếp.
- `_disp`    = danh sách hiển thị:  ("g", GroupEntry) | ("r", index vào rows).
- Hàng nhóm: flags chỉ bật Enabled (không chọn/sửa), span tràn hết chiều ngang,
  delegate tự vẽ nền + viền trái accent + meta căn phải.
- Khi bật phân cụm, `rows` được stable-sort theo khoá phường -> giữ nguyên
  thứ tự relevance của kết quả tìm kiếm trong từng nhóm.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

import theme


class GroupEntry:
    """Tiêu đề 1 nhóm (phường)."""
    __slots__ = ("title", "meta")

    def __init__(self, title: str, meta: str = ""):
        self.title = title
        self.meta = meta


class GroupedTableModel(QAbstractTableModel):
    """QAbstractTableModel có hàng nhóm phân cụm. Lớp con cung cấp columns()/cell_data()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[Dict[str, Any]] = []
        self._disp: List[Tuple[str, Any]] = []
        self._grouped: bool = True

    # ============================ API cho lớp con ============================
    def columns(self) -> List[Tuple[str, str, int]]:
        """[(key, tiêu đề, chiều rộng), ...]"""
        raise NotImplementedError

    def cell_data(self, row: Dict[str, Any], col_key: str, role: int):
        """Nội dung ô dữ liệu (lớp con thay thế toàn bộ logic hiển thị cũ)."""
        return None

    def cell_flags(self, col_key: str) -> int:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def cell_set(self, row: Dict[str, Any], col_key: str, value: Any) -> bool:
        return False

    def right_align_keys(self) -> set:
        return set()

    def center_align_keys(self) -> set:
        return set()

    # phân cụm ------------------------------------------------------------
    def group_key_of(self, row: Dict[str, Any]) -> str:
        return ""

    def group_title_of(self, key: str, rows: List[Dict[str, Any]]) -> str:
        return key

    def group_meta_of(self, key: str, rows: List[Dict[str, Any]]) -> str:
        return ""

    def group_sort_key(self, key: str) -> Any:
        """Khóa sắp thứ tự nhóm. Mặc định: số -> theo số, chữ -> A->Z."""
        return (0, int(key), "") if key.isdigit() else (1, 0, key.lower())

    # ============================ nạp / phân cụm ============================
    def set_rows(self, rows: List[Dict[str, Any]]):
        self.beginResetModel()
        self.rows = list(rows)
        self._rebuild()
        self.endResetModel()

    def set_grouped(self, on: bool):
        on = bool(on)
        if on == self._grouped:
            return
        self.beginResetModel()
        self._grouped = on
        self._rebuild()
        self.endResetModel()

    def is_grouped(self) -> bool:
        return self._grouped

    def _rebuild(self):
        self._disp = []
        n = len(self.rows)
        if not n:
            return
        if not self._grouped:
            self._disp = [("r", i) for i in range(n)]
            return
        # stable-sort theo phường -> các dòng cùng phường kề nhau,
        # thứ tự bên trong nhóm (relevance khi tìm) được GIỮ NGUYÊN.
        self.rows.sort(key=lambda r: self.group_sort_key(self.group_key_of(r)))
        i = 0
        while i < n:
            key = self.group_key_of(self.rows[i])
            j = i
            while j < n and self.group_key_of(self.rows[j]) == key:
                j += 1
            chunk = self.rows[i:j]
            self._disp.append(("g", GroupEntry(
                self.group_title_of(key, chunk), self.group_meta_of(key, chunk))))
            self._disp.extend(("r", x) for x in range(i, j))
            i = j

    # ============================ truy vấn ============================
    def data_row_count(self) -> int:
        """Số dòng DỮ LIỆU thật (không tính hàng tiêu đề nhóm)."""
        return len(self.rows)

    def is_group_row(self, view_row: int) -> bool:
        return 0 <= view_row < len(self._disp) and self._disp[view_row][0] == "g"

    def group_at(self, view_row: int) -> Optional[GroupEntry]:
        if self.is_group_row(view_row):
            return self._disp[view_row][1]
        return None

    def data_row_at(self, view_row: int) -> Optional[Dict[str, Any]]:
        """Dict dữ liệu tại dòng hiển thị (None nếu là hàng nhóm / ngoài phạm vi)."""
        if 0 <= view_row < len(self._disp):
            kind, val = self._disp[view_row]
            if kind == "r":
                return self.rows[val]
        return None

    # ============================ QAbstractTableModel ============================
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._disp)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns())

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        cols = self.columns()
        if not 0 <= section < len(cols):
            return None
        key = cols[section][0]
        if role == Qt.DisplayRole:
            return cols[section][1]
        if role == Qt.TextAlignmentRole:
            if key in self.right_align_keys():
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if key in self.center_align_keys():
                return int(Qt.AlignHCenter | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if self.is_group_row(index.row()):
            return Qt.ItemIsEnabled          # hàng nhóm: thấy được, không chọn/sửa
        return self.cell_flags(self.columns()[index.column()][0])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if self.is_group_row(index.row()):
            if index.column() != 0:
                return None
            g: GroupEntry = self._disp[index.row()][1]
            if role == Qt.DisplayRole:
                return g.title
            if role == Qt.ToolTipRole:
                return g.meta or g.title
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return None
        row = self.rows[self._disp[index.row()][1]]
        return self.cell_data(row, self.columns()[index.column()][0], role)

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid() or self.is_group_row(index.row()):
            return False
        row = self.rows[self._disp[index.row()][1]]
        return bool(self.cell_set(row, self.columns()[index.column()][0], value))

# ================================================================== delegate
def paint_group_row(painter, option: QStyleOptionViewItem, index) -> bool:
    """Vẽ hàng tiêu đề nhóm. Trả False nếu index không phải hàng nhóm.

    CHỈ vẽ ở cột 0 (nền phủ FULL chiều ngang viewport), các cột còn lại
    của cùng hàng nhóm delegate trả về True để không vẽ đè -> chữ không lặp.
    Viền trái accent, tiêu đề đậm bên trái + meta nhạt căn phải.
    """
    model = index.model()
    if not hasattr(model, "is_group_row") or not model.is_group_row(index.row()):
        return False
    if index.column() != 0:
        return True                      # hàng nhóm - cột khác: bỏ qua (đã vẽ ở cột 0)
    entry = model.group_at(index.row())
    text = str(index.data(Qt.DisplayRole) or "")
    meta = str(entry.meta if entry else "")
    rect: QRect = option.rect
    widget = option.widget
    width = max(rect.width(), int(widget.viewport().width()) if widget is not None else 0)

    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(theme.c("card2")))
    painter.drawRect(QRect(rect.left(), rect.top(), width, rect.height()))
    painter.setBrush(QColor(theme.c("accent")))
    painter.drawRect(QRect(rect.left(), rect.top() + 5, 3, max(1, rect.height() - 10)))

    f = QFont(option.font)
    f.setBold(True)
    painter.setFont(f)
    painter.setPen(QColor(theme.c("text")))
    painter.drawText(QRect(rect.left() + 14, rect.top(), max(40, width - 18), rect.height()),
                     int(Qt.AlignLeft | Qt.AlignVCenter), text)
    if meta:
        painter.setFont(option.font)
        painter.setPen(QColor(theme.c("text3")))
        painter.drawText(QRect(rect.left(), rect.top(), max(0, width - 16), rect.height()),
                         int(Qt.AlignRight | Qt.AlignVCenter), meta)
    painter.restore()
    return True


def group_row_size_hint(option: QStyleOptionViewItem, index, height: int = 30):
    """Chiều cao hàng nhóm (delegate gọi khi index là hàng nhóm)."""
    model = index.model()
    if hasattr(model, "is_group_row") and model.is_group_row(index.row()):
        from PySide6.QtCore import QSize
        return QSize(option.rect.width(), height)
    return None
