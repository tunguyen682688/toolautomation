# -*- coding: utf-8 -*-
"""building_view.py - Trang Tòa nhà (phong cách Airtable/Linear).

Thiết kế:
- Thẻ tòa: mã + địa chỉ + avatar chủ nhà + thanh tỉ lệ phòng (trống/cọc/thuê/sắp trống)
  + hàng chỉ số + chip chính sách + nút hành động tròn.
- Tiêu đề khu vực: section header sạch (title + meta + đường kẻ mảnh), phường là chip nhỏ.
- Panel phải: header tòa + chỉ số nhanh + danh sách phòng + nút thao tác.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QLayout, QListView,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

import text_utils as tu
from google_drive import open_drive, open_phone, open_zalo
from grouped_table import GroupedTableModel, group_row_size_hint, paint_group_row
from models import RoomFilter
import theme
from theme import C_ACCENT, C_BORDER, C_OK, C_ORANGE, C_WARN, C_DANGER, C_MUTED, \
    status_bg, status_color, status_label


# ------------------------------------------------------------------ helper viz
def _owner_initials(name: str) -> str:
    """Chữ cái đầu chủ nhà (2 ký tự) cho avatar tròn."""
    parts = [w for w in str(name or "").split() if w]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _owner_color(name: str) -> str:
    """Màu avatar ổn định theo tên chủ nhà (bảng màu pastel dễ nhìn 2 chế độ)."""
    pal = ["#2563EB", "#7C3AED", "#0D9488", "#DB2777", "#EA580C", "#0891B2", "#65A30D"]
    h = sum(ord(ch) for ch in str(name or "?"))
    return pal[h % len(pal)]


class OccupancyBar(QWidget):
    """Thanh tỉ lệ phòng của tòa: trống | cọc/giữ | thuê | sắp trống (vẽ bo tròn)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._counts: List[int] = [0, 0, 0, 0]

    def set_counts(self, vacant: int, deposit: int, rented: int, soon: int):
        self._counts = [int(vacant), int(deposit), int(rented), int(soon)]
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.c("track")))
        p.drawRoundedRect(r, 4, 4)
        total = sum(self._counts)
        if total <= 0:
            return
        colors = [theme.c("ok"), theme.c("orange"), theme.c("danger"), theme.c("warn")]
        x = float(r.x())
        for count, color in zip(self._counts, colors):
            if count <= 0:
                continue
            w = r.width() * count / total
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, 0, max(4.0, w), r.height()), 4, 4)
            x += w


