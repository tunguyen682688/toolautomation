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
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QScrollArea, QSpinBox,
    QSplitter, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

import text_utils as tu
from grouped_table import GroupedTableModel, group_row_size_hint, paint_group_row
from inventory_manager import DuplicateError
from media_panel import CoverPreview, MediaPanel
from models import ROOM_TABLE_COLUMNS, ROOM_TYPES, RoomFilter, RoomStatus
from theme import status_bg, status_color, status_label
import theme
from building_view import FlowLayout   # layout tự wrap - dùng cho toolbar responsive


# ------------------------------------------------------------------ delegate hiển thị
class RoomDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if paint_group_row(painter, option, index):
            return                       # đã vẽ hàng tiêu đề nhóm phường
        opt = QStyleOptionViewItem(option)
        col_key = ROOM_TABLE_COLUMNS[index.column()][0]
        if col_key == "status":
            st = index.model().data(index, Qt.UserRole) or ""
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
        gh = group_row_size_hint(option, index)
        if gh is not None:
            return gh
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 44))
        return s


# ------------------------------------------------------------------ model bảng
class RoomTableModel(GroupedTableModel):
    """Bảng phòng ảo hoá, có THÊM hàng tiêu đề nhóm theo phường."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._text = ""
        self._filter: Optional[RoomFilter] = None

    # --- data pipeline
    def set_query(self, text: str, f: Optional[RoomFilter]):
        self._text = text
        self._filter = f
        self.set_rows(self.mgr.rooms(text, f))

    def refresh(self):
        self.set_query(self._text, self._filter)

    # --- map dòng hiển thị -> dữ liệu (qua hàng nhóm)
    def room_at(self, row: int) -> Optional[Dict[str, Any]]:
        return self.data_row_at(row)

    def room_id_at(self, row: int) -> str:
        r = self.room_at(row)
        return r["id"] if r else ""

    # --- GroupedTableModel
    def columns(self):
        return ROOM_TABLE_COLUMNS

    def right_align_keys(self):
        return {"price", "deposit"}

    def group_key_of(self, row):
        return tu.canon_ward(row.get("ward"))

    def group_title_of(self, key, rows):
        if not key:
            return "📍 Chưa ghi phường"
        d = str(rows[0].get("district") or "").strip()
        return f"📍 P.{key}" + (f"  ·  {d}" if d else "")

    def group_meta_of(self, key, rows):
        n = len(rows)
        vac = sum(1 for r in rows if r.get("status") == "vacant")
        return f"{n} phòng · {vac} trống"

    def cell_flags(self, col_key):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if col_key in ("status", "price", "deposit", "room_code", "room_type"):
            f |= Qt.ItemIsEditable
        return f

    def cell_data(self, r, key, role):
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
        if key in ("house_number", "street", "ward", "district"):
            return v or "—"
        return str(v) if v not in (None, "") else ""

    def cell_set(self, r, key, value):
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
    open_building = Signal(str)           # mở trang Tòa nhà & chọn tòa của phòng này

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

        # ---- hàng nút thao tác (tiêu đề trang đã có trên TopBar - không lặp lại) ----
        head = QFrame()
        head.setObjectName("Card")
        head.setStyleSheet("QFrame#Card { background: transparent; border: none; border-radius: 0; }")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 8, 22, 6)
        hl.setSpacing(0)
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

        # nút ẩn/hiện panel chi tiết (responsive: nhường chỗ cho bảng khi màn hẹp)
        self.btn_toggle_detail = QPushButton("⟨⟩ Chi tiết")
        self.btn_toggle_detail.setObjectName("Ghost")
        self.btn_toggle_detail.setToolTip("Ẩn/hiện panel chi tiết phòng")
        self.btn_toggle_detail.setCheckable(True)
        self.btn_toggle_detail.setChecked(True)
        self.btn_toggle_detail.toggled.connect(self._toggle_detail)
        hl.addWidget(self.btn_toggle_detail)
        lay.addWidget(head)

        # ============================ BỘ LỌC (2 hàng, không bị tràn) ============================
        bar = QFrame()
        bar.setObjectName("Toolbar")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(22, 8, 22, 8)
        bl.setSpacing(8)

        # Hàng 1: bộ lọc chính - FlowLayout TỰ WRAP khi cửa sổ hẹp (responsive)
        row1 = FlowLayout(bar, 10, 6)

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

        self.cmb_district = QComboBox()
        self.cmb_district.addItem("Tất cả khu vực", None)
        self.cmb_district.currentIndexChanged.connect(self._district_changed)
        row1.addWidget(self.cmb_district)

        self.cmb_ward = QComboBox()
        self.cmb_ward.addItem("Tất cả phường", None)
        self.cmb_ward.currentIndexChanged.connect(self._ward_changed)
        row1.addWidget(self.cmb_ward)

        self.cmb_building = QComboBox()
        self.cmb_building.addItem("Tất cả tòa nhà", None)
        self.cmb_building.setMinimumWidth(190)
        self.cmb_building.currentIndexChanged.connect(self._apply_filter)
        row1.addWidget(self.cmb_building)

        self.chk_group = QCheckBox("🏘 Phân cụm phường")
        self.chk_group.setChecked(True)
        self.chk_group.setToolTip(
            "Gộp danh sách theo từng PHƯỜNG: mỗi phường một hàng tiêu đề\n"
            "«📍 P.xx · quận · N phòng · X trống» nằm trên đầu cụm dòng.")
        self.chk_group.toggled.connect(self._apply_filter)
        row1.addWidget(self.chk_group)

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

        # ---- TÌM THEO YÊU CẦU KHÁCH: dán câu khách hỏi -> 4 vòng mở rộng khu vực ----
        self.btn_request = QPushButton("🎯 Yêu cầu khách")
        self.btn_request.setToolTip(
            "Dán nguyên câu khách hỏi (giá / tiện ích / khu vực)\n"
            "VD: phòng 7tr full nội thất thang máy, gửi xe, quanh P13 hay đường Bình Lợi\n"
            "-> tự tách tiêu chí và tìm theo 4 vòng: đúng khu vực → lân cận → giáp ranh → toàn kho")
        self.btn_request.setCursor(Qt.PointingHandCursor)
        row2.addWidget(self.btn_request)

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
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)     # cột tên đường co giãn
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda idx: self._open_detail(self.model.room_id_at(idx.row())))
        split.addWidget(self.table)

        # Panel chi tiết (bên phải) - cấu trúc WIDGET, cuộn được, không tràn
        detail = QFrame()
        detail.setObjectName("DetailPanel")
        detail.setMinimumWidth(340)
        detail.setMaximumWidth(480)
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)

        # ---------- HEADER: mã phòng + badge trạng thái + đổi nhanh ----------
        phead = QFrame()
        phead.setStyleSheet("background:transparent; border:none;")
        phl = QVBoxLayout(phead)
        phl.setContentsMargins(20, 16, 20, 12)
        phl.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        dt = QLabel("Chi tiết phòng")
        dt.setObjectName("SectionTitle")
        top_row.addWidget(dt)
        top_row.addStretch(1)
        self.d_status = QLabel("")
        self.d_status.setAlignment(Qt.AlignCenter)
        self.d_status.setFixedHeight(24)
        self.d_status.setStyleSheet(
            "border-radius:12px; padding:2px 12px; font-weight:800; font-size:12px;")
        top_row.addWidget(self.d_status)
        phl.addLayout(top_row)

        self.d_code = QLabel("—")
        self.d_code.setStyleSheet(
            "font-size:22px; font-weight:800; background:transparent; letter-spacing:-0.5px;")
        phl.addWidget(self.d_code)

        self.d_sub = QLabel("")
        self.d_sub.setObjectName("Muted")
        self.d_sub.setWordWrap(True)
        phl.addWidget(self.d_sub)

        # ---- điều khiển nhanh trên 3 hàng: đổi trạng thái + khảo sát ----
        qs_grid = QGridLayout()
        qs_grid.setContentsMargins(0, 0, 0, 0)
        qs_grid.setHorizontalSpacing(12)
        qs_grid.setVerticalSpacing(8)
        # cột combo (lẻ) co giãn để chứa chữ tiếng Việt dài
        qs_grid.setColumnStretch(1, 1)
        qs_grid.setColumnStretch(3, 1)

        self.survey_combos = {}

        # Hàng 0: Đổi trạng thái | Khảo sát
        lbl_qs = QLabel("Đổi trạng thái:")
        lbl_qs.setObjectName("Muted")
        lbl_qs.setStyleSheet("font-size:11px; font-weight:700; background:transparent;")
        qs_grid.addWidget(lbl_qs, 0, 0)
        self.cmb_d_status = QComboBox()
        for k in RoomStatus.ORDER:
            self.cmb_d_status.addItem(f"● {RoomStatus.label(k)}", k)
        self.cmb_d_status.currentIndexChanged.connect(self._quick_status)
        qs_grid.addWidget(self.cmb_d_status, 0, 1)

        lbl_survey = QLabel("Khảo sát:")
        lbl_survey.setObjectName("Muted")
        lbl_survey.setStyleSheet("font-size:11px; font-weight:700; background:transparent;")
        qs_grid.addWidget(lbl_survey, 0, 2)
        cmb = QComboBox()
        cmb.addItem("— Chưa biết —", None)
        cmb.addItem("✅ Có", True)
        cmb.addItem("❌ Không", False)
        cmb.setMinimumWidth(115)
        cmb.setObjectName("Ghost")
        cmb.currentIndexChanged.connect(lambda _, f="surveyed": self._quick_survey(f))
        qs_grid.addWidget(cmb, 0, 3)
        self.survey_combos["surveyed"] = cmb

        # Hàng 1: Xe điện | Khách NNGO
        items_row1 = [
            ("ev_support", "Xe điện", False),
            ("foreign_guest", "Khách NNGO", False),
        ]
        for col, key, label, is_rating in ((0, *items_row1[0]), (2, *items_row1[1])):
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            lbl.setStyleSheet("font-size:11px; font-weight:700; background:transparent;")
            qs_grid.addWidget(lbl, 1, col)
            cmb = QComboBox()
            cmb.addItem("— Chưa biết —", None)
            cmb.addItem("✅ Có", True)
            cmb.addItem("❌ Không", False)
            cmb.setMinimumWidth(115)
            cmb.setObjectName("Ghost")
            cmb.currentIndexChanged.connect(lambda _, f=key: self._quick_survey(f))
            qs_grid.addWidget(cmb, 1, col + 1)
            self.survey_combos[key] = cmb

        # Hàng 2: Pet | Đánh giá
        items_row2 = [
            ("pet_policy", "Pet", False),
            ("rating", "Đánh giá", True),
        ]
        for col, key, label, is_rating in ((0, *items_row2[0]), (2, *items_row2[1])):
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            lbl.setStyleSheet("font-size:11px; font-weight:700; background:transparent;")
            qs_grid.addWidget(lbl, 2, col)
            cmb = QComboBox()
            cmb.addItem("— Chưa biết —", None)
            if is_rating:
                for stars in range(1, 6):
                    cmb.addItem("★" * stars + f" ({stars} sao)", stars)
            else:
                cmb.addItem("✅ Có", True)
                cmb.addItem("❌ Không", False)
            cmb.setMinimumWidth(115)
            cmb.setObjectName("Ghost")
            cmb.currentIndexChanged.connect(lambda _, f=key: self._quick_survey(f))
            qs_grid.addWidget(cmb, 2, col + 1)
            self.survey_combos[key] = cmb

        phl.addLayout(qs_grid)
        dl.addWidget(phead)

        # ---------- NỘI DUNG CUỘN: chỉ số + chip + thông tin + vị trí ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 4, 20, 8)
        cl.setSpacing(10)

        # ---- SƠ LƯỢC ẢNH: ảnh đại diện phòng (biết ngay ảnh trông như nào) ----
        self.cover = CoverPreview(self.mgr)
        cl.addWidget(self.cover)

        # 3 ô chỉ số: Giá / Cọc / Diện tích
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.d_price_fx, self.d_price_val = self._metric_box("Giá thuê")
        self.d_dep_fx, self.d_dep_val = self._metric_box("Tiền cọc")
        self.d_area_fx, self.d_area_val = self._metric_box("Diện tích")
        for fx in (self.d_price_fx, self.d_dep_fx, self.d_area_fx):
            mrow.addWidget(fx, 1)
        cl.addLayout(mrow)

        # chip tiện ích (ẩn khi không áp dụng)
        crow = QHBoxLayout()
        crow.setSpacing(6)
        self.d_chip_ks = self._chip_lbl("📸 Đã khảo sát")
        self.d_chip_ev = self._chip_lbl("⚡ Xe điện")
        self.d_chip_fg = self._chip_lbl("🌏 Khách nước ngoài")
        self.d_chip_pet = self._chip_lbl("🐾 Pet")
        for c in (self.d_chip_ks, self.d_chip_ev, self.d_chip_fg, self.d_chip_pet):
            crow.addWidget(c)
        crow.addStretch(1)
        cl.addLayout(crow)

        # ---- ẢNH / VIDEO: quản lý file cục bộ theo thư mục quy ước
        #      Data Image/<Quận>/<Đường>/<số nhà>-<mã phòng>/<loại> <giá>tr ----
        self.media_panel = MediaPanel(self.mgr)
        cl.addWidget(self.media_panel)

        # thông tin phòng
        inf = QLabel("THÔNG TIN")
        inf.setStyleSheet(f"color:{theme.c('text3')}; font-size:11px; font-weight:800; "
                          "background:transparent; letter-spacing:0.5px;")
        cl.addWidget(inf)
        self.d_info = QLabel("—")
        self.d_info.setTextFormat(Qt.RichText)
        self.d_info.setWordWrap(True)
        self.d_info.setStyleSheet("background:transparent; line-height:170%;")
        cl.addWidget(self.d_info)

        # vị trí (tách riêng số nhà/đường/phường/quận + mã tòa)
        vt = QLabel("VỊ TRÍ")
        vt.setStyleSheet(f"color:{theme.c('text3')}; font-size:11px; font-weight:800; "
                         "background:transparent; letter-spacing:0.5px;")
        cl.addWidget(vt)
        self.d_addr = QLabel("—")
        self.d_addr.setTextFormat(Qt.RichText)
        self.d_addr.setWordWrap(True)
        self.d_addr.setStyleSheet("background:transparent; line-height:170%;")
        cl.addWidget(self.d_addr)

        # meta (ID / cập nhật / phiên bản)
        self.d_meta = QLabel("")
        self.d_meta.setWordWrap(True)
        self.d_meta.setStyleSheet(f"color:{theme.c('text3')}; font-size:11px; font-weight:600; "
                                  "background:transparent; line-height:150%;")
        cl.addWidget(self.d_meta)
        cl.addStretch(1)
        scroll.setWidget(content)
        dl.addWidget(scroll, 1)

        # ---------- NÚT HÀNH ĐỘNG (cố định dưới) ----------
        self.detail_actions = QHBoxLayout()
        self.detail_actions.setContentsMargins(20, 8, 20, 16)
        self.detail_actions.setSpacing(6)
        dl.addLayout(self.detail_actions)
        split.addWidget(detail)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        self._splitter = split          # dùng cho ẩn/hiện panel (responsive)
        self._detail_panel = detail
        # vùng bảng lọt trong khung padding - không dính mép cửa sổ (khớp toolbar 22px)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(22, 6, 22, 12)
        blay.addWidget(split)
        lay.addWidget(body, 1)

        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, prev: self._open_detail(self.model.room_id_at(cur.row()) if cur.isValid() else ""))

        # tải danh sách tòa nhà vào bộ lọc
        self._load_buildings()

    def _load_buildings(self, district: Optional[str] = None):
        """Đổ KHU VỰC + PHƯỜNG + danh sách tòa nhà vào combobox lọc.

        - Combobox khu vực: các quận đang có tòa (gộp 'Q. Bình Thạnh cũ' = 'Q. Bình Thạnh').
        - Combobox phường: các phường thuộc khu vực đang chọn (phụ thuộc district).
        - Combobox tòa: chỉ hiện tòa thuộc khu vực + phường đang chọn.
        Giữ nguyên lựa chọn hiện tại nếu vẫn còn hợp lệ.
        """
        cur_district = district if district is not None else self.cmb_district.currentData()
        cur_ward = self.cmb_ward.currentData()
        cur_building = self.cmb_building.currentData()

        try:
            buildings = self.mgr.buildings()
        except Exception:  # noqa: BLE001
            buildings = []

        # ---- gom khu vực: key = canon_district, display = tên hay gặp nhất
        zone_display: Dict[str, str] = {}
        zone_count: Dict[str, int] = {}
        for b in buildings:
            raw = str(b.get("district") or "").strip()
            if not raw:
                continue
            k = tu.canon_district(raw)
            if not k:
                continue
            zone_count[k] = zone_count.get(k, 0) + 1
            if k not in zone_display:
                zone_display[k] = raw
            elif zone_count[k] > 0 and len(raw) < len(zone_display[k]):
                zone_display[k] = raw   # ưu tiên tên ngắn gọn ("Q. Bình Thạnh" hơn "... cũ")

        # ---- combobox khu vực
        self.cmb_district.blockSignals(True)
        self.cmb_district.clear()
        self.cmb_district.addItem("Tất cả khu vực", None)
        for k in sorted(zone_display, key=lambda x: -zone_count[x]):
            self.cmb_district.addItem(f"📍 {zone_display[k]}  ({zone_count[k]} tòa)", zone_display[k])
        idx = self.cmb_district.findData(cur_district)
        self.cmb_district.setCurrentIndex(max(0, idx))
        self.cmb_district.blockSignals(False)

        # ---- combobox phường (thuộc khu vực đang chọn)
        sel_district = self.cmb_district.currentData()
        ward_display: Dict[str, str] = {}
        ward_count: Dict[str, int] = {}
        for b in buildings:
            if sel_district and tu.canon_district(b.get("district")) != tu.canon_district(sel_district):
                continue
            raw_w = str(b.get("ward") or "").strip()
            if not raw_w:
                continue
            kw = tu.canon_ward(raw_w)
            if not kw:
                continue
            ward_count[kw] = ward_count.get(kw, 0) + 1
            if kw not in ward_display or len(raw_w) < len(ward_display[kw]):
                ward_display[kw] = raw_w
        self.cmb_ward.blockSignals(True)
        self.cmb_ward.clear()
        self.cmb_ward.addItem("Tất cả phường", None)
        for kw in sorted(ward_display, key=lambda x: -ward_count[x]):
            self.cmb_ward.addItem(f"🏷️ {ward_display[kw]}  ({ward_count[kw]} tòa)", ward_display[kw])
        idx = self.cmb_ward.findData(cur_ward)
        self.cmb_ward.setCurrentIndex(max(0, idx))
        self.cmb_ward.blockSignals(False)

        # ---- combobox tòa (lọc theo khu vực + phường đang chọn)
        sel_district = self.cmb_district.currentData()
        sel_ward = self.cmb_ward.currentData()
        self.cmb_building.blockSignals(True)
        self.cmb_building.clear()
        self.cmb_building.addItem("Tất cả tòa nhà", None)
        for b in buildings:
            if sel_district and tu.canon_district(b.get("district")) != tu.canon_district(sel_district):
                continue
            if sel_ward and tu.canon_ward(b.get("ward")) != tu.canon_ward(sel_ward):
                continue
            self.cmb_building.addItem(f"{b.get('code','')} — {b.get('display','')}", b["id"])
        idx = self.cmb_building.findData(cur_building)
        self.cmb_building.setCurrentIndex(max(0, idx))
        self.cmb_building.blockSignals(False)

    def _district_changed(self, *_):
        """Đổi khu vực -> làm mới phường + tòa theo khu vực + lọc phòng."""
        self._load_buildings(district=self.cmb_district.currentData())
        self._apply_filter()

    def _ward_changed(self, *_):
        """Đổi phường -> làm mới danh sách tòa theo phường + lọc phòng."""
        self._load_buildings(district=self.cmb_district.currentData())
        self._apply_filter()

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
            widgets = [self.cmb_status, self.cmb_type, self.cmb_district, self.cmb_ward,
                       self.cmb_building,
                       self.chk_ev, self.chk_foreign,
                       self.chk_pet,
                       self.chk_unsurvey, self.chk_deleted, self.spin_min, self.spin_max]
            for w in widgets:
                w.blockSignals(True)
            i = self.cmb_status.findData(st)
            self.cmb_status.setCurrentIndex(max(0, i))
            i = self.cmb_type.findData((self._filter.room_types or [None])[0])
            self.cmb_type.setCurrentIndex(max(0, i))
            i = self.cmb_district.findData(self._filter.district)
            self.cmb_district.setCurrentIndex(max(0, i))
            i = self.cmb_ward.findData(self._filter.ward)
            self.cmb_ward.setCurrentIndex(max(0, i))
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
        district = self.cmb_district.currentData()
        ward = self.cmb_ward.currentData()
        return RoomFilter(
            building_id=building_id,
            district=district,
            ward=ward,
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
        self.model.set_grouped(self.chk_group.isChecked())
        n = self.model.data_row_count()
        self.lbl_count.setText(f"{n} phòng" + (f" · «{self._title}»" if self._title != "Tất cả phòng" else ""))

    def reset_filters(self):
        self._filter = RoomFilter()
        self._title = "Tất cả phòng"
        self.cmb_status.setCurrentIndex(0)
        self.cmb_type.setCurrentIndex(0)
        self.cmb_district.setCurrentIndex(0)
        self.cmb_ward.setCurrentIndex(0)
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
    def _metric_box(self, title: str):
        """Ô chỉ số nhỏ (Giá/Cọc/Diện tích). Trả về (frame, label_giá_trị)."""
        fx = QFrame()
        fx.setStyleSheet(
            f"QFrame {{ background:{theme.c('card2')};"
            f" border:1px solid {theme.c('border')}; border-radius:10px; }}")
        v = QVBoxLayout(fx)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"color:{theme.c('text2')}; font-size:11px; font-weight:700;"
                        " background:transparent; border:none;")
        val = QLabel("—")
        val.setStyleSheet(f"color:{theme.c('accent')}; font-size:13.5px; font-weight:800; "
                          "background:transparent; border:none;")
        val.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(val)
        return fx, val

    def _chip_lbl(self, text: str) -> QLabel:
        """Chip nhỏ hiển thị tiện ích (📸/⚡/🌏/🐾)."""
        c = QLabel(text)
        c.setAlignment(Qt.AlignCenter)
        c.setFixedHeight(24)
        c.setStyleSheet(
            f"background:{theme.c('ok_soft')}; color:{theme.c('ok')};"
            f" border:1px solid {theme.c('ok')}33;"
            "border-radius:12px; padding:2px 10px; font-size:11.5px; font-weight:700;")
        return c

    def _reset_detail_empty(self, msg: str):
        """Trạng thái panel khi chưa chọn phòng / không tìm thấy."""
        self.d_code.setText("—")
        self.d_status.setText("●")
        self.d_status.setStyleSheet(
            f"background:{theme.c('card2')}; color:{theme.c('text2')};"
            f" border:1px solid {theme.c('border')}; border-radius:12px; padding:2px 12px; "
            "font-weight:800; font-size:12px;")
        self.d_sub.setText(msg)
        self.d_price_val.setText("—")
        self.d_dep_val.setText("—")
        self.d_area_val.setText("—")
        for chip in (self.d_chip_ks, self.d_chip_ev, self.d_chip_fg, self.d_chip_pet):
            chip.hide()
        self.d_info.setText("—")
        self.d_addr.setText("—")
        self.d_meta.setText("")
        self.media_panel.set_room(None)
        self.cover.set_room(None)
        self.cmb_d_status.blockSignals(True)
        self.cmb_d_status.setCurrentIndex(0)
        self.cmb_d_status.setEnabled(False)
        self.cmb_d_status.blockSignals(False)
        for cmb in self.survey_combos.values():
            cmb.blockSignals(True)
            cmb.setCurrentIndex(0)
            cmb.blockSignals(False)

    def _open_detail(self, rid: str):
        self._current_detail_id = rid
        # dọn nút cũ
        while self.detail_actions.count():
            item = self.detail_actions.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not rid:
            self._reset_detail_empty("Chọn một dòng trong bảng để xem chi tiết.")
            return
        r = self.mgr.room(rid)
        if not r:
            self._reset_detail_empty("Không tìm thấy phòng (có thể đã xóa).")
            return

        st = r.get("status", "")
        # ---- header: mã + badge trạng thái + dòng phụ
        self.d_code.setText(r.get("room_code") or "(chưa có mã)")
        self.d_status.setText(f"● {status_label(st)}")
        self.d_status.setStyleSheet(
            f"background:{status_bg(st)}; color:{status_color(st)}; border-radius:12px; "
            "padding:2px 12px; font-weight:800; font-size:12px;")
        sub_parts = [x for x in (f"🏢 {r.get('building_code')}" if r.get("building_code") else "",
                                 r.get("room_type") or "") if x]
        self.d_sub.setText("  ·  ".join(sub_parts) if sub_parts else "—")

        # ---- đổi trạng thái nhanh (chặn signal để không tự gọi lại)
        self.cmb_d_status.setEnabled(True)
        self.cmb_d_status.blockSignals(True)
        i = self.cmb_d_status.findData(st)
        self.cmb_d_status.setCurrentIndex(max(0, i))
        self.cmb_d_status.blockSignals(False)

        # ---- 3 ô chỉ số
        self.d_price_val.setText(f"{tu.format_money(r.get('price'))} ₫")
        self.d_dep_val.setText(f"{tu.format_money(r.get('deposit'))} ₫")
        self.d_area_val.setText(f"{r.get('area') or '—'} m2")

        # ---- chip tiện ích
        self.d_chip_ks.setVisible(bool(r.get("surveyed")))
        self.d_chip_ev.setVisible(bool(r.get("ev_support")))
        self.d_chip_fg.setVisible(bool(r.get("foreign_guest")))
        pet = r.get("pet_policy") or ""
        self.d_chip_pet.setVisible(bool(pet))
        if pet:
            self.d_chip_pet.setText(f"🐾 {pet}")

        # ---- đồng bộ combo khảo sát (Có/Không/Chưa biết) ----
        self._sync_survey_combos(r)

        # ---- thông tin phòng
        from html import escape

        def esc(v):
            return escape(str(v)) if v not in (None, "") else "—"
        info_rows = [
            ("Số căn", r.get("unit_code")),
            ("Tầng", r.get("floor")),
            ("Sức chứa", r.get("capacity")),
            ("Đánh giá", r.get("rating")),
            ("Ghi chú", r.get("notes")),
        ]
        self.d_info.setText(
            "<div style='font-size:12.5px;'>"
            + "".join(f"<div style='margin:3px 0;'>"
                      f"<span style='color:{theme.c('text2')}; font-weight:700;'>{k}: </span>"
                      f"<span style='color:{theme.c('text')};'>{esc(v)}</span></div>"
                      for k, v in info_rows)
            + (f"<div style='margin-top:6px; color:{theme.c('orange')}; font-weight:700;'>"
               f"⚠ Thiếu số căn - cần xác minh khoá nhận diện</div>" if r.get("needs_verify") else "")
            + "</div>")

        # ---- vị trí (tách riêng từng thành phần)
        addr_rows = [
            ("Số nhà", r.get("house_number")),
            ("Tên đường", r.get("street")),
            ("Phường", r.get("ward")),
            ("Quận / Khu vực", r.get("district")),
        ]
        full = r.get("address") or ""
        self.d_addr.setText(
            "<div style='font-size:12.5px;'>"
            f"<div style='margin-bottom:4px; color:{theme.c('text')}; font-weight:600;'>{esc(full)}</div>"
            + "".join(f"<div style='margin:2px 0;'>"
                      f"<span style='color:{theme.c('text2')}; font-weight:700;'>{k}: </span>"
                      f"<span style='color:{theme.c('text')};'>{esc(v)}</span></div>"
                      for k, v in addr_rows)
            + "</div>")

        # ---- meta
        self.d_meta.setText(
            f"ID: {r.get('id')}\n"
            f"Cập nhật: {r.get('updated_at')} bởi {r.get('updated_by')}\n"
            f"Phiên bản: v{r.get('version')} · Đồng bộ: {r.get('sync_state')}")

        # ---- Ảnh / Video của phòng (đọc từ thư mục quy ước)
        self.cover.set_room(r)
        self.media_panel.set_room(r)

        # nút hành động: hàng ngang, chỉ icon + tooltip (Sửa - Primary, Xóa - Danger, còn lại DetailAction)
        bid = r.get("building_id", "")
        btn_defs = [
            ("✏️", "Sửa chi tiết phòng", "Primary", lambda: self._edit_room(rid)),
            ("🏢", "Xem chi tiết tòa nhà", "DetailAction", lambda: self.open_building.emit(bid)),
            ("📞", "Gọi điện chủ nhà", "DetailAction", lambda: self._call(rid)),
            ("💬", "Mở nhóm Zalo chủ nhà", "DetailAction", lambda: self._zalo(rid)),
            ("📁", "Mở Google Drive", "DetailAction", lambda: self._drive(rid)),
            ("🕘", "Xem lịch sử trạng thái", "DetailAction", lambda: self._history(rid)),
            ("🗑", "Xóa phòng (thùng rác)", "Danger", lambda: self._delete(rid)),
        ]
        for icon, tooltip, objname, slot in btn_defs:
            b = QToolButton()
            b.setText(icon)
            b.setToolTip(tooltip)
            b.setObjectName(objname)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setFixedSize(44, 44)
            b.clicked.connect(slot)
            self.detail_actions.addWidget(b)
        self.detail_actions.addStretch(1)

    def _quick_status(self, *_):
        """Đổi trạng thái nhanh ngay trong panel (không cần mở form)."""
        rid = getattr(self, "_current_detail_id", "")
        if not rid:
            return
        new_st = self.cmb_d_status.currentData()
        r = self.mgr.room(rid) or {}
        if not r or r.get("status") == new_st:
            return
        try:
            self.mgr.change_status(
                rid, new_st,
                actor=self.mgr.settings.get("user_name") or "Admin",
                note="Đổi nhanh từ panel chi tiết")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không đổi được trạng thái", str(e))
            return
        self.status_changed.emit(rid, new_st)
        self.refresh()
        self._open_detail(rid)

    def _quick_survey(self, field: str):
        """Đổi nhanh trường khảo sát (Có/Không/Chưa biết) ngay trong panel."""
        rid = getattr(self, "_current_detail_id", "")
        if not rid:
            return
        cmb = self.survey_combos.get(field)
        if not cmb:
            return
        val = cmb.currentData()
        r = self.mgr.room(rid) or {}
        if not r:
            return
        # giá trị hiện tại
        cur = r.get(field)
        if field == "pet_policy":
            # pet_policy lưu chuỗi "Cho nuôi"/"Không nuôi"/""
            cur_norm = "Cho nuôi" if r.get("pet_ok") else ("Không nuôi" if cur else "")
            new_val = "Cho nuôi" if val is True else ("Không nuôi" if val is False else "")
            if new_val == cur_norm:
                return
            changes = {field: new_val}
            note = f"Khảo sát nhanh {field} -> {new_val or 'chưa biết'}"
        else:
            # surveyed / ev_support / foreign_guest: None|0|1
            cur_norm = bool(cur) if cur is not None else None
            if bool(val) == cur_norm:
                return
            changes = {field: val}
            note = f"Khảo sát nhanh {field} -> {'Có' if val is True else ('Không' if val is False else 'chưa biết')}"
        if field == "rating":
            try:
                cur_val = int(r.get("rating") or 0)
            except (TypeError, ValueError):
                cur_val = 0
            if val is None:
                new_val = None
            else:
                try:
                    new_val = int(val)
                except (TypeError, ValueError):
                    new_val = None
            if new_val == cur_val:
                return
            changes = {"rating": new_val}
            note = f"Khảo sát nhanh đánh giá -> {new_val if new_val else 'chưa biết'} sao"
        try:
            self.mgr.update_room(
                rid, changes,
                actor=self.mgr.settings.get("user_name") or "Admin",
                note=note)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không cập nhật được", str(e))
            return
        self.refresh()
        self._open_detail(rid)

    def _sync_survey_combos(self, r: Dict[str, Any]):
        """Đặt lại combo khảo sát theo dữ liệu phòng (chặn signal)."""
        for field, cmb in self.survey_combos.items():
            cmb.blockSignals(True)
            if field == "pet_policy":
                pet = r.get("pet_policy") or ""
                idx = 1 if pet == "Cho nuôi" else (2 if pet == "Không nuôi" else 0)
            elif field == "rating":
                try:
                    val = int(r.get("rating") or 0)
                except (TypeError, ValueError):
                    val = 0
                idx = val + 1 if 1 <= val <= 5 else 0
            else:
                v = r.get(field)
                idx = 1 if v is True else (2 if v is False else 0)
            cmb.setCurrentIndex(idx)
            cmb.blockSignals(False)

    # ------------------------------------------------------------------ hành động
    def _toggle_detail(self, show: bool):
        """Ẩn/hiện panel chi tiết (responsive: nhường chỗ cho bảng khi cửa sổ hẹp)."""

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
            self._load_buildings()   # địa chỉ có thể đổi -> tạo tòa mới -> cập nhật combobox
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
