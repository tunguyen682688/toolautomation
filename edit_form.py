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

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QFormLayout,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QCompleter,
)

import text_utils as tu
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

# Màu đại diện cho mức độ nghi ngờ trùng
SEVERITY_COLORS = {
    "block": C_DANGER,
    "warn": C_ORANGE,
    "info": C_OK,
}


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
        self._build_form()
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
            f"font-size:22px; font-weight:800; color:{C_ACCENT}; background:transparent;")
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
        self.layout().addWidget(box)
        return box, form

    # ------------------------------------------------------------------ xây form (grid 2 cột mỗi nhóm)
    def _build_form(self):
        self.ed: Dict[str, QWidget] = {}

        # ---------- nhóm 1: Địa chỉ ----------
        _, f1 = self._group(1)
        self.ed["house_number"] = self._line("Ví dụ: 86, 79/16, 371A")
        self.ed["street"] = self._line("Ví dụ: Nguyễn Thượng Hiền")
        self.ed["ward"] = self._line("Ví dụ: P. 13")
        self.ed["district"] = self._line("Ví dụ: Q. Bình Thạnh cũ")
        f1.addWidget(QLabel("Số nhà:"), 0, 0)
        f1.addWidget(self.ed["house_number"], 0, 1)
        f1.addWidget(QLabel("Tên đường:"), 0, 2)
        f1.addWidget(self.ed["street"], 0, 3)
        f1.addWidget(QLabel("Phường:"), 1, 0)
        f1.addWidget(self.ed["ward"], 1, 1)
        f1.addWidget(QLabel("Quận / Khu vực:"), 1, 2)
        f1.addWidget(self.ed["district"], 1, 3)

        # ---------- nhóm 2: Nhận diện ----------
        _, f2 = self._group(2)
        self.ed["room_code"] = self._line("Ví dụ: P-86")
        self.ed["unit_code"] = self._line("Số căn thực tế - khoá chống trùng")
        self.ed["floor"] = self._line("Ví dụ: 3, Lầu 2")
        self.ed["room_type"] = QComboBox()
        self.ed["room_type"].setEditable(True)
        self.ed["room_type"].addItems(ROOM_TYPES)
        f2.addWidget(QLabel("Mã phòng:"), 0, 0)
        f2.addWidget(self.ed["room_code"], 0, 1)
        f2.addWidget(QLabel("Số căn:"), 0, 2)
        f2.addWidget(self.ed["unit_code"], 0, 3)
        f2.addWidget(QLabel("Tầng:"), 1, 0)
        f2.addWidget(self.ed["floor"], 1, 1)
        f2.addWidget(QLabel("Dạng phòng:"), 1, 2)
        f2.addWidget(self.ed["room_type"], 1, 3)

        # ---------- nhóm 3: Giá & cọc ----------
        _, f3 = self._group(3)
        self.ed["price"] = self._line("Ví dụ: 7000000 hoặc 7.5tr")
        self.ed["deposit"] = self._line("Ví dụ: 7000000")
        f3.addWidget(QLabel("Giá thuê (VNĐ):"), 0, 0)
        f3.addWidget(self.ed["price"], 0, 1)
        f3.addWidget(QLabel("Tiền cọc (VNĐ):"), 1, 0)
        f3.addWidget(self.ed["deposit"], 1, 1)

        # ---------- nhóm 4: Tiện ích ----------
        _, f4 = self._group(4)
        self.ed["capacity"] = self._line("Ví dụ: 2 Ng/2 Xe")
        self.ed["ev_support"] = QCheckBox("⚡ Hỗ trợ sạc xe điện")
        self.ed["foreign_guest"] = QCheckBox("🌏 Nhận khách nước ngoài")
        f4.addWidget(QLabel("Tối đa (người/xe):"), 0, 0)
        f4.addWidget(self.ed["capacity"], 0, 1)
        f4.addWidget(self.ed["ev_support"], 1, 0, 1, 2)
        f4.addWidget(self.ed["foreign_guest"], 1, 2, 1, 2)

        # ---------- nhóm 5: Chính sách ----------
        _, f5 = self._group(5)
        self.ed["pet_policy"] = QComboBox()
        self.ed["pet_policy"].setEditable(True)
        self.ed["pet_policy"].addItems(["Cho nuôi Mèo", "Cho nuôi Chó",
                                        "Cho nuôi (chó/mèo)", "Không nuôi", ""])
        self.ed["pet_note"] = self._line("Chính sách chi tiết (giữ nguyên văn bản gốc)")
        f5.addWidget(QLabel("Nuôi thú cưng:"), 0, 0)
        f5.addWidget(self.ed["pet_policy"], 0, 1)
        f5.addWidget(QLabel("Ghi chú chính sách:"), 1, 0)
        f5.addWidget(self.ed["pet_note"], 1, 1)

        # ---------- nhóm 6: Liên hệ ----------
        _, f6 = self._group(6)
        self.ed["owner_phone"] = self._line("Ví dụ: 0868328147")
        self.ed["zalo_group"] = self._line("zalo.me/g/...")
        f6.addWidget(QLabel("SĐT chủ / admin:"), 0, 0)
        f6.addWidget(self.ed["owner_phone"], 0, 1)
        f6.addWidget(QLabel("Group Zalo:"), 1, 0)
        f6.addWidget(self.ed["zalo_group"], 1, 1)

        # ---------- nhóm 7: Media ----------
        _, f7 = self._group(7)
        self.ed["drive_link"] = self._line("drive.google.com/folder/...")
        self.ed["rating"] = self._line("Ví dụ: ⭐⭐⭐⭐ Ban công rộng")
        f7.addWidget(QLabel("Link Drive media:"), 0, 0)
        f7.addWidget(self.ed["drive_link"], 0, 1)
        f7.addWidget(QLabel("Đánh giá / độ đẹp:"), 1, 0)
        f7.addWidget(self.ed["rating"], 1, 1)

        # ---------- nhóm 8: Ghi chú & trạng thái ----------
        _, f8 = self._group(8)
        self.ed["status"] = QComboBox()
        for k in RoomStatus.ORDER:
            self.ed["status"].addItem(f"● {RoomStatus.label(k)}", k)
        self.ed["surveyed"] = QCheckBox("📸 Đã khảo sát (có ảnh/video)")
        self.ed["notes"] = QPlainTextEdit()
        self.ed["notes"].setMinimumHeight(72)
        self.ed["notes"].setPlaceholderText(
            "Chính sách, nội thất, tiện ích, ghi chú sale...")
        f8.addWidget(QLabel("Trạng thái:"), 0, 0)
        f8.addWidget(self.ed["status"], 0, 1)
        f8.addWidget(QLabel("Khảo sát:"), 1, 0)
        f8.addWidget(self.ed["surveyed"], 1, 1)
        f8.addWidget(QLabel("Ghi chú:"), 2, 0)
        f8.addWidget(self.ed["notes"], 2, 1)

    def _line(self, placeholder: str = "") -> QLineEdit:
        ed = QLineEdit()
        ed.setPlaceholderText(placeholder)
        return ed

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
                f"<span style='color:{C_OK};'>✓ Đã tự điền thông tin từ tòa "
                f"<b>{b.get('display')}</b></span>")
            self.banner.show()

    def _schedule_check(self, *_):
        self._debounce.start()

    def _run_check(self):
        payload = self.payload()
        if not (payload.get("house_number") or payload.get("street")):
            self.banner.hide()
            return
        try:
            res = self.mgr.check_new(payload, exclude_id=self.room.get("id") or None)
        except Exception as e:  # noqa: BLE001
            self.banner_label.setText(f"<span style='color:{C_DANGER};'>Lỗi kiểm tra: {e}</span>")
            self.banner.show()
            return
        self._last_check = {"room_exists": res.room_exists, "recommended": res.recommended}
        if res.room_exists:
            ex = res.existing_room or {}
            color = C_DANGER
            head = "⛔ PHÒNG NÀY ĐÃ TỒN TẠI"
            body = (f"{ex.get('room_code')} - {ex.get('address')} | "
                    f"trạng thái: {status_label(ex.get('status', ''))} | "
                    f"cập nhật: {ex.get('updated_at')}<br>"
                    f"<b>-> Bấm Lưu sẽ bị chặn. Hãy MỞ bản ghi cũ để sửa.</b>")
            self.btn_save.setEnabled(False)
            self.btn_open_dup.setVisible(True)
            self._dup_existing_id = ex.get("id")
        elif res.has_warn:
            color = C_ORANGE
            head = "⚠ NGHI NGỜ TRÙNG DỮ LIỆU"
            body = "<br>".join(f.message for f in res.findings if f.severity == "warn")
            self.btn_save.setEnabled(True)
            self.btn_open_dup.setVisible(False)
            self._dup_existing_id = None
        else:
            color = C_OK
            head = "✓ Không phát hiện trùng"
            info = [f.message for f in res.findings if f.kind in ("building_exists", "building_new")]
            body = info[0] if info else "Sẵn sàng lưu."
            self.btn_save.setEnabled(True)
            self.btn_open_dup.setVisible(False)
            self._dup_existing_id = None

        self.banner_label.setText(
            f"<b style='color:{color};'>{head}</b><br>"
            f"<span style='color:#475569;'>{body}</span>")
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
            "<span style='color:#64748B;'>📋 Phát hiện nháp nhập liệu chưa hoàn tất - "
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
            return ""

        pet_policy = self.ed["pet_policy"].currentText().strip()
        pet_note = txt("pet_note")
        notes = txt("notes")
        if pet_note:
            notes = (notes + " | " if notes else "") + f"Chính sách: {pet_note}"
        status_key = self.ed["status"].currentData() or "new"
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
            "ev_support": 1 if self.ed["ev_support"].isChecked() else 0,
            "foreign_guest": 1 if self.ed["foreign_guest"].isChecked() else 0,
            "pet_policy": pet_policy,
            "rating": txt("rating"),
            "owner_phone": txt("owner_phone"),
            "zalo_group": txt("zalo_group"),
            "drive_link": txt("drive_link"),
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
                room = self.mgr.update_room(rid, changes, actor=actor)
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
            self.banner_label.setText(f"<span style='color:{C_OK};'>✓ Đã lưu phòng "
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


# ------------------------------------------------------------------ wrapper hộp thoại (tách import)
def QMessageBox_Warning(parent, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(parent, title, text)


def QMessageBox_Critical(parent, title: str, text: str):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.critical(parent, title, text)


