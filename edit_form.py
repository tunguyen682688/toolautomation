# -*- coding: utf-8 -*-
"""edit_form.py - Biểu mẫu Thêm / Sửa phòng hiện đại.

Tính năng:
- Giao diện thẻ (card), bố cục cân đối 2 cột, màu sắc hiện đại.
- Hệ thống gợi ý trùng lặp real-time (debounce 350ms): hiện phòng trùng +
  nút "Mở bản ghi cũ" ngay TRƯỚC khi bấm Lưu.
- Tự điền chủ nhà / SĐT / Zalo / chính sách khi chọn địa chỉ tòa đã có.
- Nháp tự động: nhập dở tắt app -> mở lại hỏi khôi phục.
- Nút Lưu / Lưu & thêm tiếp.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import json

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QPixmap, QStandardItem,
                           QStandardItemModel)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QCompleter,
)

import media_manager as mm
import text_utils as tu
import theme
from inventory_manager import DuplicateError
from models import ROOM_TYPES, RoomStatus
from theme import C_ACCENT, C_ACCENT_HOVER, C_DANGER, C_OK, C_ORANGE, \
    status_color, status_label

import text_utils as tu
import theme
from inventory_manager import DuplicateError
from models import ROOM_TYPES, RoomStatus
from theme import C_ACCENT, C_ACCENT_HOVER, C_DANGER, C_OK, C_ORANGE, \
    status_color, status_label

GROUP_TITLES = [
    "1. Địa chỉ tòa nhà",
    "2. Nhận diện căn hộ",
    "3. Giá thuê & tiền cọc",
    "4. Tiện ích & sức chứa",
    "5. Chính sách (xe điện / thú cưng / nước ngoài)",
    "6. Liên hệ chủ nhà / Zalo",
    "7. Media (Drive) & đánh giá",
    "8. Ghi chú & trạng thái",
]

# Màu đại diện cho mức độ nghi ngờ trùng (gọi lúc dùng -> đúng chế độ giao diện hiện tại)
def severity_color(level: str) -> str:
    return {"block": theme.c("danger"), "warn": theme.c("orange"),
            "info": theme.c("ok")}.get(level, theme.c("text2"))


SEVERITY_COLORS = {  # giữ tên cũ cho tương thích (dùng lúc import -> chỉ đúng ở lần mở đầu)
    "block": C_DANGER,
    "warn": C_ORANGE,
    "info": C_OK,
}


# ------------------------------------------------------------------ widget chọn sao (1-5)
class StarRating(QWidget):
    """Chọn sao đánh giá 1-5 sao, bật/tắt bằng click."""

    changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._stars: List[QLabel] = []
        for i in range(1, 6):
            lbl = QLabel("☆")
            lbl.setObjectName("Star")
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setFixedSize(22, 22)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-size:18px; color:#CBD5E1; background:transparent;")
            lbl.mousePressEvent = lambda ev, n=i: self._set(n)
            self._stars.append(lbl)
            lay.addWidget(lbl)
        lay.addStretch(1)
        self._refresh()

    def _set(self, n: int):
        self._value = n if self._value != n else 0
        self._refresh()
        self.changed.emit(self._value)

    def _refresh(self):
        for i, lbl in enumerate(self._stars, 1):
            lbl.setText("★" if i <= self._value else "☆")
            lbl.setStyleSheet(
                f"font-size:18px; color:{'#FBBF24' if i <= self._value else '#CBD5E1'};"
                " background:transparent;")

    def value(self) -> int:
        return self._value

    def set_value(self, n: int):
        self._value = max(0, min(5, int(n or 0)))
        self._refresh()


# ------------------------------------------------------------------ widget upload ảnh trong form
class ImageUpload(QWidget):
    """Chọn ảnh phòng, hiển thị thumbnail."""

    files_changed = Signal(list)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._paths: List[str] = []
        self.setFixedHeight(110)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(72, 72))
        self.list.setFixedHeight(96)
        self.list.setSpacing(6)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._ctx)
        lay.addWidget(self.list)

        row = QHBoxLayout()
        btn_add = QPushButton("＋ Thêm ảnh")
        btn_add.setObjectName("Chip")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.clicked.connect(self._add)
        row.addWidget(btn_add)
        btn_clear = QPushButton("🗑 Xóa tất cả")
        btn_clear.setObjectName("Danger")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self._clear)
        row.addWidget(btn_clear)
        row.addStretch(1)
        lay.addLayout(row)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh phòng", "",
            "Ảnh (*.jpg *.jpeg *.png *.webp *.bmp);;Tất cả file (*.*)")
        self._paths.extend(files)
        self._refresh()
        self.files_changed.emit(self._paths)

    def _clear(self):
        self._paths.clear()
        self.list.clear()

    def _ctx(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Xóa", lambda: self._remove(it))
        m.exec(self.list.mapToGlobal(pos))

    def _remove(self, it: QListWidgetItem):
        p = it.data(Qt.UserRole)
        if p in self._paths:
            self._paths.remove(p)
        self.list.takeItem(self.list.row(it))

    def _refresh(self):
        self.list.clear()
        for p in self._paths:
            it = QListWidgetItem(Path(p).name)
            it.setData(Qt.UserRole, p)
            pm = QPixmap(p)
            if not pm.isNull():
                pm = pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                it.setIcon(QIcon(pm))
            it.setSizeHint(QSize(80, 84))
            self.list.addItem(it)

    def paths(self) -> List[str]:
        return list(self._paths)

    def set_paths(self, paths: List[str]):
        self._paths = list(paths)
        self._refresh()


# ------------------------------------------------------------------ model địa chỉ cho QCompleter
class AddressModel(QAbstractListModel):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.items: list = []
        self.reload()

    def reload(self):
        self.beginResetModel()
        self.items = self.mgr.buildings()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        b = self.items[index.row()]
        if role == Qt.DisplayRole:
            return b.get("display", "")
        if role == Qt.UserRole:
            return b
        return None


# ------------------------------------------------------------------ form
class RoomEditForm(QDialog):
    """Form thêm/sửa phòng - giao diện hiện đại, gợi ý trùng real-time."""

    saved = Signal(str)            # room_id
    save_and_continue = Signal(dict)

    def __init__(self, manager, room: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.room = room or {}
        self.is_new = not bool(self.room.get("id"))
        self._building: Optional[Dict[str, Any]] = None
        self._auto_filled = False
        self._last_check: Dict[str, Any] = {}

        title = "Thêm phòng mới" if self.is_new else f"Sửa phòng {self.room.get('room_code', '')}"
        self.setWindowTitle(title)
        self.setMinimumSize(900, 700)
        self.resize(1000, 760)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(16, 14, 16, 12)
        self.layout().setSpacing(10)

        self._build_header()
        self._build_banner()
        self._build_form_scroll()
        self._build_buttons()

        # debounce kiểm tra trùng
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._run_check)

        # --- AUTO DRAFT: tự lưu nháp nhập liệu ---
        self._draft_key = "room_draft"
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(2000)
        self._draft_timer.timeout.connect(self._save_draft)

        # --- GỢI Ý TÒA ĐÃ CÓ: debounce 300ms khi gõ địa chỉ ---
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(300)
        self._suggest_timer.timeout.connect(self._update_suggestions)

        self._seed_values()
        self._connect_autofill()
        if self.is_new:
            self._apply_draft()

    # ------------------------------------------------------------------ header hiện đại
    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("Card")
        bar.setFixedHeight(56)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(12)

        icon = QLabel("＋" if self.is_new else "✎")
        icon.setStyleSheet(
            f"font-size:22px; font-weight:800; color:{theme.c('accent')}; background:transparent;")
        hl.addWidget(icon)

        t = QLabel(self.windowTitle())
        t.setObjectName("PageTitle")
        t.setStyleSheet("background:transparent; font-size:16px; font-weight:700;")
        hl.addWidget(t)
        hl.addStretch(1)

        hint = QLabel("Gõ địa chỉ để gợi ý tòa đã có • trùng sẽ cảnh báo ngay khi nhập")
        hint.setObjectName("Muted")
        hint.setStyleSheet("background:transparent; font-size:11.5px;")
        hl.addWidget(hint)

        self.btn_paste = QPushButton("📋 Dán tin đăng")
        self.btn_paste.setObjectName("Chip")
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.setToolTip(
            "Dán nguyên văn tin cho thuê (Zalo/Facebook) - hệ thống tự tách "
            "địa chỉ, giá, dạng phòng, sức chứa, diện tích, tầng, pet, xe điện, SĐT")
        self.btn_paste.clicked.connect(self._open_paste_dialog)
        hl.addWidget(self.btn_paste)

        self.layout().addWidget(bar)

    # ------------------------------------------------------------------ banner gợi ý trùng
    def _build_banner(self):
        self.banner = QFrame()
        self.banner.setObjectName("Card")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(6)

        self.banner_label = QLabel("Nhập địa chỉ + số căn để kiểm tra trùng tự động…")
        self.banner_label.setWordWrap(True)
        self.banner_label.setTextFormat(Qt.RichText)
        self.banner_label.setStyleSheet("background:transparent;")
        bl.addWidget(self.banner_label)

        # hàng nút hành động trong banner (hiện khi có gợi ý trùng)
        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(8)
        self.btn_open_dup = QPushButton("Mở bản ghi cũ")
        self.btn_open_dup.setObjectName("Ghost")
        self.btn_open_dup.setFixedHeight(28)
        self.btn_open_dup.hide()
        self.btn_open_dup.clicked.connect(self._open_suggested_duplicate)
        self.btn_row.addWidget(self.btn_open_dup)
        self.btn_row.addStretch(1)
        bl.addLayout(self.btn_row)

        self.banner.hide()
        self.layout().addWidget(self.banner)

    # ------------------------------------------------------------------ helper tạo nhóm
    def _group(self, idx: int):
        box = QFrame()
        box.setObjectName("Card")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)
        t = QLabel(GROUP_TITLES[idx - 1])
        t.setObjectName("SectionTitle")
        t.setStyleSheet("font-size:13px; background:transparent;")
        v.addWidget(t)
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        v.addLayout(form)
        return box, form

    # ------------------------------------------------------------------ xây form (grid 2 cột mỗi nhóm, trong QScrollArea)
    def _build_form_scroll(self):
        self.ed: Dict[str, QWidget] = {}

        # ---- container cuộn cho 8 nhóm (form không bị dài quá màn hình) ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        self.layout().addWidget(scroll)

        container = QWidget()
        container.setObjectName("Card")
        container.setStyleSheet(
            f"QWidget#Card {{ background:{theme.c('card')}; border:none; border-radius:12px; }}")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(10)
        scroll.setWidget(container)

        def add_group(idx: int, build_fn):
            box, form = self._group(idx)
            build_fn(form)
            form.setColumnStretch(form.columnCount() - 1, 1)  # stretch cột cuối
            cl.addWidget(box)

        # ---------- nhóm 1: Địa chỉ (1 hàng 4 cột, giống cột Excel) + GỢI Ý TÒA ĐÃ CÓ ----------
        box1, f1 = self._group(1)

        def _g1(f):
            self.ed["house_number"] = self._line("Ví dụ: 86, 79/16, 371A")
            self.ed["street"] = self._line("Ví dụ: Nguyễn Thượng Hiền")
            self.ed["ward"] = self._line("Ví dụ: P. 13")
            self.ed["district"] = self._line("Ví dụ: Q. Bình Thạnh cũ")
            f.addWidget(QLabel("Số nhà:"), 0, 0)
            f.addWidget(self.ed["house_number"], 0, 1)
            f.addWidget(QLabel("Tên đường:"), 0, 2)
            f.addWidget(self.ed["street"], 0, 3)
            f.addWidget(QLabel("Phường:"), 0, 4)
            f.addWidget(self.ed["ward"], 0, 5)
            f.addWidget(QLabel("Quận / Khu vực:"), 0, 6)
            f.addWidget(self.ed["district"], 0, 7)
            f.setColumnStretch(8, 1)
        _g1(f1)

        # hàng gợi ý: bấm 1 phát điền đủ 4 ô địa chỉ + tự điền chủ nhà/SĐT
        self.suggest_row_w = QWidget()
        self.suggest_row_w.setStyleSheet("background:transparent;")
        self.suggest_lay = QHBoxLayout(self.suggest_row_w)
        self.suggest_lay.setContentsMargins(0, 0, 0, 0)
        self.suggest_lay.setSpacing(6)
        box1.layout().addWidget(self.suggest_row_w)
        self.suggest_row_w.hide()
        cl.addWidget(box1)

        # ---------- nhóm 2: Nhận diện ----------
        def _g2(f):
            self.ed["room_code"] = self._line("Ví dụ: P-86")
            self.ed["unit_code"] = self._line("Số căn thực tế - khoá chống trùng")
            self.ed["floor"] = self._line("Ví dụ: 3, Lầu 2")
            self.ed["area"] = self._line("Ví dụ: 45, 60.5")
            self.ed["room_type"] = QComboBox()
            self.ed["room_type"].setEditable(True)
            self.ed["room_type"].addItems(ROOM_TYPES)
            f.addWidget(QLabel("Mã phòng:"), 0, 0)
            f.addWidget(self.ed["room_code"], 0, 1)
            f.addWidget(QLabel("Số căn:"), 0, 2)
            f.addWidget(self.ed["unit_code"], 0, 3)
            f.addWidget(QLabel("Tầng:"), 1, 0)
            f.addWidget(self.ed["floor"], 1, 1)
            f.addWidget(QLabel("Diện tích (m2):"), 1, 2)
            f.addWidget(self.ed["area"], 1, 3)
            f.addWidget(QLabel("Dạng phòng:"), 2, 0)
            f.addWidget(self.ed["room_type"], 2, 1, 1, 3)
        add_group(2, _g2)

        # ---------- nhóm 3: Giá & cọc ----------
        def _g3(f):
            self.ed["price"] = self._line("Ví dụ: 7000000 hoặc 7.5tr")
            self.ed["deposit"] = self._line("Ví dụ: 7000000")
            f.addWidget(QLabel("Giá thuê (VNĐ):"), 0, 0)
            f.addWidget(self.ed["price"], 0, 1)
            f.addWidget(QLabel("Tiền cọc (VNĐ):"), 1, 0)
            f.addWidget(self.ed["deposit"], 1, 1)
        add_group(3, _g3)

        # ---------- nhóm 4: Tiện ích ----------
        def _g4(f):
            self.ed["capacity"] = self._line("Ví dụ: 2 Ng/2 Xe")
            self.ed["ev_support"] = self._tribune("⚡ Xe điện")
            self.ed["foreign_guest"] = self._tribune("🌏 Khách nước ngoài")
            f.addWidget(QLabel("Tối đa (người/xe):"), 0, 0)
            f.addWidget(self.ed["capacity"], 0, 1)
            f.addWidget(self.ed["ev_support"], 1, 0, 1, 2)
            f.addWidget(self.ed["foreign_guest"], 1, 2, 1, 2)
        add_group(4, _g4)

        # ---------- nhóm 5: Chính sách ----------
        def _g5(f):
            self.ed["pet_policy"] = QComboBox()
            self.ed["pet_policy"].setEditable(True)
            self.ed["pet_policy"].addItems(["Cho nuôi Mèo", "Cho nuôi Chó",
                                            "Cho nuôi (chó/mèo)", "Không nuôi", ""])
            self.ed["pet_note"] = self._line("Chính sách chi tiết (giữ nguyên văn bản gốc)")
            f.addWidget(QLabel("Nuôi thú cưng:"), 0, 0)
            f.addWidget(self.ed["pet_policy"], 0, 1)
            f.addWidget(QLabel("Ghi chú chính sách:"), 1, 0)
            f.addWidget(self.ed["pet_note"], 1, 1)
        add_group(5, _g5)

        # ---------- nhóm 6: Liên hệ ----------
        def _g6(f):
            self.ed["owner_phone"] = self._line("Ví dụ: 0868328147")
            self.ed["zalo_group"] = self._line("zalo.me/g/...")
            f.addWidget(QLabel("SĐT chủ / admin:"), 0, 0)
            f.addWidget(self.ed["owner_phone"], 0, 1)
            f.addWidget(QLabel("Group Zalo:"), 1, 0)
            f.addWidget(self.ed["zalo_group"], 1, 1)
        add_group(6, _g6)

        # ---------- nhóm 7: Media & đánh giá ----------
        def _g7(f):
            self.img_upload = ImageUpload(self.mgr)
            self.ed["rating"] = StarRating()
            self.ed["drive_link"] = self._line("drive.google.com/folder/...")
            f.addWidget(QLabel("Ảnh phòng:"), 0, 0)
            f.addWidget(self.img_upload, 0, 1)
            f.addWidget(QLabel("Link Drive:"), 1, 0)
            f.addWidget(self.ed["drive_link"], 1, 1)
            f.addWidget(QLabel("Đánh giá:"), 2, 0)
            f.addWidget(self.ed["rating"], 2, 1)
        add_group(7, _g7)

        # ---------- nhóm 8: Ghi chú & trạng thái ----------
        def _g8(f):
            self.ed["status"] = QComboBox()
            for k in RoomStatus.ORDER:
                self.ed["status"].addItem(f"● {RoomStatus.label(k)}", k)
            self.ed["surveyed"] = QCheckBox("📸 Đã khảo sát (có ảnh/video)")
            self.ed["notes"] = QPlainTextEdit()
            self.ed["notes"].setMinimumHeight(72)
            self.ed["notes"].setPlaceholderText(
                "Chính sách, nội thất, tiện ích, ghi chú sale...")
            f.addWidget(QLabel("Trạng thái:"), 0, 0)
            f.addWidget(self.ed["status"], 0, 1)
            f.addWidget(QLabel("Khảo sát:"), 1, 0)
            f.addWidget(self.ed["surveyed"], 1, 1)
            f.addWidget(QLabel("Ghi chú:"), 2, 0)
            f.addWidget(self.ed["notes"], 2, 1)
        add_group(8, _g8)

    def _line(self, placeholder: str = "") -> QLineEdit:
        ed = QLineEdit()
        ed.setPlaceholderText(placeholder)
        return ed

    def _tribune(self, label: str) -> QComboBox:
        """Combo 3 trạng thái: Chưa biết / Có / Không."""
        cmb = QComboBox()
        cmb.setEditable(False)
        cmb.addItem("— Chưa biết —", None)
        cmb.addItem("✅ Có", True)
        cmb.addItem("❌ Không", False)
        cmb.setMinimumWidth(120)
        cmb.setObjectName("Ghost")
        cmb.setToolTip(label)
        return cmb

    # ------------------------------------------------------------------ nút điều khiển
    def _build_buttons(self):
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_check = QPushButton("🔎 Kiểm tra trùng")
        self.btn_check.clicked.connect(self._run_check)
        row.addWidget(self.btn_check)
        btns = QDialogButtonBox()
        self.btn_save = btns.addButton("Lưu", QDialogButtonBox.AcceptRole)
        self.btn_save.setObjectName("Primary")
        self.btn_save_more = btns.addButton("Lưu & thêm tiếp", QDialogButtonBox.ActionRole)
        # "Lưu & thêm tiếp" chỉ có ý nghĩa khi THÊM MỚI - ẩn khi đang sửa
        if not self.is_new:
            self.btn_save_more.setVisible(False)
        btns.addButton("Hủy", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        self.btn_save_more.clicked.connect(lambda: self._save(more=True))
        row.addWidget(btns)
        self.layout().addLayout(row)

    # ------------------------------------------------------------------ dữ liệu
    def _seed_values(self):
        r = self.room
        for key, w in self.ed.items():
            if isinstance(w, QLineEdit):
                v = r.get(key, "")
                w.setText(str(v) if v not in (None, "") else "")
            elif isinstance(w, QComboBox):
                if key == "status":
                    i = w.findData(r.get("status", "new"))
                    w.setCurrentIndex(max(0, i))
                else:
                    w.setCurrentText(str(r.get(key, "") or ""))
            elif isinstance(w, QCheckBox):
                if key == "surveyed":
                    w.setChecked(bool(r.get("surveyed")))
                elif key == "foreign_guest":
                    w.setChecked(bool(r.get("foreign_guest")))
                else:
                    w.setChecked(bool(r.get("ev_support")))
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(str(r.get("notes", "") or ""))
            elif isinstance(w, StarRating):
                w.set_value(int(r.get("rating") or 0))
        if isinstance(self.img_upload, ImageUpload) and r.get("id"):
            # ảnh đã lưu sẽ được nạp từ thư mục quy ước khi mở form chi tiết
            pass
        if r.get("unit_code") == "" and r.get("room_code"):
            pass  # giữ trống - không tự đoán số căn

    def _connect_autofill(self):
        for key in ("house_number", "street", "ward", "district"):
            w = self.ed[key]
            if isinstance(w, QLineEdit):
                w.editingFinished.connect(self._maybe_autofill)

        # QCompleter gợi ý địa chỉ tòa (gõ không dấu vẫn khớp nhờ model chuẩn hoá)
        self.addr_model = AddressModel(self.mgr, self)
        comp = QCompleter()
        comp.setModel(self.addr_model)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        comp.setFilterMode(Qt.MatchContains)
        self.ed["street"].setCompleter(comp)

        # debounce kiểm tra trùng khi thay đổi khoá nhận diện
        for key in ("house_number", "street", "ward", "district", "unit_code", "room_code"):
            w = self.ed[key]
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._schedule_check)

        # gợi ý tòa đã có khi gõ số nhà / tên đường
        for key in ("house_number", "street"):
            w = self.ed[key]
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._schedule_suggest)

        # lưu nháp tự động khi thay đổi bất kỳ trường nào (debounce 2s)
        for w in self.ed.values():
            if isinstance(w, (QLineEdit, QComboBox, QCheckBox, QPlainTextEdit)):
                if isinstance(w, QLineEdit):
                    w.textChanged.connect(self._schedule_draft)
                elif isinstance(w, QComboBox):
                    w.currentTextChanged.connect(self._schedule_draft)
                elif isinstance(w, QCheckBox):
                    w.toggled.connect(self._schedule_draft)
                else:
                    w.textChanged.connect(self._schedule_draft)

    def _maybe_autofill(self):
        """Tự điền chủ nhà / SĐT / Zalo / chính sách từ tòa đã có."""
        if self.is_new is False:
            return
        payload = self.payload()
        key = tu.address_key(payload.get("house_number"), payload.get("street"),
                             payload.get("ward"), payload.get("district"))
        if not key:
            return
        b = self.mgr.db.find_building_by_address(key)
        if not b:
            return
        self._building = b
        changed = False
        for src, dst in (("phone", "owner_phone"), ("zalo_group", "zalo_group")):
            if b.get(src) and not self.ed[dst].text().strip():
                self.ed[dst].setText(str(b[src]))
                changed = True
        if b.get("pet_policy") and not self.ed["pet_policy"].currentText().strip():
            self.ed["pet_policy"].setCurrentText(str(b["pet_policy"]))
            changed = True
        if b.get("ev_policy") and not self.ed["pet_note"].text().strip():
            self.ed["pet_note"].setText(str(b["ev_policy"]))
            changed = True
        if changed:
            self.banner_label.setText(
                f"<span style='color:{theme.c('ok')};'>✓ Đã tự điền thông tin từ tòa "
                f"<b>{b.get('display')}</b></span>")
            self.banner.show()

    def _schedule_check(self, *_):
        self._debounce.start()

    # ------------------------------------------------------------------ gợi ý tòa đã có (nhập nhanh)
    def _schedule_suggest(self, *_):
        if hasattr(self, "_suggest_timer"):
            self._suggest_timer.start()

    def _update_suggestions(self):
        """Gợi ý tòa đã có theo số nhà + tên đường đang gõ (chỉ khi THÊM MỚI)."""
        if not hasattr(self, "suggest_row_w"):
            return
        if not self.is_new:
            self.suggest_row_w.hide()
            return
        q = tu.norm(f"{self.ed['house_number'].text()} {self.ed['street'].text()}")
        if len(q) < 2:
            self.suggest_row_w.hide()
            return
        matches = []
        try:
            for b in self.mgr.buildings():
                if q in tu.norm(b.get("display", "")):
                    matches.append(b)
                if len(matches) >= 5:
                    break
        except Exception:  # noqa: BLE001
            matches = []
        if not matches:
            self.suggest_row_w.hide()
            return
        # dựng lại hàng chip
        while self.suggest_lay.count():
            it = self.suggest_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        lbl = QLabel("🏢 Tòa đã có - bấm để điền nhanh:")
        lbl.setObjectName("Muted")
        lbl.setStyleSheet("background:transparent; font-size:12px;")
        self.suggest_lay.addWidget(lbl)
        for b in matches:
            total = b.get("rooms_total", 0)
            txt = f"{b.get('code','')} · {b.get('display','')}" + (f" · {total} phòng" if total else "")
            chip = QPushButton(txt)
            chip.setObjectName("Chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip("Bấm để điền đủ địa chỉ + tự điền chủ nhà/SĐT/chính sách")
            chip.clicked.connect(lambda checked=False, bb=dict(b): self._fill_from_building(bb))
            self.suggest_lay.addWidget(chip)
        self.suggest_lay.addStretch(1)
        self.suggest_row_w.show()

    def _fill_from_building(self, b: Dict[str, Any]):
        """Bấm gợi ý -> điền đủ 4 ô địa chỉ + tự điền chủ nhà/SĐT/chính sách."""
        if not b:
            return
        self.ed["house_number"].setText(str(b.get("house_number") or ""))
        self.ed["street"].setText(str(b.get("street") or ""))
        self.ed["ward"].setText(str(b.get("ward") or ""))
        self.ed["district"].setText(str(b.get("district") or ""))
        self._maybe_autofill()
        self._run_check()
        self.suggest_row_w.hide()
        self.banner_label.setText(
            f"<span style='color:{theme.c('ok')};'>✓ Đã chọn tòa tồn tại "
            f"<b>{b.get('display')}</b> - chỉ cần nhập thông tin phòng "
            f"(mã / số căn / giá).</span>")
        self.banner.show()

    def _run_check(self):
        payload = self.payload()
        if not (payload.get("house_number") or payload.get("street")):
            self.banner.hide()
            return
        try:
            res = self.mgr.check_new(payload, exclude_id=self.room.get("id") or None)
        except Exception as e:  # noqa: BLE001
            self.banner_label.setText(f"<span style='color:{theme.c('danger')};'>Lỗi kiểm tra: {e}</span>")
            self.banner.show()
            return
        self._last_check = {"room_exists": res.room_exists, "recommended": res.recommended}
        if res.room_exists:
            ex = res.existing_room or {}
            color = theme.c("danger")
            head = "⛔ PHÒNG NÀY ĐÃ TỒN TẠI"
            body = (f"{ex.get('room_code')} - {ex.get('address')} | "
                    f"trạng thái: {status_label(ex.get('status', ''))} | "
                    f"cập nhật: {ex.get('updated_at')}<br>"
                    f"<b>-> Bấm Lưu sẽ bị chặn. Hãy MỞ bản ghi cũ để sửa.</b>")
            self.btn_save.setEnabled(False)
            self.btn_open_dup.setVisible(True)
            self._dup_existing_id = ex.get("id")
        elif res.has_warn:
            color = theme.c("orange")
            head = "⚠ NGHI NGỜ TRÙNG DỮ LIỆU"
            body = "<br>".join(f.message for f in res.findings if f.severity == "warn")
            self.btn_save.setEnabled(True)
            self.btn_open_dup.setVisible(False)
            self._dup_existing_id = None
        else:
            color = theme.c("ok")
            head = "✓ Không phát hiện trùng"
            info = [f.message for f in res.findings if f.kind in ("building_exists", "building_new")]
            body = info[0] if info else "Sẵn sàng lưu."
            self.btn_save.setEnabled(True)
            self.btn_open_dup.setVisible(False)
            self._dup_existing_id = None

        self.banner_label.setText(
            f"<b style='color:{color};'>{head}</b><br>"
            f"<span style='color:{theme.c('text2')};'>{body}</span>")
        self.banner.show()

    def _open_suggested_duplicate(self):
        """Mở bản ghi trùng được gợi ý (nếu có)."""
        rid = getattr(self, "_dup_existing_id", None)
        if not rid:
            return
        self.reject()
        mw = self.parent()
        if mw and hasattr(mw, "_open_detail"):
            mw._open_detail(rid)

    # ------------------------------------------------------------------ dán tin đăng (nhập nhanh từ text)
    def _open_paste_dialog(self):
        dlg = PasteListingDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        parsed = dlg.parsed
        if not parsed:
            return
        self._apply_listing(parsed)

    def _apply_listing(self, p: Dict[str, Any]):
        """Điền các trường đã tách từ tin đăng vào form."""
        text_fields = ("house_number", "street", "ward", "district", "room_type",
                       "area", "floor", "capacity", "pet_policy", "owner_phone")
        for k in text_fields:
            v = str(p.get(k) or "").strip()
            if v and k in self.ed:
                w = self.ed[k]
                if isinstance(w, QLineEdit):
                    w.setText(v)
                elif isinstance(w, QComboBox):
                    w.setCurrentText(v)
        for k in ("price", "deposit"):
            v = int(p.get(k) or 0)
            if v and isinstance(self.ed[k], QLineEdit):
                self.ed[k].setText(str(v))
        if p.get("ev_support") and isinstance(self.ed.get("ev_support"), QCheckBox):
            self.ed["ev_support"].setChecked(True)
        # ghi chú: lưu nguyên văn tin gốc để tham khảo (nếu ô ghi chú đang trống)
        note_src = str(p.get("notes") or "").strip()
        if note_src:
            cur = self.ed["notes"].toPlainText().strip()
            if not cur:
                self.ed["notes"].setPlainText(f"[Tin gốc] {note_src}")
        self._maybe_autofill()
        self._run_check()
        self.banner_label.setText(
            f"<span style='color:{theme.c('ok')};'>📋 Đã tách tin đăng vào form - "
            f"kiểm tra lại giá & địa chỉ trước khi Lưu.</span>")
        self.banner.show()

    # ------------------------------------------------------------------ nháp tự động (draft)
    def _schedule_draft(self, *_):
        self._draft_timer.start()

    def _draft_payload(self) -> Dict[str, Any]:
        """Lấy giá trị THẢO (chưa normalize) để lưu nháp."""
        out: Dict[str, Any] = {}
        for k, w in self.ed.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text().strip()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText().strip()
            elif isinstance(w, QCheckBox):
                out[k] = 1 if w.isChecked() else 0
            elif isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText().strip()
        out["status"] = self.ed["status"].currentData() or "new"
        return out

    def _save_draft(self):
        if not self.is_new:
            return
        p = self._draft_payload()
        if not any(str(v) for v in p.values()):
            return
        try:
            self.mgr.settings.set(self._draft_key,
                                  json.dumps(p, ensure_ascii=False), save=True)
        except Exception:  # noqa: BLE001
            pass

    def _apply_draft(self):
        """Điền nháp lưu từ lần trước vào form (nếu có)."""
        raw = self.mgr.settings.get(self._draft_key)
        if not raw:
            return
        try:
            p = json.loads(raw)
        except Exception:
            return
        if not isinstance(p, dict) or not any(str(v) for v in p.values()):
            return
        self.banner_label.setText(
            f"<span style='color:{theme.c('text2')};'>📋 Phát hiện nháp nhập liệu chưa hoàn tất - "
            "đã tự điền vào form.</span>")
        self.banner.show()
        for k, v in p.items():
            if k not in self.ed:
                continue
            w = self.ed[k]
            try:
                if isinstance(w, QLineEdit):
                    w.setText(str(v or ""))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(v or ""))
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(int(v or 0)))
                elif isinstance(w, QPlainTextEdit):
                    w.setPlainText(str(v or ""))
            except Exception:  # noqa: BLE001
                pass
        self.ed["room_code"].setFocus()

    def _clear_draft(self):
        try:
            self.mgr.settings.set(self._draft_key, "", save=True)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ lưu
    def payload(self) -> Dict[str, Any]:
        def txt(k):
            w = self.ed[k]
            if isinstance(w, QLineEdit):
                return w.text().strip()
            if isinstance(w, QComboBox):
                return w.currentText().strip()
            if isinstance(w, QPlainTextEdit):
                return w.toPlainText().strip()
            if isinstance(w, StarRating):
                return str(w.value())
            return ""

        pet_policy = self.ed["pet_policy"].currentText().strip()
        pet_note = txt("pet_note")
        notes = txt("notes")
        if pet_note:
            notes = (notes + " | " if notes else "") + f"Chính sách: {pet_note}"
        status_key = self.ed["status"].currentData() or "new"

        # tribune 3-state: None/True/False
        ev = self.ed["ev_support"].currentData()
        fg = self.ed["foreign_guest"].currentData()

        return {
            "house_number": txt("house_number"),
            "street": txt("street"),
            "ward": txt("ward"),
            "district": txt("district"),
            "room_code": txt("room_code"),
            "unit_code": txt("unit_code"),
            "floor": txt("floor"),
            "room_type": self.ed["room_type"].currentText().strip(),
            "price": tu.normalize_price(txt("price")),
            "deposit": tu.normalize_price(txt("deposit")),
            "capacity": txt("capacity"),
            "ev_support": 1 if ev is True else (0 if ev is False else 0),
            "foreign_guest": 1 if fg is True else (0 if fg is False else 0),
            "area": txt("area"),
            "pet_policy": pet_policy,
            "rating": txt("rating"),
            "owner_phone": txt("owner_phone"),
            "zalo_group": txt("zalo_group"),
            "drive_link": txt("drive_link"),
            "image_paths": ",".join(self.img_upload.paths()),
            "notes": notes,
            "status": status_key,
            "status_text": RoomStatus.label(status_key),
            "surveyed": 1 if self.ed["surveyed"].isChecked() else 0,
        }

    def _save(self, more: bool = False):
        payload = self.payload()
        if not (payload.get("house_number") or payload.get("street")):
            QMessageBox_Warning(self, "Thiếu dữ liệu",
                                "Cần nhập ít nhất SỐ NHÀ hoặc TÊN ĐƯỜNG để xác định tòa nhà.")
            return
        if not payload.get("unit_code") and not tu.valid_room_code(payload.get("room_code")):
            QMessageBox_Warning(self, "Thiếu khoá nhận diện",
                                "Cần SỐ CĂN (khuyến nghị) hoặc MÃ PHÒNG hợp lệ (có chữ số)\n"
                                "để chống trùng - chương trình không tự suy đoán.")
            return

        actor = self.mgr.settings.get("user_name") or "Admin"
        try:
            if self.is_new:
                room = self.mgr.add_room(payload, actor=actor)
            else:
                rid = self.room["id"]
                changes = {k: v for k, v in payload.items() if k != "status_text"}
                # Kiểm tra trùng THẬT (loại trừ chính bản ghi đang sửa):
                # - room_exists -> chặn (trùng phòng khác)
                # - chỉ warn (bản ghi khác tương tự) -> cho phép lưu khi người dùng chủ động sửa
                res = self.mgr.check_new(payload, exclude_id=rid)
                if res.room_exists:
                    self._show_duplicate(DuplicateError(res))
                    return
                room = self.mgr.update_room(rid, changes, actor=actor, force=True,
                                            note="Sửa từ form chi tiết")
        except DuplicateError as e:
            self._show_duplicate(e)
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox_Critical(self, "Không lưu được", str(e))
            return

        self.saved.emit(room["id"])
        self._clear_draft()   # đã lưu xong -> xóa nháp
        if more:
            self.save_and_continue.emit(payload)
            # reset form cho lần nhập kế tiếp (giữ nguyên địa chỉ - nhập nhiều căn cùng tòa)
            keep = {k: payload.get(k) for k in
                    ("house_number", "street", "ward", "district", "room_type",
                     "price", "deposit", "capacity", "owner_phone", "zalo_group")}
            self.room = {}
            self.is_new = True
            self._seed_values()
            for k, v in keep.items():
                w = self.ed[k]
                if isinstance(w, QLineEdit):
                    w.setText(str(v or ""))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(v or ""))
            self.ed["room_code"].clear()
            self.ed["unit_code"].clear()
            self.ed["floor"].clear()
            self.ed["drive_link"].clear()
            self.ed["notes"].clear()
            self.ed["room_code"].setFocus()
            self.banner_label.setText(f"<span style='color:{theme.c('ok')};'>✓ Đã lưu phòng "
                                      f"<b>{payload.get('room_code') or payload.get('unit_code')}</b> "
                                      f"- tiếp tục nhập phòng kế.</span>")
            self.banner.show()
            return
        self.accept()

    def _show_duplicate(self, err: DuplicateError):
        res = err.result
        ex = res.existing_room or {}
        self._run_check()
        if ex.get("id"):
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Trùng dữ liệu - không cho lưu")
            box.setText(res.messages("\n"))
            box.setInformativeText("Hãy mở bản ghi cũ để chỉnh sửa, tránh nhập trùng.")
            open_btn = box.addButton(f"Mở bản ghi cũ: {ex.get('room_code', '')}",
                                     QMessageBox.AcceptRole)
            box.addButton("Đóng", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self.reject()
                self.parent() and getattr(self.parent(), "_open_detail", lambda *_: None)(ex["id"])
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Trùng dữ liệu", res.messages("\n"))


# ------------------------------------------------------------------ dialog dán tin đăng
class PasteListingDialog(QDialog):
    """Dán nguyên văn tin cho thuê (Zalo/FB) -> hệ thống tự tách các trường.

    Xem trước kết quả phân tích ngay khi gõ/dán; bấm "Áp dụng vào form" để điền.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parsed: Dict[str, Any] = {}
        self.setWindowTitle("📋 Dán tin đăng - nhập nhanh từ text")
        self.setMinimumSize(640, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(10)

        tip = QLabel(
            "Dán nguyên văn tin đăng vào ô bên dưới. Hệ thống tự tách:\n"
            "địa chỉ (số nhà · đường · phường · quận) · giá · cọc · dạng phòng · "
            "sức chứa · diện tích · tầng · pet · xe điện · SĐT")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.txt = QPlainTextEdit()
        self.txt.setPlaceholderText(
            "Ví dụ:\nCho thue can ho 86 Nguyễn Thượng Hiền P.13 Q.Bình Thạnh, "
            "giá 7.5tr, studio, 2 người 2 xe, 45m2, tầng 3, sạc xe điện, "
            "cho nuôi mèo, SDT 0868328147")
        f = self.txt.font()
        f.setPointSize(11)
        self.txt.setFont(f)
        lay.addWidget(self.txt, 2)

        # xem trước kết quả phân tích
        prev_box = QFrame()
        prev_box.setObjectName("Card")
        pv = QVBoxLayout(prev_box)
        pv.setContentsMargins(14, 10, 14, 10)
        pv.setSpacing(6)
        pt = QLabel("Kết quả tách được:")
        pt.setObjectName("SectionTitle")
        pt.setStyleSheet("font-size:13px; background:transparent;")
        pv.addWidget(pt)
        self.prev_label = QLabel("Chưa có dữ liệu.")
        self.prev_label.setTextFormat(Qt.RichText)
        self.prev_label.setWordWrap(True)
        self.prev_label.setStyleSheet("background:transparent; line-height:150%;")
        pv.addWidget(self.prev_label, 1)
        lay.addWidget(prev_box, 3)

        bb = QDialogButtonBox()
        self.btn_apply = bb.addButton("Áp dụng vào form", QDialogButtonBox.AcceptRole)
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.setEnabled(False)
        bb.addButton("Hủy", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        # phân tích tự động khi dán/gõ (debounce 300ms)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._preview)
        self.txt.textChanged.connect(lambda: self._timer.start())

    def _preview(self):
        import text_utils as tu
        text = self.txt.toPlainText().strip()
        if not text:
            self.parsed = {}
            self.prev_label.setText("Chưa có dữ liệu.")
            self.btn_apply.setEnabled(False)
            return
        p = tu.parse_listing_text(text)
        self.parsed = p
        acc = theme.c("accent")
        rows = [
            ("Địa chỉ", " ".join(x for x in (p.get("house_number"), p.get("street")) if x)),
            ("Phường / Quận", " · ".join(x for x in (p.get("ward"), p.get("district")) if x)),
            ("Giá thuê", f"{tu.format_money(p.get('price'))} ₫" if p.get("price") else ""),
            ("Tiền cọc", f"{tu.format_money(p.get('deposit'))} ₫" if p.get("deposit") else ""),
            ("Dạng phòng", p.get("room_type")),
            ("Sức chứa", p.get("capacity")),
            ("Diện tích / Tầng", " / ".join(x for x in (p.get("area"), p.get("floor")) if x)),
            ("Xe điện", "⚡ Có" if p.get("ev_support") else ""),
            ("Thú cưng", p.get("pet_policy")),
            ("SĐT", p.get("owner_phone")),
        ]
        html = "".join(
            f"<tr><td style='color:{theme.c('text2')}; font-weight:700; padding:1px 12px 1px 0;'>{k}</td>"
            f"<td style='color:{acc}; font-weight:700;'>{v}</td></tr>"
            for k, v in rows if v)
        if html:
            self.prev_label.setText(
                f"<table width='100%'>{html}</table>")
            self.btn_apply.setEnabled(True)
        else:
            self.prev_label.setText(
                f"<span style='color:{theme.c('danger')}; font-weight:700;'>"
                "Không tách được thông tin nào - kiểm tra lại tin đăng.</span>")
            self.btn_apply.setEnabled(False)


# ------------------------------------------------------------------ wrapper hộp thoại (tách import)
def QMessageBox_Warning(parent, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(parent, title, text)


def QMessageBox_Critical(parent, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.critical(parent, title, text)