def _metric(value: Any, label: str, color: str) -> QWidget:
    """Ô chỉ số nhỏ: số lớn màu + nhãn nhỏ nhạt (dùng cho thẻ và panel)."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    num = QLabel(str(value))
    num.setStyleSheet(
        f"font-size:16px; font-weight:800; color:{color}; background:transparent;")
    lab = QLabel(label)
    lab.setStyleSheet(
        f"font-size:10.5px; font-weight:600; color:{theme.c('text3')}; background:transparent;")
    v.addWidget(num)
    v.addWidget(lab)
    return w


def _icon_btn(text: str, tip: str, slot) -> QToolButton:
    """Nút biểu tượng tròn nhỏ (gọi / Zalo / Drive / sửa)."""
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setObjectName("IconButton")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


# ------------------------------------------------------------------ layout tự bọc dòng
class FlowLayout(QLayout):
    """Layout bọc dòng: các thẻ tự xuống hàng như khối Lego (phù hợp lưới thẻ)."""

    def __init__(self, parent=None, hspacing: int = 12, vspacing: int = 12):
        super().__init__(parent)
        self._items: List[Any] = []
        self.hspacing, self.vspacing = hspacing, vspacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(2 * m.left(), 2 * m.top())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        lineheight = 0
        for item in self._items:
            wid = item.widget()
            space_x = self.hspacing
            space_y = self.vspacing
            nextx = x + item.sizeHint().width() + space_x
            if nextx - space_x > rect.right() and lineheight > 0:
                x = rect.x()
                y = y + lineheight + space_y
                nextx = x + item.sizeHint().width() + space_x
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nextx
            lineheight = max(lineheight, item.sizeHint().height())
        return y + lineheight - rect.y()


# ------------------------------------------------------------------ form tòa nhà
class BuildingForm(QDialog):
    """3 nhóm dữ liệu tòa: địa chỉ / chủ nhà / quy định (cuộn được, không bị tràn)."""

    def __init__(self, building: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sửa thông tin tòa nhà" if building else "Thêm tòa nhà mới")
        self.setMinimumWidth(620)
        self.setMinimumHeight(480)
        self.building = building or {}
        self.fields: Dict[str, QLineEdit] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 4, 0)
        inner.setSpacing(12)

        def add_group(num: str, title: str, rows: List[tuple]):
            box = QFrame()
            box.setObjectName("Card")
            gl = QVBoxLayout(box)
            gl.setContentsMargins(16, 12, 16, 14)
            gl.setSpacing(9)
            head = QHBoxLayout()
            head.setSpacing(9)
            badge = QLabel(num)
            badge.setFixedSize(24, 24)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background:{theme.c('accent_soft')}; color:{theme.c('accent_soft_text')};"
                " border-radius:12px; font-size:12px; font-weight:800;")
            head.addWidget(badge)
            t = QLabel(title)
            t.setStyleSheet(
                f"font-size:14px; font-weight:800; color:{theme.c('text')};"
                " background:transparent; letter-spacing:-0.2px;")
            head.addWidget(t)
            head.addStretch(1)
            gl.addLayout(head)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(9)
            for key, label in rows:
                ed = QLineEdit(str(self.building.get(key, "") or ""))
                ed.setPlaceholderText(label)
                self.fields[key] = ed
                form.addRow(label + ":", ed)
            gl.addLayout(form)
            inner.addWidget(box)

        add_group("1", "Địa chỉ tòa nhà", [
            ("house_number", "Số nhà"), ("street", "Tên đường"),
            ("ward", "Phường"), ("district", "Quận / Khu vực"),
        ])
        add_group("2", "Chủ nhà / Admin quản lý", [
            ("owner_name", "Chủ tòa / Admin"), ("phone", "Số điện thoại"),
            ("zalo_group", "Link Group Zalo"),
        ])
        add_group("3", "Quy định & hoa hồng", [
            ("ev_policy", "Quy định xe điện"), ("pet_policy", "Quy định thú cưng"),
            ("commission", "Chính sách hoa hồng sale"), ("notes", "Ghi chú khác"),
        ])
        inner.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def payload(self) -> Dict[str, Any]:
        return {k: ed.text().strip() for k, ed in self.fields.items()}


# ------------------------------------------------------------------ panel phòng nhanh bên phải (split view)
class RoomsInlinePanel(QFrame):
    """Hiển thị NGAY danh sách phòng của tòa đang chọn (inline, không nhảy trang)."""

    open_detail = Signal(str)        # room_id
    open_full_table = Signal(dict)   # filter dict -> mở trang Phòng đầy đủ
    edit_requested = Signal(str)     # building_id -> sửa tòa

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.building = None
        self.setObjectName("Card")
        self.setMinimumWidth(300)
        self.setMaximumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # ---------- header: avatar + tên tòa + owner ----------
        head = QHBoxLayout()
        head.setSpacing(10)
        self.avatar = QLabel("?")
        self.avatar.setFixedSize(38, 38)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            f"background:{theme.c('track')}; color:{theme.c('text2')};"
            " border-radius:19px; font-size:13px; font-weight:800;")
        head.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.lbl_title = QLabel("Chọn một tòa nhà")
        self.lbl_title.setStyleSheet(
            f"font-size:14.5px; font-weight:800; color:{theme.c('text')};"
            " background:transparent; letter-spacing:-0.2px;")
        self.lbl_title.setWordWrap(True)
        col.addWidget(self.lbl_title)
        self.lbl_sub = QLabel("Bấm thẻ tòa nhà bên trái để xem phòng.")
        self.lbl_sub.setStyleSheet(
            f"font-size:11.5px; color:{theme.c('text2')}; background:transparent;")
        self.lbl_sub.setWordWrap(True)
        col.addWidget(self.lbl_sub)
        head.addLayout(col, 1)
        self.btn_edit = _icon_btn("✏️", "Sửa thông tin tòa",
                                  lambda: self.edit_requested.emit(
                                      (self.building or {}).get("id", "")))
        self.btn_edit.setEnabled(False)
        head.addWidget(self.btn_edit)
        lay.addLayout(head)

        # ---------- 4 chỉ số nhanh ----------
        stats = QGridLayout()
        stats.setHorizontalSpacing(6)
        stats.setVerticalSpacing(6)
        self.m_total = _metric(0, "Tổng", theme.c("accent"))
        self.m_vacant = _metric(0, "Trống", theme.c("ok"))
        self.m_deposit = _metric(0, "Cọc/Giữ", theme.c("orange"))
        self.m_rented = _metric(0, "Thuê", theme.c("danger"))
        for i, m in enumerate((self.m_total, self.m_vacant, self.m_deposit, self.m_rented)):
            stats.addWidget(m, 0, i)
        lay.addLayout(stats)

        # ---------- danh sách phòng ----------
        self.model = QStandardItemModel()
        self.list = QListView()
        self.list.setObjectName("RoomList")
        self.list.setModel(self.model)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.clicked.connect(self._item_clicked)
        lay.addWidget(self.list, 1)

        self.btn_empty = QPushButton("Chưa có phòng nào")
        self.btn_empty.setEnabled(False)
        lay.addWidget(self.btn_empty)

        btn_open = QPushButton("📋  Mở bảng phòng đầy đủ")
        btn_open.setObjectName("Primary")
        btn_open.clicked.connect(self._open_full)
        lay.addWidget(btn_open)

    # ------------------------------------------------------------------
    def set_building(self, b: Dict[str, Any] | None):
        self.building = b
        self.model.clear()
        if not b:
            self.lbl_title.setText("Chọn một tòa nhà")
            self.lbl_sub.setText("Bấm thẻ tòa nhà bên trái để xem phòng.")
            self.avatar.setText("?")
            self.avatar.setStyleSheet(
                f"background:{theme.c('track')}; color:{theme.c('text2')};"
                " border-radius:19px; font-size:13px; font-weight:800;")
            self.btn_edit.setEnabled(False)
            for m in (self.m_total, self.m_vacant, self.m_deposit, self.m_rented):
                m.findChild(QLabel).setText("0")
            self.btn_empty.setEnabled(False)
            return
        self.btn_edit.setEnabled(True)
        owner = b.get("owner_name") or "—"
        self.avatar.setText(_owner_initials(owner))
        col = _owner_color(owner)
        self.avatar.setStyleSheet(
            f"background:{col}; color:white; border-radius:19px;"
            " font-size:13px; font-weight:800;")
        self.lbl_title.setText(str(b.get("display") or b.get("code") or "Tòa nhà"))
        self.lbl_sub.setText(f"👤 {owner} · 📞 {b.get('phone') or '—'}")

        rooms = self.mgr.rooms("", RoomFilter(building_id=b["id"])) or []
        cnt = {"vacant": 0, "rented": 0, "deposit": 0}
        for r in rooms:
            st = r.get("status", "")
            if st in cnt:
                cnt[st] += 1
        self.m_total.findChild(QLabel).setText(str(len(rooms)))
        self.m_vacant.findChild(QLabel).setText(str(cnt["vacant"]))
        self.m_deposit.findChild(QLabel).setText(str(cnt["deposit"]))
        self.m_rented.findChild(QLabel).setText(str(cnt["rented"]))

        if not rooms:
            self.lbl_sub.setText(self.lbl_sub.text() + " · chưa có phòng")
            self.btn_empty.setText("Thêm phòng đầu tiên")
            self.btn_empty.setEnabled(True)
            try:
                self.btn_empty.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass    # chưa từng kết nối
            self.btn_empty.clicked.connect(lambda: self.open_full_table.emit(
                {"filter": RoomFilter(building_id=b["id"]), "title": b.get("display", "")}))
            return
        self.btn_empty.hide()
        for r in rooms:
            st = r.get("status", "")
            loai = r.get("room_type") or "(chưa rõ)"
            item = QStandardItem(
                f"{r.get('room_code') or '(chưa có mã)'}   ·   {loai}   ·   "
                f"{tu.format_money(r.get('price'))}₫")
            item.setToolTip(f"{status_label(st)} · {r.get('address') or ''}")
            item.setData(st, Qt.UserRole)
            item.setForeground(QColor(status_color(st)))
            item.setEditable(False)
            self.model.appendRow(item)

    def _item_clicked(self, index: QModelIndex):
        if not self.building:
            return
        rooms = self.mgr.rooms("", RoomFilter(building_id=self.building["id"])) or []
        rid = rooms[index.row()]["id"] if index.row() < len(rooms) else ""
        if rid:
            self.open_detail.emit(rid)

    def _open_full(self):
        if not self.building:
            return
        self.open_full_table.emit({
            "filter": RoomFilter(building_id=self.building["id"]),
            "title": self.building.get("display", ""),
        })


# ------------------------------------------------------------------ thẻ tòa nhà
class BuildingCard(QFrame):
    """Thẻ tòa hiện đại: mã + địa chỉ, avatar chủ nhà, thanh tỉ lệ, chỉ số, hành động."""

    open_rooms = Signal(dict)       # filter
    edit_requested = Signal(str)

    def __init__(self, b: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setObjectName("BuildingCard")
        self.b = b
        self.setCursor(Qt.PointingHandCursor)
        # KÍCH THƯỚC ĐỀU NHAU -> thẻ xếp thành lưới cân đối trong FlowLayout
        self.setFixedWidth(368)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(9)

        # ---- hàng 1: mã + địa chỉ + nút sửa ----
        top = QHBoxLayout()
        top.setSpacing(9)
        code = QLabel(b.get('code', '') or '—')
        code.setStyleSheet(
            f"background:{theme.c('accent_soft')}; color:{theme.c('accent_soft_text')};"
            " border-radius:7px; padding:3px 8px; font-size:11.5px; font-weight:800;")
        top.addWidget(code)
        addr = QLabel(b.get('display', ''))
        addr.setStyleSheet(
            f"font-size:14.5px; font-weight:800; color:{theme.c('text')};"
            " background:transparent; letter-spacing:-0.2px;")
        addr.setWordWrap(True)
        top.addWidget(addr, 1)
        btn_edit = _icon_btn("✏️", "Sửa tòa nhà",
                             lambda: self.edit_requested.emit(self.b["id"]))
        top.addWidget(btn_edit)
        lay.addLayout(top)

        # ---- hàng 2: avatar chủ nhà + tên + SĐT ----
        owner_row = QHBoxLayout()
        owner_row.setSpacing(9)
        owner = str(b.get('owner_name') or "")
        av = QLabel(_owner_initials(owner))
        av.setFixedSize(26, 26)
        av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet(
            f"background:{_owner_color(owner)}; color:white; border-radius:13px;"
            " font-size:10.5px; font-weight:800;")
        owner_row.addWidget(av)
        oname = QLabel(owner or "Chưa rõ chủ nhà")
        oname.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text')}; background:transparent;")
        oname.setWordWrap(True)
        owner_row.addWidget(oname, 1)
        if b.get("phone"):
            btn_call = _icon_btn("📞", f"Gọi {b.get('phone')}",
                                 lambda: open_phone(self.b.get("phone", "")))
            owner_row.addWidget(btn_call)
        if b.get("zalo_group"):
            btn_zalo = _icon_btn("💬", "Mở Group Zalo",
                                 lambda: open_zalo(self.b.get("zalo_group", "")))
            owner_row.addWidget(btn_zalo)
        lay.addLayout(owner_row)

        # ---- hàng 3: thanh tỉ lệ phòng ----
        bar = OccupancyBar()
        bar.set_counts(b.get('rooms_vacant', 0), b.get('rooms_deposit', 0),
                       b.get('rooms_rented', 0), b.get('rooms_soon', 0))
        lay.addWidget(bar)

        # ---- hàng 4: chỉ số ----
        stats = QHBoxLayout()
        stats.setSpacing(0)
        metrics = [
            (b.get('rooms_total', 0), "Tổng", theme.c('text')),
            (b.get('rooms_vacant', 0), "Trống", theme.c('ok')),
            (b.get('rooms_deposit', 0), "Cọc/Giữ", theme.c('orange')),
            (b.get('rooms_rented', 0), "Thuê", theme.c('danger')),
            (b.get('rooms_soon', 0), "Sắp trống", theme.c('warn')),
        ]
        for i, (v, lab, col) in enumerate(metrics):
            if i:
                sep = QLabel("·")
                sep.setStyleSheet(
                    f"color:{theme.c('text3')}; background:transparent;"
                    " font-size:12px; padding:0 8px;")
                stats.addWidget(sep)
            stats.addWidget(_metric(v, lab, col))
        stats.addStretch(1)
        lay.addLayout(stats)

        # ---- hàng 5: chip chính sách ----
        pol_text = "  ·  ".join(
            s for s in (f"⚡ {b.get('ev_policy')}" if b.get('ev_policy') else "",
                        f"🐾 {b.get('pet_policy')}" if b.get('pet_policy') else "") if s)
        if pol_text:
            pol = QLabel(pol_text)
            pol.setStyleSheet(
                f"font-size:11px; color:{theme.c('text3')}; background:transparent;")
            pol.setWordWrap(True)
            lay.addWidget(pol)

        # ---- hàng 6: actions ----
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.c('border_soft')}; border:none;")
        lay.addWidget(line)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        btn_rooms = QPushButton("📋  Xem phòng")
        btn_rooms.setObjectName("SmallPrimary")
        btn_rooms.clicked.connect(self._open_rooms)
        actions.addWidget(btn_rooms)
        actions.addStretch(1)
        lay.addLayout(actions)

    def _open_rooms(self):
        self.open_rooms.emit({"building": self.b, "title": self.b.get("display", "")})

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._open_rooms()
        super().mousePressEvent(ev)


# ------------------------------------------------------------------ model bảng tòa
class BuildingTableModel(GroupedTableModel):
    """Bảng tòa nhà ảo hoá, phân cụm theo PHƯỜNG (cùng phường gộp chung)."""

    COLS = [
        ("code",        "Mã tòa",         80),
        ("display",     "Địa chỉ",       220),   # cột co giãn
        ("ward",        "Phường",         75),
        ("district",    "Quận / Khu vực", 110),
        ("owner_name",  "Chủ nhà",       130),
        ("phone",       "Số điện thoại",  115),
        ("rooms_total", "Tổng",           55),
        ("rooms_vacant","Trống",          60),
        ("rooms_deposit","Cọc",           55),
        ("rooms_rented","Thuê",           55),
        ("rooms_soon",  "Sắp trống",      80),
    ]

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager

    def columns(self):
        return self.COLS

    def right_align_keys(self):
        return {"rooms_total", "rooms_vacant", "rooms_deposit", "rooms_rented", "rooms_soon"}

    def center_align_keys(self):
        return {"code", "ward"}

    # --- phân cụm theo (quận, phường) để tránh trùng tên phường giữa 2 quận
    def group_key_of(self, row):
        return (tu.canon_district(row.get("district")) + "|" +
                tu.canon_ward(row.get("ward")))

    def group_sort_key(self, key):
        d, _, w = key.partition("|")
        wk = (0, int(w), "") if w.isdigit() else (1, 0, w)
        return (d, wk)

    def group_title_of(self, key, rows):
        d, _, w = key.partition("|")
        parts = []
        if w:
            raw_w = str(rows[0].get("ward") or "").strip()
            parts.append(f"📍 {raw_w or ('P.' + w)}")
        if d:
            raw_d = str(rows[0].get("district") or "").strip()
            parts.append(raw_d or d)
        return "  ·  ".join(parts) or "Chưa ghi địa chỉ"

    def group_meta_of(self, key, rows):
        n = len(rows)
        rooms = sum(int(b.get("rooms_total", 0) or 0) for b in rows)
        vac = sum(int(b.get("rooms_vacant", 0) or 0) for b in rows)
        return f"{n} tòa · {rooms} phòng · {vac} trống"

    def cell_flags(self, col_key):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def cell_data(self, b, key, role):
        if role == Qt.TextAlignmentRole:
            if key in self.right_align_keys():
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if key in self.center_align_keys():
                return int(Qt.AlignHCenter | Qt.AlignVCenter)
            return None
        if role == Qt.ForegroundRole:
            if key == "rooms_vacant":
                return QColor(theme.c("ok")) if int(b.get("rooms_vacant", 0) or 0) > 0 \
                    else QColor(theme.c("text3"))
            if key == "rooms_soon":
                return QColor(theme.c("warn")) if int(b.get("rooms_soon", 0) or 0) > 0 \
                    else QColor(theme.c("text3"))
            if key == "rooms_rented":
                return QColor(theme.c("danger")) if int(b.get("rooms_rented", 0) or 0) > 0 \
                    else QColor(theme.c("text3"))
            if key == "rooms_deposit":
                return QColor(theme.c("orange")) if int(b.get("rooms_deposit", 0) or 0) > 0 \
                    else QColor(theme.c("text3"))
            return None
        if role == Qt.ToolTipRole:
            return (f"{b.get('code','')} — {b.get('display','')}\n"
                    f"Chủ nhà: {b.get('owner_name','—')} · {b.get('phone','—')}\n"
                    f"Tổng {b.get('rooms_total',0)} · Trống {b.get('rooms_vacant',0)} · "
                    f"Cọc {b.get('rooms_deposit',0)} · Thuê {b.get('rooms_rented',0)} · "
                    f"Sắp trống {b.get('rooms_soon',0)}\n"
                    f"Double-click để mở bảng phòng của tòa này")
        if role != Qt.DisplayRole:
            return None
        v = b.get(key, "")
        if key == "rooms_soon":
            return str(int(v or 0))
        if key in ("rooms_total", "rooms_vacant", "rooms_deposit", "rooms_rented"):
            return str(int(v or 0))
        if key == "phone":
            return v or "—"
        if key == "ward":
            return v or "—"
        if key == "district":
            return v or "—"
        return str(v) if v not in (None, "") else ""


class BuildingDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if paint_group_row(painter, option, index):
            return                       # đã vẽ hàng tiêu đề nhóm phường
        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        gh = group_row_size_hint(option, index)
        if gh is not None:
            return gh
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 38))
        return s


# ------------------------------------------------------------------ trang tòa nhà
class BuildingPage(QWidget):
    building_selected = Signal(dict)   # click thẻ -> hiển thị phòng inline bên phải
    open_detail = Signal(str)          # click 1 phòng trong panel nhanh -> chi tiết
    open_rooms = Signal(dict)          # "Mở bảng đầy đủ" -> điều hướng trang Phòng

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._model = BuildingTableModel(manager, self)
        self._build_ui()
        self.building_selected.connect(lambda d: self.panel.set_building(d.get("building")))

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- thanh công cụ: lọc + tóm tắt + thêm ----
        filt = QFrame()
        filt.setObjectName("Toolbar")
        fl = QHBoxLayout(filt)
        fl.setContentsMargins(22, 10, 22, 10)
        fl.setSpacing(10)
        from PySide6.QtWidgets import QLineEdit as _QLE
        self.cmb_zone = QComboBox()
        self.cmb_zone.addItem("Tất cả khu vực", None)
        self.cmb_zone.currentIndexChanged.connect(self._zone_changed)
        self.cmb_zone.setToolTip("Phân cụm tòa nhà theo khu vực (quận)")
        fl.addWidget(self.cmb_zone)
        self.cmb_ward = QComboBox()
        self.cmb_ward.addItem("Tất cả phường", None)
        self.cmb_ward.currentIndexChanged.connect(self._apply_filter)
        self.cmb_ward.setToolTip("Lọc theo phường (thuộc khu vực đang chọn)")
        fl.addWidget(self.cmb_ward)

        self.chk_group = QCheckBox("🏘 Phân cụm phường")
        self.chk_group.setChecked(True)
        self.chk_group.setToolTip(
            "Gộp bảng tòa nhà theo từng PHƯỜNG: mỗi phường một hàng tiêu đề\n"
            "«📍 P.xx · quận · N tòa · M phòng · X trống».")
        self.chk_group.toggled.connect(self._apply_filter)
        fl.addWidget(self.chk_group)

        self.ed_search = _QLE()
        self.ed_search.setPlaceholderText("🔎 Địa chỉ / chủ nhà / SĐT...")
        self.ed_search.setMinimumWidth(220)
        self.ed_search.textChanged.connect(self._apply_filter)
        fl.addWidget(self.ed_search, 1)

        # tóm tắt nhanh: tòa · phòng · trống
        self.lbl_sum = QLabel("")
        self.lbl_sum.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent; padding:0 6px;")
        fl.addWidget(self.lbl_sum)

        self.btn_add = QPushButton("＋ Thêm tòa nhà")
        self.btn_add.setObjectName("Primary")
        self.btn_add.clicked.connect(self._add)
        fl.addWidget(self.btn_add)
        lay.addWidget(filt)

        # ---- SPLIT VIEW: trái thẻ tòa | phải danh sách phòng của tòa được chọn ----
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # trái: bảng tòa nhà (QTableView như trang Phòng)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setItemDelegate(BuildingDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, _, w) in enumerate(BuildingTableModel.COLS):
            self.table.setColumnWidth(i, w)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)     # cột địa chỉ co giãn
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.clicked.connect(self._on_row_clicked)
        ll.addWidget(self.table, 1)
        split.addWidget(left)

        # phải: panel phòng nhanh của tòa đang chọn
        self.panel = RoomsInlinePanel(self.mgr)
        self.panel.open_detail.connect(self.open_detail.emit)
        self.panel.open_full_table.connect(self.open_rooms.emit)
        self.panel.edit_requested.connect(self._edit)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([760, 360])
        # vùng lưới thẻ lọt trong khung padding - không dính mép cửa sổ (khớp toolbar 22px)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(22, 4, 22, 12)
        blay.addWidget(split)
        lay.addWidget(body, 1)

    # ------------------------------------------------------------------ header nhóm
    def _section_header(self, title: str, meta: str, level: int = 1) -> QWidget:
        """Tiêu đề khu vực (level 1: đậm + đường kẻ) hoặc phường (level 2: nhẹ)."""
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 10 if level == 1 else 2, 6, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:{15 if level == 1 else 12.5}px; font-weight:800;"
            f" color:{theme.c('text') if level == 1 else theme.c('text2')};"
            " background:transparent; letter-spacing:-0.2px;")
        row.addWidget(t)
        row.addStretch(1)
        m = QLabel(meta)
        m.setStyleSheet(
            f"font-size:{12 if level == 1 else 11.5}px; color:{theme.c('text3')};"
            " background:transparent; font-weight:600;")
        row.addWidget(m)
        v.addLayout(row)
        if level == 1:
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background:{theme.c('border_soft')}; border:none;")
            v.addWidget(line)
        return w

    # ------------------------------------------------------------------ dữ liệu
    def refresh(self, text: str = ""):
        text = text or self.ed_search.text()
        base = self.mgr.buildings(text=text)
        self._reload_zones(base)

        zone = self.cmb_zone.currentData()
        ward_sel = self.cmb_ward.currentData()
        buildings = base
        if zone:
            buildings = [b for b in base
                         if tu.canon_district(b.get("district")) == tu.canon_district(zone)]
        if ward_sel:
            buildings = [b for b in buildings
                         if tu.canon_ward(b.get("ward")) == tu.canon_ward(ward_sel)]

        # tóm tắt toolbar
        n_rooms = sum(int(b.get("rooms_total", 0) or 0) for b in buildings)
        n_vac = sum(int(b.get("rooms_vacant", 0) or 0) for b in buildings)
        self.lbl_sum.setText(f"{len(buildings)} tòa  ·  {n_rooms} phòng  ·  {n_vac} trống")

        # nạp vào bảng (phân cụm theo phường nếu đang bật)
        self._model.set_rows(buildings)
        self._model.set_grouped(self.chk_group.isChecked())

    # ------------------------------------------------------------------ chọn tòa
    def _on_row_clicked(self, idx):
        if not idx.isValid():
            return
        b = self._model.data_row_at(idx.row())
        if b:
            self.building_selected.emit({"building": b})

    def _on_double_click(self, idx):
        if not idx.isValid():
            return
        b = self._model.data_row_at(idx.row())
        if not b:
            return
        self.open_rooms.emit({
            "filter": RoomFilter(building_id=b["id"]),
            "title": b.get("display", "") or b.get("code", ""),
        })

    def _reload_zones(self, base_buildings: List[Dict[str, Any]]):
        """Cập nhật combobox khu vực + phường (phường phụ thuộc khu vực đang chọn)."""
        cur_zone = self.cmb_zone.currentData()
        cur_ward = self.cmb_ward.currentData()
        zones: Dict[str, str] = {}
        counts: Dict[str, int] = {}
        for b in base_buildings:
            raw = str(b.get("district") or "").strip()
            if not raw:
                continue
            k = tu.canon_district(raw)
            if not k:
                continue
            counts[k] = counts.get(k, 0) + 1
            if k not in zones or len(raw) < len(zones[k]):
                zones[k] = raw
        self.cmb_zone.blockSignals(True)
        self.cmb_zone.clear()
        self.cmb_zone.addItem("Tất cả khu vực", None)
        for k in sorted(zones, key=lambda x: -counts[x]):
            self.cmb_zone.addItem(f"📍 {zones[k]}  ({counts[k]} tòa)", zones[k])
        idx = self.cmb_zone.findData(cur_zone)
        self.cmb_zone.setCurrentIndex(max(0, idx))
        self.cmb_zone.blockSignals(False)

        # ---- phường (thuộc khu vực đang chọn)
        sel_zone = self.cmb_zone.currentData()
        wards: Dict[str, str] = {}
        wcounts: Dict[str, int] = {}
        for b in base_buildings:
            if sel_zone and tu.canon_district(b.get("district")) != tu.canon_district(sel_zone):
                continue
            raw_w = str(b.get("ward") or "").strip()
            if not raw_w:
                continue
            kw = tu.canon_ward(raw_w)
            if not kw:
                continue
            wcounts[kw] = wcounts.get(kw, 0) + 1
            if kw not in wards or len(raw_w) < len(wards[kw]):
                wards[kw] = raw_w
        self.cmb_ward.blockSignals(True)
        self.cmb_ward.clear()
        self.cmb_ward.addItem("Tất cả phường", None)
        for kw in sorted(wards, key=lambda x: -wcounts[x]):
            self.cmb_ward.addItem(f"🏷️ {wards[kw]}  ({wcounts[kw]} tòa)", wards[kw])
        idx = self.cmb_ward.findData(cur_ward)
        self.cmb_ward.setCurrentIndex(max(0, idx))
        self.cmb_ward.blockSignals(False)

    def _zone_changed(self, *_):
        """Đổi khu vực -> làm mới phường phụ thuộc + refresh cụm."""
        self._reload_zones(self.mgr.buildings(text=self.ed_search.text()))
        self.refresh()

    def _apply_filter(self, *_):
        self.refresh()

    def _add(self):
        dlg = BuildingForm(None, self)
        if dlg.exec() != QDialog.Accepted:
            return
        payload = dlg.payload()
        if not (payload.get("house_number") or payload.get("street")):
            QMessageBox.warning(self, "Thiếu dữ liệu", "Cần ít nhất số nhà hoặc tên đường.")
            return
        try:
            self.mgr.save_building(payload, bid=None)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không lưu được", str(e))
            return
        self.refresh()

    def _edit(self, bid: str):
        b = self.mgr.building(bid)
        if not b:
            return
        dlg = BuildingForm(b, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.mgr.save_building(dlg.payload(), bid=bid)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không lưu được", str(e))
            return
        self.refresh()
