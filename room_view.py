# -*- coding: utf-8 -*-
"""room_view.py - Trang Phòng: bảng ảo hoá (QAbstractTableModel) + lọc + panel chi tiết + menu chuột phải.

Đặc tả ưu tiên: bảng phải CUỘN MƯỢT với hàng nghìn dòng -> chỉ tải dữ liệu theo yêu cầu,
màu trạng thái theo RoomStatus, sửa trực tiếp (inline) gọi manager.update_room,
đổi trạng thái không sinh ID mới, trùng dữ liệu -> hộp thoại mở bản ghi cũ.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QStyledItemDelegate, QStyleOptionViewItem, QTableView, QToolButton,
    QVBoxLayout, QWidget,
)

import text_utils as tu
from inventory_manager import DuplicateError
from models import ROOM_TABLE_COLUMNS, ROOM_TYPES, RoomFilter, RoomStatus
from theme import status_bg, status_color, status_label


# ------------------------------------------------------------------ delegate hiển thị
class RoomDelegate(QStyledItemDelegate):
    def paint(self, painter: QStyleOptionViewItem, option, index):
        opt = QStyleOptionViewItem(option)
        col_key = ROOM_TABLE_COLUMNS[index.column()][0]
        row = index.row()
        model = index.model()
        if col_key == "status":
            st = model.data(index, Qt.UserRole) or ""
            # trạng thái hiển thị mờ nhạt, chữ đậm, căn giữa
            opt.displayAlignment = Qt.AlignCenter | Qt.AlignVCenter
            opt.font = QFont(opt.font)
            opt.font.setBold(True)
            opt.font.setPointSize(max(9, opt.font.pointSize() - 1))
        elif col_key in ("price", "deposit"):
            opt.displayAlignment = Qt.AlignRight | Qt.AlignVCenter
        elif col_key in ("foreign_guest", "ev_support", "surveyed"):
            opt.displayAlignment = Qt.AlignCenter | Qt.AlignVCenter
        elif col_key == "area":
            opt.displayAlignment = Qt.AlignCenter | Qt.AlignVCenter
        super().paint(painter, opt, index)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 44))
        return s


# ------------------------------------------------------------------ model bảng
class RoomTableModel(QAbstractTableModel):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.rows: List[Dict[str, Any]] = []
        self._text = ""
        self._filter: Optional[RoomFilter] = None

    # --- data pipeline
    def set_query(self, text: str, f: Optional[RoomFilter]):
        self.beginResetModel()
        self._text = text
        self._filter = f
        self.rows = self.mgr.rooms(text, f)
        self.endResetModel()

    def refresh(self):
        self.set_query(self._text, self._filter)

    def room_at(self, row: int) -> Optional[Dict[str, Any]]:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def room_id_at(self, row: int) -> str:
        r = self.room_at(row)
        return r["id"] if r else ""

    # --- QAbstractTableModel
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(ROOM_TABLE_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ROOM_TABLE_COLUMNS[section][1]
        if role == Qt.TextAlignmentRole and orientation == Qt.Horizontal:
            key = ROOM_TABLE_COLUMNS[section][0]
            if key in ("price", "deposit"):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        key = ROOM_TABLE_COLUMNS[index.column()][0]
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if key in ("status", "price", "deposit", "room_code", "room_type"):
            f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        key = ROOM_TABLE_COLUMNS[index.column()][0]
        if role == Qt.UserRole:
            return r.get("status", "")
        if role == Qt.ForegroundRole and key == "status":
            return QColor(status_color(r.get("status", "")))
        if role == Qt.TextAlignmentRole and key in ("price", "deposit"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return (f"{r.get('room_code','')} - {r.get('address','')}\n"
                    f"Trạng thái: {status_label(r.get('status',''))}\n"
                    f"Cập nhật: {r.get('updated_at','')} bởi {r.get('updated_by','')}\n"
                    f"ID nội bộ: {r.get('id','')} (không đổi khi đổi trạng thái)")
        if role != Qt.DisplayRole:
            return None
        v = r.get(key, "")
        if key == "status":
            return status_label(v)
        if key in ("price", "deposit"):
            return tu.format_money(v) + " ₫"
        if key == "area":
            return f"{v} m2" if v else "—"
        if key == "surveyed":
            return "✅ Đã KS" if v else "Chưa KS"
        if key == "ev_support":
            return "⚡ Có" if v else "—"
        if key == "foreign_guest":
            return "🌏 Có" if v else "—"
        if key == "pet_policy":
            return v or "—"
        if key == "updated_at":
            return (v or "")[:16]
        if key == "address":
            return v or "—"
        return str(v) if v not in (None, "") else ""

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        r = self.rows[index.row()]
        key = ROOM_TABLE_COLUMNS[index.column()][0]
        rid = r["id"]
        changes: Dict[str, Any] = {}
        if key == "status":
            st = RoomStatus.from_text(value)
            if st not in RoomStatus.LABEL or st == r.get("status"):
                return False
            changes["status"] = st
        elif key == "price":
            changes["price"] = tu.normalize_price(value)
            if changes["price"] == int(r.get("price") or 0):
                return False
        elif key == "deposit":
            changes["deposit"] = tu.normalize_price(value)
            if changes["deposit"] == int(r.get("deposit") or 0):
                return False
        elif key == "room_code":
            changes["room_code"] = str(value).strip()
        elif key == "room_type":
            changes["room_type"] = str(value).strip()
        else:
            return False
        ok = self.mgr.try_update(rid, changes)
        return bool(ok)


# ------------------------------------------------------------------ widget phòng
class RoomPage(QWidget):
    status_changed = Signal(str, str)     # room_id, status
    duplicate_open = Signal(str)          # mở bản ghi trùng

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._filter = RoomFilter()
        self._text = ""
        self._multi_statuses = None      # bộ lọc nhiều trạng thái (từ Dashboard)
        self._title = "Tất cả phòng"
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QFrame()
        head.setObjectName("Card")
        head.setStyleSheet("QFrame#Card { background: transparent; border: none; border-radius: 0; }")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(0)

        self.lbl_title = QLabel("Danh sách phòng")
        self.lbl_title.setObjectName("PageHeaderTitle")
        hl.addWidget(self.lbl_title)
        hl.addStretch(1)

        self.btn_undo = QPushButton("↩ Hoàn tác (Ctrl+Z)")
        self.btn_undo.setObjectName("Ghost")
        self.btn_undo.setToolTip("Hoàn tác thao tác sửa/xóa/thêm gần nhất")
        self.btn_undo.clicked.connect(self._undo)
        hl.addWidget(self.btn_undo)

        self.btn_batch = QPushButton("🛠 Sửa hàng loạt")
        self.btn_batch.setObjectName("Ghost")
        self.btn_batch.setToolTip("Chọn nhiều dòng → thay đổi trạng thái/giá/chính sách 1 lúc")
        self.btn_batch.clicked.connect(self._batch_edit)
        hl.addWidget(self.btn_batch)

        self.btn_new = QPushButton("＋ Thêm phòng")
        self.btn_new.setObjectName("Primary")
        self.btn_new.clicked.connect(self._add_room)
        hl.addWidget(self.btn_new)
        lay.addWidget(head)

        # subtitle
        sub = QLabel("Tìm kiếm, lọc và cập nhật thông tin từng căn hộ")
        sub.setObjectName("PageHeaderSubtitle")
        sub.setStyleSheet("color:#6B7280; font-size:12.5px; padding:0 22px 0 22px;")
        lay.addWidget(sub)
        lay.addSpacing(6)

        # ============================ BỘ LỌC (2 hàng, không bị tràn) ============================
        bar = QFrame()
        bar.setObjectName("Toolbar")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(22, 8, 22, 8)
        bl.setSpacing(8)

        # Hàng 1: bộ lọc chính
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Tất cả trạng thái", None)
        for k in RoomStatus.ORDER:
            self.cmb_status.addItem(f"● {RoomStatus.label(k)}", k)
        self.cmb_status.currentIndexChanged.connect(self._status_changed)
        row1.addWidget(self.cmb_status)

        self.cmb_type = QComboBox()
        self.cmb_type.addItem("Tất cả loại phòng", None)
        for t in ROOM_TYPES:
            self.cmb_type.addItem(t, t)
        self.cmb_type.currentIndexChanged.connect(self._apply_filter)
        row1.addWidget(self.cmb_type)

        self.cmb_building = QComboBox()
        self.cmb_building.addItem("Tất cả tòa nhà", None)
        self.cmb_building.setMinimumWidth(190)
        self.cmb_building.currentIndexChanged.connect(self._apply_filter)
        row1.addWidget(self.cmb_building)

        self.chk_ev = QCheckBox("⚡ Xe điện")
        self.chk_ev.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_ev)
        self.chk_foreign = QCheckBox("🌏 Khách nước ngoài")
        self.chk_foreign.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_foreign)
        self.chk_pet = QCheckBox("🐾 Cho nuôi pet")
        self.chk_pet.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_pet)
        self.chk_unsurvey = QCheckBox("Chưa khảo sát")
        self.chk_unsurvey.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_unsurvey)
        self.chk_deleted = QCheckBox("Hiện đã xóa")
        self.chk_deleted.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_deleted)
        row1.addStretch(1)
        bl.addLayout(row1)

        # Hàng 2: khoảng giá + nút reset + đếm
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        lbl = QLabel("Giá từ")
        lbl.setObjectName("Muted")
        row2.addWidget(lbl)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(0, 100_000_000)
        self.spin_min.setSingleStep(500_000)
        self.spin_min.setSpecialValueText("Bỏ trống")
        self.spin_min.valueChanged.connect(self._apply_filter)
        row2.addWidget(self.spin_min)
        lbl2 = QLabel("đến")
        lbl2.setObjectName("Muted")
        row2.addWidget(lbl2)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(0, 100_000_000)
        self.spin_max.setSingleStep(500_000)
        self.spin_max.setSpecialValueText("Bỏ trống")
        self.spin_max.valueChanged.connect(self._apply_filter)
        row2.addWidget(self.spin_max)

        row2.addSpacing(16)
        self.btn_reset = QPushButton("🏠 Xem tất cả")
        self.btn_reset.setObjectName("Ghost")
        self.btn_reset.setToolTip("Bỏ toàn bộ bộ lọc")
        self.btn_reset.clicked.connect(self.reset_filters)
        row2.addWidget(self.btn_reset)
        row2.addStretch(1)

        self.lbl_count = QLabel("0 phòng")
        self.lbl_count.setObjectName("Muted")
        row2.addWidget(self.lbl_count)
        bl.addLayout(row2)
        lay.addWidget(bar)

        # ============================ BẢNG + PANEL CHI TIẾT ============================
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)

        # Bảng phòng (bên trái - chiếm phần lớn)
        self.model = RoomTableModel(self.mgr)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(RoomDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # chọn nhiều dòng
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, _, w) in enumerate(ROOM_TABLE_COLUMNS):
            self.table.setColumnWidth(i, w)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)     # cột địa chỉ co giãn
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda idx: self._open_detail(self.model.room_id_at(idx.row())))
        split.addWidget(self.table)

        # Panel chi tiết (bên phải - cố định chiều rộng)
        detail = QFrame()
        detail.setObjectName("DetailPanel")
        detail.setMinimumWidth(340)
        detail.setMaximumWidth(480)
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)

        # tiêu đề panel
        phead = QFrame()
        phead.setObjectName("Card")
        phead.setStyleSheet("QFrame#Card { background: transparent; border: none; border-radius: 0; }")
        phl = QVBoxLayout(phead)
        phl.setContentsMargins(20, 16, 20, 14)
        phl.setSpacing(4)
        dt = QLabel("Chi tiết phòng")
        dt.setObjectName("SectionTitle")
        phl.addWidget(dt)
        dl.addWidget(phead)

        self.detail_body = QLabel("Chọn một dòng trong bảng để xem chi tiết.")
        self.detail_body.setTextFormat(Qt.RichText)
        self.detail_body.setWordWrap(True)
        self.detail_body.setStyleSheet(
            "background:transparent; line-height: 160%; padding: 0 20px;")
        dl.addWidget(self.detail_body, 1)

        # vùng nút hành động
        self.detail_actions = QVBoxLayout()
        self.detail_actions.setContentsMargins(16, 8, 16, 16)
        self.detail_actions.setSpacing(8)
        dl.addLayout(self.detail_actions)
        split.addWidget(detail)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        lay.addWidget(split, 1)

        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, prev: self._open_detail(self.model.room_id_at(cur.row()) if cur.isValid() else ""))

        # tải danh sách tòa nhà vào bộ lọc
        self._load_buildings()

    def _load_buildings(self):
        """Đổ danh sách tòa nhà vào combobox lọc (giữ nguyên lựa chọn hiện tại nếu có)."""
        cur = self.cmb_building.currentData()
        self.cmb_building.blockSignals(True)
        self.cmb_building.clear()
        self.cmb_building.addItem("Tất cả tòa nhà", None)
        try:
            for b in self.mgr.buildings():
                self.cmb_building.addItem(f"{b.get('code','')} — {b.get('display','')}", b["id"])
        except Exception:  # noqa: BLE001
            pass
        # khôi phục lựa chọn nếu toà vẫn còn
        idx = self.cmb_building.findData(cur)
        self.cmb_building.setCurrentIndex(max(0, idx))
        self.cmb_building.blockSignals(False)

    # ------------------------------------------------------------------ bộ lọc / query
    def set_query(self, text: str = "", filter_dict: Optional[Dict] = None,
                  title: Optional[str] = None):
        self._text = text
        if filter_dict is not None:
            f = filter_dict.get("filter")
            self._filter = f if isinstance(f, RoomFilter) else RoomFilter()
            multi = list(self._filter.statuses) if len(self._filter.statuses or ()) > 1 else None
            # đồng bộ điều khiển (tạm chặn signal để không clear bộ lọc nhiều trạng thái)
            st = (self._filter.statuses or [None])[0] if self._filter.statuses else None
            widgets = [self.cmb_status, self.cmb_type, self.cmb_building, self.chk_ev, self.chk_foreign,
                       self.chk_pet,
                       self.chk_unsurvey, self.chk_deleted, self.spin_min, self.spin_max]
            for w in widgets:
                w.blockSignals(True)
            i = self.cmb_status.findData(st)
            self.cmb_status.setCurrentIndex(max(0, i))
            i = self.cmb_type.findData((self._filter.room_types or [None])[0])
            self.cmb_type.setCurrentIndex(max(0, i))
            i = self.cmb_building.findData(self._filter.building_id)
            self.cmb_building.setCurrentIndex(max(0, i))
            self.chk_ev.setChecked(bool(self._filter.ev_support))
            self.chk_pet.setChecked(bool(self._filter.pet_allowed))
            self.chk_unsurvey.setChecked(self._filter.surveyed is False)
            self.chk_deleted.setChecked(bool(self._filter.include_deleted))
            self.spin_min.setValue(int(self._filter.price_min or 0))
            self.spin_max.setValue(int(self._filter.price_max or 0))
            for w in widgets:
                w.blockSignals(False)
            self._multi_statuses = multi
            if title:
                self._title = title
        self._apply_filter()

    def set_text(self, text: str):
        """Gõ tìm kiếm từ thanh trên cùng."""
        self._text = text
        self._apply_filter()

    def _collect_filter(self) -> RoomFilter:
        cur = self.cmb_status.currentData()
        statuses = None
        if cur:
            multi = self._multi_statuses
            statuses = list(multi) if (multi and cur in multi) else [cur]
        else:
            self._multi_statuses = None
        types = [self.cmb_type.currentData()] if self.cmb_type.currentData() else None
        building_id = self.cmb_building.currentData()
        return RoomFilter(
            building_id=building_id,
            statuses=statuses,
            room_types=types,
            price_min=self.spin_min.value() or None,
            price_max=self.spin_max.value() or None,
            ev_support=True if self.chk_ev.isChecked() else None,
            foreign_guest=True if self.chk_foreign.isChecked() else None,
            pet_allowed=True if self.chk_pet.isChecked() else None,
            surveyed=False if self.chk_unsurvey.isChecked() else None,
            include_deleted=self.chk_deleted.isChecked(),
        )

    def _status_changed(self, *_):
        """Người dùng tự đổi trạng thái -> bỏ bộ lọc nhiều trạng thái từ Dashboard."""
        self._multi_statuses = None
        self._apply_filter()

    def _apply_filter(self, *_):
        self._filter = self._collect_filter()
        self.model.set_query(getattr(self, "_text", ""), self._filter)
        n = self.model.rowCount()
        self.lbl_count.setText(f"{n} phòng" + (f" · «{self._title}»" if self._title != "Tất cả phòng" else ""))
        self.lbl_title.setText(self._title if self._title != "Tất cả phòng" else "Danh sách phòng")

    def reset_filters(self):
        self._filter = RoomFilter()
        self._title = "Tất cả phòng"
        self.cmb_status.setCurrentIndex(0)
        self.cmb_type.setCurrentIndex(0)
        self.cmb_building.setCurrentIndex(0)
        self.chk_ev.setChecked(False)
        self.chk_foreign.setChecked(False)
        self.chk_pet.setChecked(False)
        self.chk_unsurvey.setChecked(False)
        self.chk_deleted.setChecked(False)
        self.spin_min.setValue(0)
        self.spin_max.setValue(0)
        self._apply_filter()

    def refresh(self):
        self._apply_filter()

    # ------------------------------------------------------------------ chi tiết
    def _open_detail(self, rid: str):
        # dọn nút cũ
        while self.detail_actions.count():
            item = self.detail_actions.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not rid:
            self.detail_body.setText("Chọn một dòng trong bảng để xem chi tiết.")
            return
        r = self.mgr.room(rid)
        if not r:
            self.detail_body.setText("Không tìm thấy phòng (có thể đã xóa).")
            return
        st = r.get("status", "")
        fg = r.get("foreign_guest", 0)
        html = f"""
        <div style='font-size:18px; font-weight:800;'>{r.get('room_code') or '(chưa có mã)'}</div>
        <div style='color:{status_color(st)}; font-weight:700; margin-top:2px;'>● {status_label(st)}</div>
        {'<div style="color:#15803D; font-weight:700; font-size:12px; margin-top:2px;">🌏 Nhận khách nước ngoài</div>' if fg else ''}
        <hr style='border:none; border-top:1px solid #E5E7EB; margin:10px 0;'>
        <div style='font-size:13px; line-height:1.7;'>
        <span style='color:#6B7280; font-weight:700;'>Địa chỉ:</span> {r.get('address') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Số căn / Tầng:</span> {r.get('unit_code') or '—'} / {r.get('floor') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Loại phòng:</span> {r.get('room_type') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Giá thuê:</span> {tu.format_money(r.get('price'))} ₫<br>
        <span style='color:#6B7280; font-weight:700;'>Tiền cọc:</span> {tu.format_money(r.get('deposit'))} ₫<br>
        <span style='color:#6B7280; font-weight:700;'>Diện tích:</span> {r.get('area') or '—'} m2<br>
        <span style='color:#6B7280; font-weight:700;'>Sức chứa:</span> {r.get('capacity') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Khảo sát:</span> {'✅ Đã khảo sát' if r.get('surveyed') else 'Chưa khảo sát'}<br>
        <span style='color:#6B7280; font-weight:700;'>Xe điện:</span> {'⚡ Có sạc' if r.get('ev_support') else 'Không'}<br>
        <span style='color:#6B7280; font-weight:700;'>Thú cưng:</span> {r.get('pet_policy') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>SĐT chủ nhà:</span> {r.get('owner_phone') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Zalo:</span> {r.get('zalo_group') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Drive:</span> {r.get('drive_link') or '—'}<br>
        <span style='color:#6B7280; font-weight:700;'>Ghi chú:</span> {r.get('notes') or '—'}<br>
        </div>
        <hr style='border:none; border-top:1px solid #E5E7EB; margin:12px 0;'>
        <span style='color:#9CA3AF; font-size:11px; font-weight:600;'>
          ID: {r.get('id')}<br>
          Cập nhật: {r.get('updated_at')} bởi {r.get('updated_by')}<br>
          Phiên bản: v{r.get('version')} · Đồng bộ: {r.get('sync_state')}
        </span>"""
        if r.get("needs_verify"):
            html += ("<br><span style='color:#F97316; font-weight:700;'>⚠ Thiếu số căn - "
                     "cần xác minh khoá nhận diện</span>")
        self.detail_body.setText(html)

        # nút hành động (đầy chiều rộng, bo tròn, hiện đại)
        for label, slot in (
            ("✏️ Sửa chi tiết", lambda: self._edit_room(rid)),
            ("📞 Gọi chủ nhà", lambda: self._call(rid)),
            ("💬 Mở Zalo", lambda: self._zalo(rid)),
            ("📁 Mở Drive", lambda: self._drive(rid)),
            ("🕘 Lịch sử trạng thái", lambda: self._history(rid)),
            ("🗑 Xóa phòng", lambda: self._delete(rid)),
        ):
            b = QPushButton(label)
            b.setMinimumHeight(40)
            if label.startswith("🗑"):
                b.setObjectName("Danger")
            else:
                b.setObjectName("Ghost")
            b.clicked.connect(slot)
            self.detail_actions.addWidget(b)

    # ------------------------------------------------------------------ hành động
    def _current_room_id(self) -> str:
        idx = self.table.currentIndex()
        return self.model.room_id_at(idx.row()) if idx.isValid() else ""

    def _add_room(self):
        from edit_form import RoomEditForm
        dlg = RoomEditForm(self.mgr, None, self)
        dlg.exec()
        self.refresh()

    def _edit_room(self, rid: str):
        from edit_form import RoomEditForm
        r = self.mgr.room(rid)
        if not r:
            return
        dlg = RoomEditForm(self.mgr, r, self)
        if dlg.exec():
            self.refresh()
            self._open_detail(rid)

    def _call(self, rid: str):
        from google_drive import open_phone
        r = self.mgr.room(rid)
        open_phone((r or {}).get("owner_phone", ""))

    def _zalo(self, rid: str):
        from google_drive import open_zalo
        r = self.mgr.room(rid)
        open_zalo((r or {}).get("zalo_group", ""))

    def _drive(self, rid: str):
        from google_drive import open_drive
        r = self.mgr.room(rid)
        open_drive((r or {}).get("drive_link", ""))

    def _history(self, rid: str):
        from PySide6.QtWidgets import QDialog, QTextBrowser, QDialogButtonBox
        r = self.mgr.room(rid) or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Lịch sử - {r.get('room_code', '')}")
        dlg.setMinimumSize(560, 380)
        v = QVBoxLayout(dlg)
        tb = QTextBrowser()
        recs = self.mgr.history(rid, 200)
        if not recs:
            tb.setPlainText("Chưa có thay đổi trạng thái nào.")
        else:
            lines = []
            for rec in recs:
                lines.append(f"{rec['changed_at']}  |  {status_label(rec['old_status'])} → "
                             f"{status_label(rec['new_status'])}  |  {rec['actor']}"
                             + (f"  |  {rec['note']}" if rec.get("note") else ""))
            tb.setPlainText("\n".join(lines))
        v.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        v.addWidget(bb)
        dlg.exec()

    def _delete(self, rid: str):
        r = self.mgr.room(rid) or {}
        if self.mgr.settings.get("confirm_delete", True):
            ans = QMessageBox.question(
                self, "Xóa phòng",
                f"Xóa mềm phòng <b>{r.get('room_code', '')}</b>?\n"
                f"(Vẫn khôi phục được từ dữ liệu - không mất lịch sử)")
            if ans != QMessageBox.Yes:
                return
        try:
            self.mgr.delete_room(rid)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không xóa được", str(e))
            return
        self.refresh()

    # ------------------------------------------------------------------ chọn nhiều / hoàn tác / sửa hàng loạt
    def _selected_ids(self) -> List[str]:
        idxs = self.table.selectionModel().selectedRows()
        return [self.model.room_id_at(i.row()) for i in idxs if i.isValid()]

    def _undo(self):
        """Hoàn tác thao tác gần nhất (Ctrl+Z)."""
        actor = self.mgr.settings.get("user_name") or ""
        res = self.mgr.undo_last(actor=actor)
        if res["ok"]:
            self.refresh()
            # toast qua thanh trạng thái
            mw = self.window()
            lbl = getattr(mw, "lbl_status", None)
            if lbl:
                lbl.setText(res["message"])
                QTimer.singleShot(3000, lambda: lbl.setText("Sẵn sàng"))
        else:
            QMessageBox.information(self, "Hoàn tác", res["message"])

    def _batch_edit(self):
        """Sửa nhiều phòng được chọn cùng 1 lúc (xác nhận + xem trước)."""
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "Sửa hàng loạt",
                                    "Vui lòng chọn ít nhất 1 dòng trong bảng (bấm Ctrl để chọn nhiều).")
            return
        dlg = _BatchEditDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        field, value = dlg.result()
        actor = self.mgr.settings.get("user_name") or "Admin"
        ok = fail = 0
        details: List[str] = []
        for rid in ids:
            try:
                if field == "status":
                    self.mgr.change_status(rid, value, actor=actor,
                                           note=f"Sửa hàng loạt ({len(ids)} phòng)")
                else:
                    self.mgr.update_room(rid, {field: value}, actor=actor,
                                         note=f"Sửa hàng loạt ({len(ids)} phòng)")
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                r = self.mgr.room(rid) or {}
                details.append(f"• {r.get('room_code', rid)}: {e}")
        self.refresh()
        msg = f"Đã sửa {ok}/{len(ids)} phòng" + (f", thất bại {fail}" if fail else "")
        if details:
            msg += "\n" + "\n".join(details[:10])
            if fail > 10:
                msg += f"\n... và {fail-10} dòng khác"
        QMessageBox.information(self, "Sửa hàng loạt", msg)

    # ------------------------------------------------------------------ context menu (giữ nguyên)
    def _context_menu(self, pos):
        rid = self._current_room_id()
        if not rid:
            return
        r = self.mgr.room(rid) or {}
        menu = QMenu(self)

        act_open = menu.addAction("✏️ Sửa chi tiết")
        menu.addSeparator()
        sub = menu.addMenu("⚡ Đổi trạng thái (không tạo ID mới)")
        for k in RoomStatus.ORDER:
            a = sub.addAction(f"{status_label(k)}")
            a.setData(k)
            if k == r.get("status"):
                a.setEnabled(False)
        menu.addSeparator()
        act_dup = menu.addAction("🧬 Nhân bản phòng")
        act_del = menu.addAction("🗑 Xóa phòng")
        act_hist = menu.addAction("🕘 Lịch sử trạng thái")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_open:
            self._edit_room(rid)
        elif chosen in sub.actions():
            self._change_status(rid, chosen.data())
        elif chosen is act_dup:
            try:
                self.mgr.duplicate_room(rid)
                self.refresh()
            except DuplicateError as e:
                self._show_duplicate(e)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Không nhân bản được", str(e))
        elif chosen is act_del:
            self._delete(rid)
        elif chosen is act_hist:
            self._history(rid)

    def _change_status(self, rid: str, new_status: str):
        """Đổi trạng thái nhanh - ID phòng GIỮ NGUYÊN, có ghi lịch sử."""
        try:
            r = self.mgr.change_status(rid, new_status)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không đổi được trạng thái", str(e))
            return
        self.status_changed.emit(r["id"], new_status)
        self.refresh()
        self._open_detail(rid)

    def _show_duplicate(self, err: DuplicateError):
        res = err.result
        ex = res.existing_room or {}
        msg = res.messages("\n")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Phát hiện trùng dữ liệu")
        box.setText("Dữ liệu trùng với bản ghi đang có trong hệ thống.")
        box.setInformativeText(msg)
        if ex.get("id"):
            box.addButton(f"Mở bản ghi cũ: {ex.get('room_code', '')}", QMessageBox.AcceptRole)
            box.addButton("Vẫn lưu bản mới", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        ret = box.exec()
        if ex.get("id") and ret == QMessageBox.AcceptRole:
            self.duplicate_open.emit(ex["id"])
            self.reset_filters()
            self.refresh()
            self._open_detail(ex["id"])


# ------------------------------------------------------------------ dialog sửa hàng loạt
class _BatchEditDialog(QDialog):
    """Chọn 1 trường + giá trị -> áp dụng cho nhiều phòng đã chọn."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sửa hàng loạt phòng")
        self.setMinimumWidth(420)
        self.field = None
        self.value = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.cb_field = QComboBox()
        self.cb_field.addItems([
            "Trạng thái (status)",
            "Giá thuê (price)",
            "Tiền cọc (deposit)",
            "Loại phòng (room_type)",
            "Sức chứa (capacity)",
            "Xe điện (ev_support)",
            "Thú cưng (pet_policy)",
        ])
        form.addRow("Trường cần sửa:", self.cb_field)

        self.ed_value = QLineEdit()
        self.ed_value.setPlaceholderText("Nhập giá trị mới...")
        self.cb_field.currentIndexChanged.connect(self._on_field_changed)
        self._on_field_changed(0)
        form.addRow("Giá trị mới:", self.ed_value)
        lay.addLayout(form)

        hint = QLabel(
            "<b>Lưu ý:</b> thay đổi sẽ áp dụng cho <b>tất cả</b> dòng bạn đã chọn trong bảng. "
            "Trạng thái sẽ ghi lịch sử tự động.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _on_field_changed(self, idx: int):
        placeholders = {
            0: "Ví dụ: rented, vacant, deposit, soon_vacant, new",
            1: "Ví dụ: 7000000 hoặc 7.5tr",
            2: "Ví dụ: 7000000",
            3: "Ví dụ: Phòng trọ, Studio, Căn chung cư",
            4: "Ví dụ: 2 Ng/2 Xe",
            5: "Ví dụ: 1 (có) / 0 (không)",
            6: "Ví dụ: Cho nuôi Chó / Không nuôi",
        }
        self.ed_value.setPlaceholderText(placeholders.get(idx, "Nhập giá trị..."))

    def _accept(self):
        field_keys = ["status", "price", "deposit", "room_type", "capacity",
                      "ev_support", "pet_policy"]
        self.field = field_keys[self.cb_field.currentIndex()]
        self.value = self.ed_value.text().strip()
        if not self.value:
            QMessageBox.warning(self, "Thiếu giá trị", "Vui lòng nhập giá trị mới.")
            return
        # validate nhanh
        if self.field == "status":
            from models import RoomStatus
            if RoomStatus.from_text(self.value) not in RoomStatus.LABEL:
                QMessageBox.warning(self, "Giá trị không hợp lệ",
                                    f"Trạng thái phải là một trong: {', '.join(RoomStatus.ORDER)}")
                return
        if self.field in ("price", "deposit"):
            import text_utils as tu
            if tu.normalize_price(self.value) is None:
                QMessageBox.warning(self, "Giá trị không hợp lệ",
                                    "Vui lòng nhập số tiền (ví dụ 7000000 hoặc 7.5tr).")
                return
        self.accept()

    def result(self):
        return self.field, self.value
