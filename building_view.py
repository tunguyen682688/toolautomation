# -*- coding: utf-8 -*-
"""building_view.py - Trang Tòa nhà: lưới thẻ tòa (FlowLayout) + form thêm/sửa tòa.

Mỗi thẻ: địa chỉ, chủ nhà, chip số phòng trống/thuê/cọc, nút xem phòng, gọi / Zalo / Drive.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QLayout, QListView,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStyle, QTableView, QToolButton, QVBoxLayout, QWidget,
)

import text_utils as tu
from google_drive import open_drive, open_phone, open_zalo
from models import RoomFilter
import theme
from theme import C_ACCENT, C_BORDER, C_OK, C_ORANGE, C_WARN, C_DANGER, C_MUTED, \
    status_bg, status_color, status_label


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
    """8 nhóm dữ liệu (áp dụng cho tòa: địa chỉ / chủ nhà / quy định / hoa hồng...)."""

    def __init__(self, building: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sửa thông tin tòa nhà" if building else "Thêm tòa nhà mới")
        self.setMinimumWidth(560)
        self.building = building or {}
        self.fields: Dict[str, QLineEdit] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        def add_group(title: str, rows: List[tuple]):
            box = QFrame()
            box.setObjectName("Card")
            gl = QVBoxLayout(box)
            gl.setContentsMargins(14, 10, 14, 12)
            gl.setSpacing(7)
            t = QLabel(title)
            t.setObjectName("SectionTitle")
            t.setStyleSheet("font-size:13.5px; background:transparent;")
            gl.addWidget(t)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            for key, label in rows:
                ed = QLineEdit(str(self.building.get(key, "") or ""))
                ed.setPlaceholderText(label)
                self.fields[key] = ed
                form.addRow(label + ":", ed)
            gl.addLayout(form)
            lay.addWidget(box)

        add_group("1. Địa chỉ tòa nhà", [
            ("house_number", "Số nhà"), ("street", "Tên đường"),
            ("ward", "Phường"), ("district", "Quận / Khu vực cũ"),
        ])
        add_group("2. Chủ nhà / Admin quản lý", [
            ("owner_name", "Chủ tòa / Admin"), ("phone", "Số điện thoại"),
            ("zalo_group", "Link Group Zalo"),
        ])
        add_group("3. Quy định & hoa hồng", [
            ("ev_policy", "Quy định xe điện"), ("pet_policy", "Quy định thú cưng"),
            ("commission", "Chính sách hoa hồng sale"), ("notes", "Ghi chú khác"),
        ])

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def payload(self) -> Dict[str, Any]:
        return {k: ed.text().strip() for k, ed in self.fields.items()}


# ------------------------------------------------------------------ panel phòng nhanh bên phải (split view)
class RoomsInlinePanel(QFrame):
    """Hiển thị NGAY danh sách phòng của tòa đang chọn (inline, không nhảy trang)."""

    open_detail = Signal(str)   # room_id
    open_full_table = Signal(dict)   # filter dict -> mở trang Phòng đầy đủ

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.building = None
        self.setObjectName("Card")
        self.setMinimumWidth(300)
        self.setMaximumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.lbl_title = QLabel("Chọn một tòa nhà")
        self.lbl_title.setObjectName("SectionTitle")
        lay.addWidget(self.lbl_title)

        self.lbl_sub = QLabel("Bấm thẻ tòa nhà ở bên trái để xem phòng.")
        self.lbl_sub.setObjectName("Muted")
        self.lbl_sub.setWordWrap(True)
        lay.addWidget(self.lbl_sub)

        # --- nút xem tất cả (không giới hạn tòa) ---
        self.btn_all = QPushButton("🏠 Xem tất cả phòng")
        self.btn_all.setObjectName("Ghost")
        self.btn_all.setToolTip("Xem toàn bộ danh sách phòng (không lọc theo tòa)")
        self.btn_all.clicked.connect(lambda: self.open_full_table.emit(
            {"filter": RoomFilter(), "title": "Tất cả phòng"}))
        lay.addWidget(self.btn_all)

        # danh sách phòng ngắn gọn (1 dòng mỗi phòng: mã + loại + trạng thái + giá)
        self.model = QStandardItemModel()
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setAlternatingRowColors(True)
        self.list.clicked.connect(self._item_clicked)
        lay.addWidget(self.list, 1)

        self.btn_empty = QPushButton("Chưa có phòng nào")
        self.btn_empty.setEnabled(False)
        lay.addWidget(self.btn_empty)

        btn_open = QPushButton("📋 Mở bảng phòng đầy đủ")
        btn_open.setObjectName("Primary")
        btn_open.clicked.connect(self._open_full)
        lay.addWidget(btn_open)

    def set_building(self, b: Dict[str, Any] | None):
        self.building = b
        self.model.clear()
        if not b:
            self.lbl_title.setText("Chọn một tòa nhà")
            self.lbl_sub.setText("Bấm thẻ tòa nhà ở bên trái để xem phòng.")
            self.btn_empty.setEnabled(False)
            return
        self.lbl_title.setText(f"{b.get('code','')} — {b.get('display','')}")
        owner = b.get("owner_name") or "—"
        phone = b.get("phone") or "—"
        self.lbl_sub.setText(f"👤 {owner} · 📞 {phone} · bấm phòng để xem chi tiết")
        rooms = self.mgr.rooms("", RoomFilter(building_id=b["id"])) or []
        if not rooms:
            self.lbl_sub.setText(self.lbl_sub.text() + " (chưa có phòng)")
            self.btn_empty.setText("Thêm phòng đầu tiên")
            self.btn_empty.setEnabled(True)
            self.btn_empty.clicked.disconnect()
            self.btn_empty.clicked.connect(lambda: self.open_full_table.emit(
                {"filter": RoomFilter(building_id=b["id"]), "title": b.get("display", "")}))
            return
        self.btn_empty.hide()
        for r in rooms:
            st = r.get("status", "")
            loai = r.get("room_type") or "(chưa rõ)"
            item = QStandardItem(
                f"{r.get('room_code') or '(chưa có mã)'}   ●   {loai}   ●   {status_label(st)}   "
                f"| {tu.format_money(r.get('price'))}₫")
            item.setData(QColor(status_bg(st)), 5)  # UserRole-ish custom
            item.setData(st, 6)
            item.setForeground(QColor(status_color(st)))
            item.setEditable(False)
            self.model.appendRow(item)
        self.lbl_sub.setText(
            f"{len(rooms)} phòng · " + self.lbl_sub.text().split("·")[0].strip())

    def _item_clicked(self, index: QModelIndex):
        st = index.data(6)
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
    open_rooms = Signal(dict)          # filter
    edit_requested = Signal(str)

    def __init__(self, b: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.b = b
        self.setCursor(Qt.PointingHandCursor)
        # KÍCH THƯỚC ĐỀU NHAU -> thẻ xếp thành lưới cân đối trong FlowLayout
        self.setFixedWidth(375)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 13, 15, 13)
        lay.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(10)
        code = QLabel(b.get('code', ''))
        code.setStyleSheet(f"font-size:12px; font-weight:800; color:{theme.c('accent')}; background:transparent;")
        code.setFixedWidth(34)
        top.addWidget(code)
        addr = QLabel(f"<b style='font-size:15px'>{b.get('display', '')}</b>")
        addr.setTextFormat(Qt.RichText)
        addr.setStyleSheet("background:transparent;")
        addr.setWordWrap(True)
        top.addWidget(addr, 1)
        lay.addLayout(top)

        owner = QLabel(f"👤 {b.get('owner_name') or '—'} &nbsp;·&nbsp; 📞 {b.get('phone') or '—'}")
        owner.setTextFormat(Qt.RichText)
        owner.setObjectName("Muted")
        owner.setStyleSheet(f"background:transparent; font-size:12px; color:{theme.c('text2')};")
        owner.setWordWrap(True)
        lay.addWidget(owner)

        # chip số phòng
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(self._chip(f"Trống {b.get('rooms_vacant', 0)}", "vacant"))
        chips.addWidget(self._chip(f"Cọc/giữ {b.get('rooms_deposit', 0)}", "deposit"))
        chips.addWidget(self._chip(f"Thuê {b.get('rooms_rented', 0)}", "rented"))
        chips.addWidget(self._chip(f"Sắp trống {b.get('rooms_soon', 0)}", "soon_vacant"))
        total = QLabel(f"Σ {b.get('rooms_total', 0)}")
        total.setStyleSheet(f"background:transparent; color:{theme.c('text')}; font-weight:800; padding:4px 10px;")
        chips.addWidget(total)
        chips.addStretch(1)
        lay.addLayout(chips)

        meta = QLabel(f"⚡ {b.get('ev_policy') or '—'} &nbsp;·&nbsp; 🐾 {b.get('pet_policy') or '—'}")
        meta.setTextFormat(Qt.RichText)
        meta.setObjectName("Muted")
        meta.setStyleSheet(f"background:transparent; font-size:11.5px; color:{theme.c('text2')};")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_rooms = QPushButton("📋 Phòng")
        btn_rooms.setObjectName("Ghost")
        btn_rooms.setMinimumHeight(34)
        btn_rooms.clicked.connect(self._open_rooms)
        actions.addWidget(btn_rooms)

        btn_edit = QPushButton("✏️ Sửa")
        btn_edit.setObjectName("Ghost")
        btn_edit.setMinimumHeight(34)
        btn_edit.clicked.connect(lambda: self.edit_requested.emit(self.b["id"]))
        actions.addWidget(btn_edit)

        if b.get("phone"):
            btn_call = QToolButton()
            btn_call.setText("📞")
            btn_call.setToolTip(f"Gọi {b.get('phone')}")
            btn_call.setStyleSheet("QToolButton { border: none; font-size: 16px; }")
            btn_call.clicked.connect(lambda: open_phone(self.b.get("phone", "")))
            actions.addWidget(btn_call)

        if b.get("zalo_group"):
            btn_zalo = QToolButton()
            btn_zalo.setText("💬")
            btn_zalo.setToolTip("Mở Group Zalo")
            btn_zalo.setStyleSheet("QToolButton { border: none; font-size: 16px; }")
            btn_zalo.clicked.connect(lambda: open_zalo(self.b.get("zalo_group", "")))
            actions.addWidget(btn_zalo)
        actions.addStretch(1)
        lay.addLayout(actions)

    def _chip(self, text: str, color_key: str) -> QLabel:
        color = {"vacant": theme.c("ok"), "deposit": theme.c("orange"),
                 "holding": theme.c("warn"), "rented": theme.c("danger"),
                 "soon_vacant": theme.c("warn")}.get(color_key, theme.c("text2"))
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"background:{color}15; color:{color}; border-radius:20px; padding:4px 12px;"
            f"font-size:11.5px; font-weight:700; border:1px solid {color}30;"
        )
        return lbl

    def _open_rooms(self):
        self.open_rooms.emit({"building": self.b, "title": self.b.get("display", "")})

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._open_rooms()
        super().mousePressEvent(ev)


# ------------------------------------------------------------------ trang tòa nhà
class BuildingPage(QWidget):
    building_selected = Signal(dict)   # click thẻ -> hiển thị phòng inline bên phải
    open_detail = Signal(str)          # click 1 phòng trong panel nhanh -> chi tiết
    open_rooms = Signal(dict)          # "Mở bảng đầy đủ" -> điều hướng trang Phòng

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._cards: List[BuildingCard] = []
        self._build_ui()
        self.building_selected.connect(lambda d: self.panel.set_building(d.get("building")))

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header trang (giống main_window)
        head = QFrame()
        head.setObjectName("Card")
        head.setStyleSheet("QFrame#Card { background: transparent; border: none; }")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 18, 22, 16)
        hl.setSpacing(0)
        t = QLabel("Danh mục tòa nhà & chủ nhà")
        t.setObjectName("PageHeaderTitle")
        hl.addWidget(t)
        hl.addStretch(1)
        self.btn_add = QPushButton("＋ Thêm tòa nhà")
        self.btn_add.setObjectName("Primary")
        self.btn_add.clicked.connect(self._add)
        hl.addWidget(self.btn_add)
        lay.addWidget(head)

        # subtitle
        sub = QLabel("Quản lý danh sách tòa nhà, chủ nhà và thông tin liên hệ")
        sub.setObjectName("PageHeaderSubtitle")
        sub.setStyleSheet(f"color:{theme.c('text2')}; font-size:12.5px; padding:0 22px 0 22px;")
        lay.addWidget(sub)
        lay.addSpacing(6)

        filt = QFrame()
        filt.setObjectName("Toolbar")
        fl = QHBoxLayout(filt)
        fl.setContentsMargins(22, 8, 22, 8)
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
        self.ed_search = _QLE()
        self.ed_search.setPlaceholderText("🔎 Lọc theo địa chỉ / chủ nhà / SĐT...")
        self.ed_search.setMinimumWidth(300)
        self.ed_search.textChanged.connect(self._apply_filter)
        fl.addWidget(self.ed_search, 1)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("Muted")
        fl.addWidget(self.lbl_count)
        lay.addWidget(filt)

        # ---- SPLIT VIEW: trái thẻ tòa | phải danh sách phòng của tòa được chọn
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # trái: lưới thẻ tòa nhà
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        # phân cụm: mỗi khu vực = 1 header + 1 dòng thẻ (FlowLayout riêng)
        self.container_lay = QVBoxLayout(self.container)
        self.container_lay.setContentsMargins(0, 0, 6, 0)
        self.container_lay.setSpacing(6)
        self.container.setLayout(self.container_lay)
        self._cluster_flows: List[FlowLayout] = []
        scroll.setWidget(self.container)
        ll.addWidget(scroll, 1)
        split.addWidget(left)

        # phải: panel phòng nhanh của tòa đang chọn
        self.panel = RoomsInlinePanel(self.mgr)
        self.panel.open_detail.connect(self.open_detail.emit)
        self.panel.open_full_table.connect(self.open_rooms.emit)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([700, 380])

        lay.addWidget(split, 1)

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

        # dọn container cũ
        while self.container_lay.count():
            item = self.container_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards = []
        self._cluster_flows = []

        if not buildings:
            empty = QLabel("Không có tòa nhà nào khớp bộ lọc.")
            empty.setObjectName("Muted")
            self.container_lay.addWidget(empty)
        else:
            # ---- PHÂN CỤM CẤP 1: KHU VỰC (quận): 'Q. Bình Thạnh cũ' = 'Q. Bình Thạnh' ----
            groups: Dict[str, Dict] = {}
            order: List[str] = []
            for b in buildings:
                raw = str(b.get("district") or "").strip()
                k = tu.canon_district(raw) or "(khác)"
                g = groups.get(k)
                if not g:
                    g = {"title": raw or "Khu vực khác", "items": []}
                    groups[k] = g
                    order.append(k)
                g["items"].append(b)
                if raw and len(raw) < len(g["title"]):
                    g["title"] = raw        # ưu tiên tên ngắn gọn
            order.sort(key=lambda k: -len(groups[k]["items"]))   # cụm nhiều tòa lên trước

            for k in order:
                g = groups[k]
                n_b = len(g["items"])
                n_rooms = sum(int(b.get("rooms_total", 0) or 0) for b in g["items"])
                n_vac = sum(int(b.get("rooms_vacant", 0) or 0) for b in g["items"])
                header = QLabel(
                    f"📍 {g['title']}    ·    {n_b} tòa    ·    {n_rooms} phòng    ·    {n_vac} trống")
                header.setStyleSheet(
                    f"background:{theme.c('accent_soft')}; color:{theme.c('accent_soft_text')};"
                    f" font-weight:800; font-size:13.5px;"
                    f"border-left:4px solid {theme.c('accent')}; border-radius:8px; padding:8px 12px;")
                self.container_lay.addWidget(header)

                # ---- PHÂN CỤM CẤP 2: PHƯỜNG (P.13, P.5, ...) - tự tạo từ dữ liệu ----
                ward_groups: Dict[str, Dict] = {}
                ward_order: List[str] = []
                for b in g["items"]:
                    raw_w = str(b.get("ward") or "").strip()
                    kw = tu.canon_ward(raw_w) or "(khác)"
                    wg = ward_groups.get(kw)
                    if not wg:
                        wg = {"title": raw_w or "Chưa phân phường", "items": []}
                        ward_groups[kw] = wg
                        ward_order.append(kw)
                    wg["items"].append(b)
                    if raw_w and len(raw_w) < len(wg["title"]):
                        wg["title"] = raw_w

                # thứ tự phường theo TÊN (A->Z) -> cụm ổn định, dễ tra cứu
                ward_order.sort(key=lambda x: ward_groups[x]["title"].lower())
                show_wards = len(ward_groups) > 1

                def _ward_sub(wk: str):
                    """Header phường + lưới thẻ của phường đó."""
                    wg = ward_groups[wk]
                    if show_wards:
                        n_wb = len(wg["items"])
                        n_wr = sum(int(b.get("rooms_total", 0) or 0) for b in wg["items"])
                        n_wv = sum(int(b.get("rooms_vacant", 0) or 0) for b in wg["items"])
                        sub = QLabel(
                            f"        🏷️ {wg['title']}   ·   {n_wb} tòa   ·   "
                            f"{n_wr} phòng   ·   {n_wv} trống")
                        sub.setStyleSheet(
                            f"background:{theme.c('card2')}; color:{theme.c('text2')};"
                            f" font-weight:700; font-size:12.5px;"
                            f"border-left:3px solid {theme.c('text3')}; border-radius:6px;"
                            " padding:6px 10px; margin-left:16px;")
                        self.container_lay.addWidget(sub)

                    wrap = QWidget()
                    wrap.setStyleSheet("background:transparent;")
                    flow = FlowLayout(wrap, 14, 14)
                    flow.setContentsMargins(0, 0, 6, 0)
                    wrap.setLayout(flow)
                    for b in wg["items"]:
                        card = BuildingCard(b)
                        card.open_rooms.connect(self.building_selected.emit)
                        card.edit_requested.connect(self._edit)
                        flow.addWidget(card)
                        self._cards.append(card)
                    self._cluster_flows.append(flow)
                    self.container_lay.addWidget(wrap)

                # ---- CỤM TỰ ĐỘNG ~5 PHƯỜNG: quận nhiều phường -> gom thành cụm cho dễ quản lý ----
                CLUSTER_SIZE = 5
                if len(ward_order) > CLUSTER_SIZE:
                    chunks = [ward_order[i:i + CLUSTER_SIZE]
                              for i in range(0, len(ward_order), CLUSTER_SIZE)]
                    for ci, chunk in enumerate(chunks, 1):
                        c_items = [b for wk in chunk for b in ward_groups[wk]["items"]]
                        n_cb = len(c_items)
                        n_cr = sum(int(b.get("rooms_total", 0) or 0) for b in c_items)
                        n_cv = sum(int(b.get("rooms_vacant", 0) or 0) for b in c_items)
                        names = ", ".join(ward_groups[wk]["title"] for wk in chunk)
                        chead = QLabel(
                            f"    🧩 Cụm {ci} · {names}\n"
                            f"    {len(chunk)} phường   ·   {n_cb} tòa   ·   "
                            f"{n_cr} phòng   ·   {n_cv} trống")
                        chead.setWordWrap(True)
                        chead.setStyleSheet(
                            f"background:{theme.c('info_soft')}; color:{theme.c('info')};"
                            f" font-weight:800; font-size:13px;"
                            f"border-left:4px solid {theme.c('info')}; border-radius:8px;"
                            " padding:8px 12px;")
                        self.container_lay.addWidget(chead)
                        for wk in chunk:
                            _ward_sub(wk)
                else:
                    for wk in ward_order:
                        _ward_sub(wk)

        self.lbl_count.setText(f"{len(buildings)} tòa nhà")

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
