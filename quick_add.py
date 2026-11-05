# -*- coding: utf-8 -*-
"""quick_add.py - Tạo phòng NHANH từ tin nhắn Zalo: copy ảnh -> dán -> Enter là xong.

Bài toán: phòng được gửi qua Zalo (ảnh + tin nhắn). Trước đây muốn đưa vào kho
phải bấm "Thêm phòng" rồi mò file trong thư mục Downloads. Giờ chỉ cần:

  1. Trong Zalo: copy ảnh phòng (Ctrl+C) - lấy được cả file lẫn ảnh bitmap.
  2. Trang Phòng -> nút "⚡ Tạo nhanh từ Zalo".
  3. Dialog TỰ đọc clipboard: ảnh hiện xem trước ngay; chữ trong tin (nếu có)
     tự tách địa chỉ / giá / dạng phòng để điền sẵn (chỉ điền field còn trống).
  4. Check LIVE (debounce 250ms) 3 lớp:
       🏢 TÒA NHÀ đã có chưa?   -> tự liên kết / tạo tòa mới
       🧱 LOẠI PHÒNG đó đã có trong tòa chưa? -> liệt kê mã phòng đang có
       ⛔ Trùng số căn/mã       -> chặn Lưu + nút "Mở bản ghi cũ"
  5. Enter -> lưu -> ảnh tự copy vào THƯ MỤC QUY ƯỚC của phòng -> mở panel chi tiết.

Module tách 3 hàm thuần (autofill_from_text / type_in_building / norm_price) để
kiểm thử backend không cần mở Qt.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

import media_manager as mm
import text_utils as tu
import theme
from inventory_manager import DuplicateError
from models import ROOM_TYPES, RoomStatus

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")


# ================================================================ helper thuần (test không cần Qt)
def norm_price(raw: Any) -> Optional[int]:
    """Giá ô text -> int VNĐ hoặc None (NULL = Chưa biết).

    rỗng / không đọc được -> None, KHÔNG bao giờ ép về 0 (0 nghĩa là "Không").
    """
    s = str(raw or "").strip()
    if not s:
        return None
    v = tu.normalize_price(s)
    return int(v) if v else None


def autofill_from_text(text: str) -> Dict[str, Any]:
    """Tin nhắn Zalo / tin đăng -> {field: giá trị} CHỈ gồm field nào tách được.

    Dùng `text_utils.parse_listing_text` (tách địa chỉ, giá, dạng phòng, tầng,
    diện tích, SĐT...). Field không tách được sẽ KHÔNG xuất hiện trong dict ->
    form chỉ điền vào ô còn trống, không ghi đè dữ liệu người dùng đã nhập.

    Trả {} nếu chữ KHÔNG giống tin đăng (chỉ có "cảm ơn bạn" thì đừng tự điền gì).
    """
    p = tu.parse_listing_text(text or "")
    # phải tách được ÍT NHẤT địa chỉ / giá / dạng phòng thì mới coi là tin đăng
    if not (str(p.get("house_number") or "").strip()
            or str(p.get("street") or "").strip()
            or p.get("price") or str(p.get("room_type") or "").strip()):
        return {}
    out: Dict[str, Any] = {}
    # KHÔNG nhận `notes`: parse_listing_text gán notes = nguyên văn text ->
    # điền vào ô Ghi chú sẽ bị thừa/đụng dữ liệu người dùng đã gõ.
    for k in ("house_number", "street", "ward", "district", "room_code",
              "room_type", "area", "floor", "capacity", "owner_phone",
              "service_fee", "access_hours", "amenities"):
        v = str(p.get(k) or "").strip()
        if v:
            out[k] = v
    if p.get("price"):
        out["price"] = int(p["price"])
    if p.get("deposit"):
        out["deposit"] = int(p["deposit"])
    # nhóm 5: 0 = Không cũng phải truyền (không chỉ 1 = Có)
    for k in ("ev_support", "foreign_guest"):
        if p.get(k) in (0, 1):
            out[k] = int(p[k])
    if p.get("pet_policy"):
        out["pet_policy"] = p["pet_policy"]
    # tin NHIỀU PHÒNG (vd 'Mã 501_502: 6.400.000') -> chỉ gợi ý, không tự tạo
    rooms = [str(r.get("room_code") or "") for r in (p.get("_rooms") or [])
             if r.get("room_code")]
    if len(rooms) >= 2:
        out["_rooms"] = rooms
    return out


def type_in_building(db, building_id: str, room_type: str,
                     limit: int = 8) -> Dict[str, Any]:
    """LOẠI PHÒNG (dạng phòng) này đã có trong tòa nhà đó chưa?

    Trả {"count": số phòng cùng loại, "codes": [mã phòng...], "truncated": bool}
    - building_id rỗng / chưa chọn loại -> {"count": 0, "codes": []}
    """
    bt = str(room_type or "").strip()
    if not building_id or not bt:
        return {"count": 0, "codes": [], "truncated": False}
    rows = db.search_rooms_sql(
        "r.building_id=? AND r.deleted=0 AND r.room_type=?",
        (str(building_id), bt), order="r.room_code", limit=limit + 1)
    codes = [str(r.get("room_code") or r.get("unit_code") or "?") for r in rows[:limit]]
    return {"count": len(rows), "codes": codes, "truncated": len(rows) > limit}


# ================================================================ dialog
class QuickAddDialog(QDialog):
    """Tạo phòng nhanh từ clipboard (ảnh Zalo + chữ tin nhắn)."""

    room_created = Signal(str)     # room_id vừa lưu
    open_room = Signal(str)        # mở bản ghi trùng đã có

    def __init__(self, mgr, parent=None):
        super().__init__(parent)
        self.mgr = mgr
        self.db = mgr.db
        self.ed: Dict[str, Any] = {}
        self.img_paths: List[str] = []
        self._autofilled = False
        self._extra_fields: Dict[str, Any] = {}   # trường parse được nhưng form không có ô (cọc, phí DV...)
        self._dup_id = ""
        self.saved_room_id = ""
        self.saved_images = 0

        self.setWindowTitle("⚡ Tạo phòng nhanh từ Zalo")
        self.setMinimumSize(920, 590)
        self._build()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._run_check)
        for w in self.ed.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._debounce.start)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._debounce.start)

        self._read_clipboard()      # đọc NGAY: ảnh Zalo + chữ tin nhắn
        self._run_check()           # banner + trạng thái nút Lưu ngay từ đầu

    # ------------------------------------------------------------------ UI
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(18)
        outer.addLayout(body, 1)

        # ================= TRÁI: form =================
        left = QVBoxLayout()
        left.setSpacing(8)
        body.addLayout(left, 3)

        title = QLabel("⚡ Tạo phòng nhanh từ Zalo")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("background:transparent;")
        left.addWidget(title)

        hint = QLabel(
            "Trong Zalo <b>copy ảnh phòng</b> → quay lại đây là ảnh tự vào. "
            "Chữ trong tin tự điền địa chỉ / giá / dạng phòng. "
            "<b>Enter = Lưu & mở phòng</b>.")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet(
            f"font-size:12.5px; color:{theme.c('text2')}; background:transparent;")
        left.addWidget(hint)

        # ---- banner check 3 lớp ----
        self.banner = QFrame()
        self.banner.setObjectName("Card")
        bnl = QVBoxLayout(self.banner)
        bnl.setContentsMargins(14, 10, 14, 10)
        bnl.setSpacing(6)
        self.banner_label = QLabel("Đang kiểm tra...")
        self.banner_label.setWordWrap(True)
        self.banner_label.setTextFormat(Qt.RichText)
        self.banner_label.setStyleSheet("background:transparent;")
        bnl.addWidget(self.banner_label)
        self.lbl_autofill = QLabel("")
        self.lbl_autofill.setWordWrap(True)
        self.lbl_autofill.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{theme.c('accent')};"
            " background:transparent;")
        self.lbl_autofill.hide()
        bnl.addWidget(self.lbl_autofill)
        dup_row = QHBoxLayout()
        dup_row.addStretch(1)
        self.btn_open_dup = QPushButton("📂  Mở bản ghi trùng")
        self.btn_open_dup.setObjectName("Ghost")
        self.btn_open_dup.setFixedHeight(28)
        self.btn_open_dup.clicked.connect(self._open_dup)
        self.btn_open_dup.hide()
        dup_row.addWidget(self.btn_open_dup)
        bnl.addLayout(dup_row)
        left.addWidget(self.banner)

        # ---- form rút gọn: 6 dòng, label bên trái ----
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        left.addLayout(grid)

        def add(row, col, key, label, placeholder="", combo=False):
            lb = QLabel(label)
            lb.setStyleSheet(
                f"font-size:12px; font-weight:700; color:{theme.c('text2')};"
                " background:transparent;")
            grid.addWidget(lb, row, col * 2)
            if combo:
                w = QComboBox()
                w.setEditable(True)
                w.setInsertPolicy(QComboBox.NoInsert)
                w.addItem("", "")
                for t in ROOM_TYPES:
                    w.addItem(t, t)
                w.setPlaceholderText(placeholder or "Chọn / gõ mới")
            else:
                w = QLineEdit()
                w.setPlaceholderText(placeholder)
            self.ed[key] = w
            grid.addWidget(w, row, col * 2 + 1)
            return w

        add(0, 0, "house_number", "Số nhà", "86")
        add(0, 1, "street", "Đường", "Nguyễn Thượng Hiền")
        add(1, 0, "ward", "Phường", "P. 13")
        add(1, 1, "district", "Quận", "Q. Bình Thạnh")
        add(2, 0, "unit_code", "Số căn", "79/16  (khuyến nghị)")
        add(2, 1, "room_code", "Mã phòng", "P-86")
        add(3, 0, "room_type", "Dạng phòng", "Studio / 1 PN...", combo=True)
        add(3, 1, "price", "Giá thuê", "7tr  (để trống = Chưa biết)")
        add(4, 0, "area", "Diện tích", "45m2")
        add(4, 1, "floor", "Tầng", "3")
        add(5, 0, "owner_phone", "SĐT chủ", "09...")
        add(5, 1, "notes", "Ghi chú", "tiện ích, chủ nhà...")
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # ================= PHẢI: ảnh từ Zalo =================
        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 2)

        ih = QLabel("ẢNH TIN NHẮN ZALO")
        ih.setStyleSheet(
            f"font-size:11px; font-weight:800; color:{theme.c('text3')};"
            " background:transparent; letter-spacing:0.6px;")
        right.addWidget(ih)

        self.img_preview = QLabel("Chưa có ảnh\n\nCopy ảnh trong Zalo\nrồi bấm ⚡ hoặc 📋")
        self.img_preview.setFixedSize(268, 176)
        self.img_preview.setAlignment(Qt.AlignCenter)
        self.img_preview.setWordWrap(True)
        self.img_preview.setStyleSheet(
            f"border:1px dashed {theme.c('border')}; border-radius:8px;"
            f" color:{theme.c('text3')}; background:{theme.c('card2')};"
            " font-size:12px;")
        right.addWidget(self.img_preview, 0, Qt.AlignHCenter)

        self.lbl_imgs = QLabel("Chưa có ảnh - ảnh sẽ tự vào thư mục quy ước khi Lưu")
        self.lbl_imgs.setWordWrap(True)
        self.lbl_imgs.setStyleSheet(
            f"font-size:11.5px; color:{theme.c('text2')}; background:transparent;")
        right.addWidget(self.lbl_imgs)

        ibtns = QHBoxLayout()
        ibtns.setSpacing(6)
        self.btn_paste = QPushButton("📋  Dán ảnh")
        self.btn_paste.setObjectName("Ghost")
        self.btn_paste.setToolTip(
            "Đọc clipboard ngay: ảnh copy từ Zalo (file hoặc bitmap)\n"
            "+ chữ tin nhắn để tự điền địa chỉ / giá / dạng phòng")
        self.btn_paste.clicked.connect(self._read_clipboard)
        ibtns.addWidget(self.btn_paste)
        self.btn_pick = QPushButton("📁  Chọn file")
        self.btn_pick.setObjectName("Ghost")
        self.btn_pick.clicked.connect(self._pick_files)
        ibtns.addWidget(self.btn_pick)
        self.btn_clear = QPushButton("🗑")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.setFixedWidth(34)
        self.btn_clear.clicked.connect(self._clear_images)
        ibtns.addWidget(self.btn_clear)
        right.addLayout(ibtns)

        tip = QLabel(
            f"Ảnh lưu bền vào thư mục quy ước:\n"
            f"<b>&lt;Quận&gt;/&lt;Đường&gt;/&lt;số-nhà-mã&gt;/&lt;loại&gt; &lt;giá&gt;tr</b>")
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.RichText)
        tip.setStyleSheet(
            f"font-size:11px; color:{theme.c('text3')}; background:transparent;")
        right.addWidget(tip)
        right.addStretch(1)

        # ================= dưới: nút =================
        bb = QHBoxLayout()
        bb.setSpacing(8)
        lbl_enter = QLabel("💡 Enter = Lưu & mở phòng")
        lbl_enter.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{theme.c('text3')};"
            " background:transparent;")
        bb.addWidget(lbl_enter)
        bb.addStretch(1)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.setObjectName("Ghost")
        btn_cancel.clicked.connect(self.reject)
        bb.addWidget(btn_cancel)
        self.btn_save = QPushButton("💾  Lưu & mở (Enter)")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setAutoDefault(True)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        bb.addWidget(self.btn_save)
        outer.addLayout(bb)

    # ------------------------------------------------------------------ clipboard
    def changeEvent(self, ev):
        """Alt-tab về app sau khi copy ảnh trong Zalo -> tự đọc lại clipboard."""
        if ev.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._read_clipboard()
        super().changeEvent(ev)

    def _read_clipboard(self, *_):
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime is None:
            return
        added: List[str] = []
        # 1) file (copy từ Zalo/Explorer -> CF_HDROP)
        if mime.hasUrls():
            for url in mime.urls():
                p = url.toLocalFile()
                if (p and Path(p).suffix.lower() in IMG_EXT
                        and Path(p).exists() and p not in self.img_paths
                        and p not in added):
                    added.append(p)
        # 2) ảnh bitmap (Zalo hay copy dạng này) -> lưu tạm PNG
        if not added and mime.hasImage():
            img = cb.image()
            if not img.isNull():
                tmp = Path(tempfile.gettempdir()) / \
                    f"zalo_paste_{int(time.time() * 1000)}.png"
                if img.save(str(tmp), "PNG") and str(tmp) not in self.img_paths:
                    added.append(str(tmp))
        if added:
            self.img_paths.extend(added)
            self._refresh_images()

        # 3) chữ trong clipboard -> tự điền field còn trống (không ghi đè)
        text = (mime.text() or "").strip()
        if text and not self._autofilled:
            fields = autofill_from_text(text)
            if fields:
                self._apply_autofill(fields)
                self._autofilled = True

        if hasattr(self, "_debounce"):
            self._debounce.start()

    def _apply_autofill(self, fields: Dict[str, Any]):
        labels = {"house_number": "số nhà", "street": "đường", "ward": "phường",
                  "district": "quận", "room_code": "mã phòng",
                  "room_type": "dạng phòng", "price": "giá",
                  "area": "diện tích", "floor": "tầng", "capacity": "sức chứa",
                  "owner_phone": "SĐT chủ", "notes": "ghi chú",
                  "deposit": "cọc", "pet_policy": "thú cưng",
                  "service_fee": "phí dịch vụ", "access_hours": "giờ giấc",
                  "amenities": "tiện ích"}
        filled = []
        for k, v in fields.items():
            w = self.ed.get(k)
            if w is None:
                # trường parse được nhưng form rút gọn không có ô nhập
                # (cọc, phí DV, giờ giấc, tiện ích...) -> GIỮ lại, payload() sẽ gửi
                self._extra_fields[k] = v
                continue
            if isinstance(w, QComboBox):
                if not w.currentText().strip():
                    w.setCurrentText(str(v))
                    filled.append(labels.get(k, k))
            elif not w.text().strip():
                if k == "price" and isinstance(v, int):
                    w.setText(tu.format_money(v))
                else:
                    w.setText(str(v))
                filled.append(labels.get(k, k))
        if filled or fields.get("_rooms"):
            msg = "✨ Đã tự điền từ tin nhắn: " + ", ".join(filled) if filled else "✨ Tin nhắn"
            rooms = [r for r in fields.get("_rooms") or [] if r]
            if len(rooms) >= 2:
                # tin nhiều phòng: điền MÃ ĐẦU, nhắc vào Sửa phòng để tách từng phòng
                msg += (f" · tin có <b>{len(rooms)} phòng</b>: "
                        f"{', '.join(rooms)} (bấm Sửa phòng để tách)")
            self.lbl_autofill.setText(msg)
            self.lbl_autofill.show()

    def _refresh_images(self):
        n = len(self.img_paths)
        if not n:
            self.img_preview.clear()
            self.img_preview.setText("Chưa có ảnh\n\nCopy ảnh trong Zalo\nrồi bấm ⚡ hoặc 📋")
            self.lbl_imgs.setText(
                "Chưa có ảnh - ảnh sẽ tự vào thư mục quy ước khi Lưu")
            return
        names = " · ".join(Path(p).name for p in self.img_paths[:3])
        more = f"  +{n - 3} ảnh khác" if n > 3 else ""
        self.lbl_imgs.setText(f"🖼 {n} ảnh: {names}{more}")
        self.lbl_imgs.setToolTip("\n".join(self.img_paths))
        pm = QPixmap(self.img_paths[0])
        if pm.isNull():
            self.img_preview.setText("Không đọc được ảnh đầu tiên")
            return
        self.img_preview.clear()
        self.img_preview.setPixmap(pm.scaled(
            self.img_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh phòng", "",
            "Ảnh (*.jpg *.jpeg *.png *.webp *.bmp *.gif);;Tất cả file (*.*)")
        for f in files:
            if f not in self.img_paths:
                self.img_paths.append(f)
        if files:
            self._refresh_images()

    def _clear_images(self):
        self.img_paths = []
        self._refresh_images()

    # ------------------------------------------------------------------ dữ liệu
    def payload(self) -> Dict[str, Any]:
        g = lambda k: str(self.ed[k].text()).strip()   # noqa: E731
        return {
            "house_number": g("house_number"),
            "street": g("street"),
            "ward": g("ward"),
            "district": g("district"),
            "unit_code": g("unit_code"),
            "room_code": g("room_code"),
            "room_type": str(self.ed["room_type"].currentText() or "").strip(),
            "price": norm_price(g("price")),          # rỗng -> None (Chưa biết)
            "area": g("area"),
            "floor": g("floor"),
            "owner_phone": g("owner_phone"),
            "notes": g("notes"),
            "status": "new",
            # trường parse được nhưng form rút gọn không có ô: cọc, phí DV,
            # giờ giấc, tiện ích + nhóm 5 (xe điện / thú cưng / nước ngoài)
            **{k: v for k, v in self._extra_fields.items() if k in
               ("deposit", "service_fee", "access_hours", "amenities",
                "ev_support", "pet_policy", "foreign_guest")},
        }

    def _set_banner(self, color: str, head: str, body: str = ""):
        self.banner_label.setText(
            f"<b style='color:{color};'>{head}</b>"
            + (f"<br><span style='color:{theme.c('text2')};'>{body}</span>"
               if body else ""))
        self.banner.show()

    def _type_line(self, building, ptype: str) -> str:
        """Dòng check LOẠI PHÒNG đã có trong tòa chưa."""
        if not building:
            return (f"<br>🆕 Tòa mới - sẽ tạo tòa + phòng loại <b>{ptype}</b>."
                    if ptype else "")
        if not ptype:
            return (f"<br>🏢 Tòa <b>{building.get('display')}</b> đã có - "
                    "chọn DẠNG PHÒNG để kiểm tra loại đã có chưa.")
        th = type_in_building(self.db, building.get("id") or "", ptype)
        if th["count"]:
            codes = ", ".join(th["codes"]) + (" …" if th.get("truncated") else "")
            return (f"<br>🧱 Tòa này đã có <b>{th['count']} phòng {ptype}</b>: "
                    f"{codes} - kiểm tra kỹ trước khi thêm.")
        return (f"<br>🆕 Tòa <b>{building.get('display')}</b> đã có nhưng "
                f"<b>CHƯA có phòng loại {ptype}</b> -> tạo mới.")

    def _run_check(self, *_):
        """Check LIVE: tòa nhà đã có? · loại phòng đã có trong tòa? · trùng mã?"""
        p = self.payload()
        has_addr = bool(p.get("house_number") or p.get("street"))
        has_id = bool(p.get("unit_code")) or tu.valid_room_code(p.get("room_code"))
        self._dup_id = ""
        self.btn_open_dup.hide()

        if not has_addr:
            self._set_banner(
                theme.c("text2"), "Nhập <b>SỐ NHÀ</b> hoặc <b>TÊN ĐƯỜNG</b>",
                "để kiểm tra tòa nhà đã có chưa và loại phòng đã có trong tòa chưa.")
            self.btn_save.setEnabled(False)
            return
        if not has_id:
            self._set_banner(
                theme.c("orange"), "Thiếu khoá nhận diện phòng",
                "Nhập <b>SỐ CĂN</b> (khuyến nghị) hoặc <b>MÃ PHÒNG</b> có chữ số "
                "để chống trùng - chương trình không tự suy đoán.")
            self.btn_save.setEnabled(False)
            return
        try:
            res = self.mgr.check_new(p)
        except Exception as e:  # noqa: BLE001
            self._set_banner(theme.c("danger"), f"Lỗi kiểm tra: {e}")
            self.btn_save.setEnabled(False)
            return

        tline = self._type_line(res.building, p.get("room_type") or "")
        if res.room_exists:
            ex = res.existing_room or {}
            self._set_banner(
                theme.c("danger"), "⛔ PHÒNG NÀY ĐÃ TỒN TẠI",
                f"{ex.get('room_code') or ex.get('unit_code')} - {ex.get('address')} "
                f"| trạng thái: {RoomStatus.label(ex.get('status') or '')}"
                f"<br><b>-&gt; Enter sẽ bị chặn. Bấm \"Mở bản ghi cũ\" để sửa.</b>"
                + tline)
            self._dup_id = str(ex.get("id") or "")
            self.btn_open_dup.show()
            self.btn_save.setEnabled(False)
            return
        if res.has_warn:
            body = "<br>".join(f.message for f in res.findings
                               if f.severity == "warn")
            self._set_banner(
                theme.c("orange"), "⚠ NGHI NGỜ TRÙNG DỮ LIỆU",
                body + "<br><b>-&gt; Enter để lưu vẫn được.</b>" + tline)
            self.btn_save.setEnabled(True)
            return
        info = next((f.message for f in res.findings
                     if f.kind in ("building_exists", "building_new")), "")
        self._set_banner(theme.c("ok"), "✓ Sẵn sàng lưu", info + tline)
        self.btn_save.setEnabled(True)

    def _save(self, *_):
        p = self.payload()
        if not (p.get("house_number") or p.get("street")) or not (
                p.get("unit_code") or tu.valid_room_code(p.get("room_code"))):
            self._run_check()
            return
        try:
            res = self.mgr.check_new(p)
        except Exception as e:  # noqa: BLE001
            self._set_banner(theme.c("danger"), f"Lỗi kiểm tra: {e}")
            return
        if res.room_exists:
            self._run_check()
            return
        actor = self.mgr.settings.get("user_name") or "Admin"
        try:
            # chỉ force khi đã cảnh báo (banner đang hiển thị) và không trùng thật
            room = self.mgr.add_room(p, actor=actor, force=bool(res.has_warn))
        except DuplicateError as e:
            self._run_check()
            self._set_banner(theme.c("danger"), "⛔ KHÔNG LƯU ĐƯỢC - TRÙNG",
                             e.result.messages("<br>"))
            return

        imgs = 0
        if self.img_paths:
            out = mm.import_files(room, self.img_paths, self.mgr.settings)
            imgs = len(out.get("copied") or []) + len(out.get("skipped") or [])
        self.saved_room_id = str(room.get("id") or "")
        self.saved_images = imgs
        self.room_created.emit(self.saved_room_id)
        self.accept()

    def _open_dup(self):
        if self._dup_id:
            self.open_room.emit(self._dup_id)
        self.reject()
