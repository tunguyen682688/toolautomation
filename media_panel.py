# -*- coding: utf-8 -*-
"""media_panel.py - Khu "Ảnh / Video" trong panel chi tiết phòng.

- Hiển thị thumbnail nhanh ảnh + icon video của phòng đang chọn.
- Thêm file: nút ＋ hoặc KÉO THẢ file/thư mục vào danh sách -> app tự tạo thư mục
  quy ước (Data Image/<Quận>/<Đường>/<số nhà>-<mã phòng>/<loại> <giá>tr) rồi copy vào.
- LẤY NHANH: bấm 📋 Copy -> file nằm trong clipboard, dán thẳng vào Zalo/Telegram/Mail.
- Bấm đúp: mở bằng trình xem mặc định. 📂 mở thư mục quy ước. 🗑 chuyển vào _ThungRac.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QRect, QSize, QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QIcon, QImageReader,
                           QPixmap, QPainter, QFont, QPen, QPainterPath)
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

import media_manager as mm
import theme


def _thumb_pixmap(path: str, size: int) -> Optional[QPixmap]:
    """Đọc ảnh đã thu nhỏ NGAY KHI GIẢI MÃ (nhanh, ít RAM) - trả None nếu lỗi."""
    r = QImageReader(path)
    r.setAutoTransform(True)
    r.setScaledSize(QSize(size * 2, size * 2))       # x2 để nét trên màn DPI cao
    img = r.read()
    if img.isNull():
        return None
    return QPixmap.fromImage(img)


def _video_pixmap(size: int) -> QPixmap:
    """Icon đại diện video (không cần ffmpeg)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor(theme.c("bg_alt")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(theme.c("text3")))
    f = QFont()
    f.setPixelSize(size)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "🎬")
    p.end()
    return pm


def _placeholder_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor(theme.c("track")))
    return pm


class CoverPreview(QLabel):
    """Sơ lược ẢNH ĐẠI DIỆN của phòng trong panel chi tiết.

    Hiển thị ảnh đầu tiên (co giữ tỉ lệ, bo góc) + badge đếm "📷 N ảnh · ▶ M video"
    ở góc dưới bên phải. Bấm vào -> mở ảnh đầu tiên bằng trình xem mặc định;
    bấm chuột phải -> menu (mở ảnh / mở thư mục). Không có ảnh -> placeholder.
    """

    HEIGHT = 168

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.room: Optional[Dict[str, Any]] = None
        self._media: List[Dict[str, Any]] = []
        self._pm: Optional[QPixmap] = None
        self.setFixedHeight(self.HEIGHT)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"background:{theme.c('bg_alt')}; border:1px dashed {theme.c('border')};"
            " border-radius:12px; color:{0}; font-size:12px;".format(theme.c("text3")))
        self.setToolTip("Sơ lược ảnh đại diện — bấm để xem ảnh đầu tiên")

    # ================================================================ data
    def set_room(self, room: Optional[Dict[str, Any]]):
        self.room = room
        self._media = []
        self._pm = None
        if not room:
            self.setText("📷 Chưa có ảnh")
            self.setPixmap(QPixmap())
            return
        self._media = mm.list_media(room, self.mgr.settings)
        n_img = sum(1 for m in self._media if m["kind"] == "image")
        n_vid = sum(1 for m in self._media if m["kind"] == "video")
        first_img = next((m for m in self._media if m["kind"] == "image"), None)
        if first_img:
            self._pm = _thumb_pixmap(first_img["path"], self.HEIGHT)
            if self._pm is not None:
                self.setText("")
                self.setToolTip(
                    f"Ảnh đại diện: {first_img['name']}\n"
                    f"📷 {n_img} ảnh · ▶ {n_vid} video — bấm để xem ảnh đầu tiên")
                self.update()
                return
        # không có ảnh (hoặc ảnh lỗi) -> chữ
        if n_vid:
            self.setText(f"🎬 {n_vid} video · chưa có ảnh\nbấm ＋ Thêm để thêm ảnh phòng")
        else:
            self.setText("📷 Chưa có ảnh\nbấm ＋ Thêm bên dưới để thêm ảnh phòng")

    def media_counts(self):
        n_img = sum(1 for m in self._media if m["kind"] == "image")
        n_vid = sum(1 for m in self._media if m["kind"] == "video")
        return n_img, n_vid

    # ================================================================ paint
    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._pm is None or self._pm.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(3, 3, -3, -3)
        # ảnh co giữ tỉ lệ, cắt cho vừa khung (cover) trong vùng bo góc
        path = QPainterPath()
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 10, 10)
        p.save()
        p.setClipPath(path)
        pm = self._pm
        scale = max(r.width() / pm.width(), r.height() / pm.height())
        w, h = int(pm.width() * scale), int(pm.height() * scale)
        p.drawPixmap(r.x() + (r.width() - w) // 2, r.y() + (r.height() - h) // 2,
                     pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        p.restore()
        # badge đếm ở góc dưới phải
        n_img, n_vid = self.media_counts()
        badge = f"📷 {n_img}" + (f"  ▶ {n_vid}" if n_vid else "")
        f = QFont()
        f.setBold(True)
        f.setPointSize(9)
        p.setFont(f)
        br = self.rect()
        tw = p.fontMetrics().horizontalAdvance(badge) + 18
        bh = 22
        bx, by = br.right() - tw - 10, br.bottom() - bh - 8
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 23, 42, 210))
        p.drawRoundedRect(bx, by, tw, bh, 11, 11)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRect(bx, by, tw, bh), Qt.AlignCenter, badge)
        p.end()

    # ================================================================ tương tác
    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self._menu(ev.globalPosition().toPoint())
            return
        if ev.button() == Qt.LeftButton:
            first = next((m for m in self._media if m["kind"] == "image"), None)
            if first:
                QDesktopServices.openUrl(QUrl.fromLocalFile(first["path"]))
        super().mousePressEvent(ev)

    def _menu(self, pos):
        menu = QMenu(self)
        first = next((m for m in self._media if m["kind"] == "image"), None)
        if first:
            menu.addAction("🔍 Mở ảnh đầu tiên",
                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(first["path"])))
        if self.room:
            menu.addAction("📂 Mở thư mục ảnh phòng",
                           lambda: QDesktopServices.openUrl(
                               QUrl.fromLocalFile(str(mm.room_media_dir(self.room, self.mgr.settings)))))
        menu.exec(pos)


class MediaPanel(QWidget):
    """Khu quản lý media của 1 phòng (nhúng trong panel chi tiết)."""

    count_changed = Signal(int)      # số file hiện có (để trang Phòng hiển thị badge nếu cần)

    THUMB = 96

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.room: Optional[Dict[str, Any]] = None
        self._media: List[Dict[str, Any]] = []
        self._thumb_queue: List[QListWidgetItem] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ---- header: tiêu đề + đếm + nút hành động ----
        head = QHBoxLayout()
        head.setSpacing(6)
        t = QLabel("ẢNH / VIDEO")
        t.setStyleSheet(f"color:{theme.c('text3')}; font-size:11px; font-weight:800; "
                        "background:transparent; letter-spacing:0.5px;")
        head.addWidget(t)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(f"color:{theme.c('text3')}; font-size:11px; "
                                     "font-weight:700; background:transparent;")
        head.addWidget(self.lbl_count)
        head.addStretch(1)

        def mini(text: str, tip: str, slot) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("IconButton")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.clicked.connect(slot)
            return b

        self.btn_add = mini("＋ Thêm", "Chọn ảnh/video để copy vào thư mục quy ước của phòng",
                            self.add_files)
        self.btn_copy = mini("📋", "Copy file đang chọn -> dán thẳng vào Zalo/Telegram",
                             self.copy_selected)
        self.btn_trash = mini("🗑", "Chuyển file đang chọn vào _ThungRac", self.trash_selected)
        self.btn_open = mini("📂", "Mở thư mục quy ước của phòng", self.open_folder)
        self.btn_re = mini("🔄", "Nạp lại (nếu vừa chép file vào từ điện thoại)", self.refresh)
        for b in (self.btn_add, self.btn_copy, self.btn_trash, self.btn_open, self.btn_re):
            head.addWidget(b)
        lay.addLayout(head)

        # ---- đường dẫn quy ước ----
        self.ed_path = QLineEdit()
        self.ed_path.setReadOnly(True)
        self.ed_path.setObjectName("MediaPath")
        self.ed_path.setStyleSheet(
            f"background:{theme.c('bg_alt')}; color:{theme.c('text2')};"
            "border:1px solid " + theme.c("border_soft") + "; border-radius:8px;"
            "font-size:11px; padding:4px 8px;")
        self.ed_path.setToolTip("Thư mục quy ước: copy file vào đây là app tự liệt kê")
        lay.addWidget(self.ed_path)

        # ---- danh sách thumbnail ----
        self.list = QListWidget()
        self.list.setObjectName("MediaList")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(self.THUMB, self.THUMB))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setWordWrap(True)
        self.list.setFixedHeight(150)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemDoubleClicked.connect(self._open_item)
        self.list.itemSelectionChanged.connect(self._sel_changed)
        lay.addWidget(self.list)

        # hint + trạng thái rỗng
        self.lbl_empty = QLabel("Chưa có ảnh/video. Bấm ＋ Thêm hoặc KÉO THẢ file vào đây.")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet(
            f"color:{theme.c('text3')}; font-size:11.5px; background:{theme.c('bg_alt')};"
            "border:1px dashed " + theme.c("border") + "; border-radius:10px; padding:12px;")
        lay.addWidget(self.lbl_empty)

        self.setAcceptDrops(True)
        self.set_room(None)

    # ================================================================ data
    def set_room(self, room: Optional[Dict[str, Any]]):
        self.room = room
        self._thumb_queue.clear()
        if not room:
            self.ed_path.setText("")
            self.list.clear()
            self.lbl_empty.setVisible(True)
            self.lbl_count.setText("")
            self.count_changed.emit(0)
            return
        d = mm.room_media_dir(room, self.mgr.settings)
        self.ed_path.setText(str(d))
        self.ed_path.setToolTip("Quy ước: <gốc>/<Quận>/<Đường>/<số nhà>-<mã phòng>/<loại> <giá>tr")
        self.refresh()

    def refresh(self):
        """Quét lại thư mục quy ước (FileSystem là nguồn sự thật)."""
        self.list.clear()
        if not self.room:
            return
        self._media = mm.list_media(self.room, self.mgr.settings)
        n_img = sum(1 for m in self._media if m["kind"] == "image")
        n_vid = sum(1 for m in self._media if m["kind"] == "video")
        self.lbl_count.setText(
            f"({len(self._media)} file · {n_img} ảnh · {n_vid} video)" if self._media else "")
        self.lbl_empty.setVisible(not self._media)
        self.count_changed.emit(len(self._media))
        for m in self._media:
            it = QListWidgetItem(m["name"])
            it.setData(Qt.UserRole, m["path"])
            tip = (f"{'Ảnh' if m['kind'] == 'image' else 'Video' if m['kind'] == 'video' else 'File'} · "
                   f"{mm.human_size(m['size'])} · {mm.age_label(m['mtime'])}\n{m['path']}\n"
                   "Bấm đúp: mở xem · 📋: copy để dán vào Zalo")
            it.setToolTip(tip)
            it.setSizeHint(QSize(self.THUMB + 8, self.THUMB + 22))
            it.setIcon(QIcon(_placeholder_pixmap(self.THUMB)))
            self.list.addItem(it)
            self._thumb_queue.append(it)
        self._pump_thumbs()

    def _pump_thumbs(self):
        """Nạp thumbnail từng đợt nhỏ để không đơ UI khi phòng có nhiều ảnh."""
        if not self._thumb_queue:
            return
        for _ in range(6):
            if not self._thumb_queue:
                break
            it = self._thumb_queue.pop(0)
            path = it.data(Qt.UserRole)
            kind = mm.kind_of(Path(path))
            pm = None
            if kind == "image":
                pm = _thumb_pixmap(path, self.THUMB)
            elif kind == "video":
                pm = _video_pixmap(self.THUMB)
            if pm is not None:
                it.setIcon(QIcon(pm))
            else:
                it.setIcon(QIcon(_placeholder_pixmap(self.THUMB)))
        if self._thumb_queue:
            QTimer.singleShot(15, self._pump_thumbs)

    # ================================================================ hành động
    def add_files(self):
        if not self.room:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh / video của phòng", "",
            "Media (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.mp4 *.mov *.avi *.mkv *.webm *.m4v *.3gp);;Tất cả file (*.*)")
        self._import(files)

    def _import(self, files: List[str]):
        if not self.room or not files:
            return
        res = mm.import_files(self.room, files, self.mgr.settings)
        if res["copied"]:
            self.lbl_empty.setVisible(True)   # refresh() sẽ cập nhật lại
        self.refresh()
        msg = []
        if res["copied"]:
            msg.append(f"Đã thêm {len(res['copied'])} file vào:\n{mm.room_media_dir(self.room, self.mgr.settings)}")
        if res["skipped"]:
            msg.append(f"Bỏ qua {len(res['skipped'])} file trùng (đã có sẵn).")
        if res["errors"]:
            msg.append("Lỗi:\n" + "\n".join(res["errors"][:5]))
        if msg:
            QMessageBox.information(self, "Ảnh / Video", "\n\n".join(msg))

    def _selected_paths(self) -> List[str]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    def copy_selected(self):
        """LẤY NHANH: copy file vào clipboard -> dán thẳng vào Zalo/Telegram/Mail."""
        paths = self._selected_paths()
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        QApplication.clipboard().setMimeData(mime)
        self.lbl_count.setToolTip(f"Đã copy {len(paths)} file vào clipboard - dán (Ctrl+V) vào Zalo/Telegram")

    def trash_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        if QMessageBox.question(
                self, "Bỏ vào thùng rác",
                f"Chuyển {len(paths)} file vào _ThungRac (không mất ngay)?") != QMessageBox.Yes:
            return
        moved = mm.move_to_trash(paths, self.mgr.settings)
        self.refresh()
        if moved:
            self.lbl_count.setToolTip(f"Đã chuyển {len(moved)} file vào _ThungRac")

    def open_folder(self):
        if not self.room:
            return
        d = mm.ensure_room_dir(self.room, self.mgr.settings)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ================================================================ tương tác item
    def _open_item(self, item: QListWidgetItem):
        p = item.data(Qt.UserRole)
        if p:
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _sel_changed(self):
        n = len(self.list.selectedItems())
        for b in (self.btn_copy, self.btn_trash):
            b.setEnabled(n > 0)
            b.setToolTip(f"{'Copy' if b is self.btn_copy else 'Bỏ vào thùng rác'} "
                         f"{n} file đang chọn" if n else
                         ("Copy file -> dán vào Zalo" if b is self.btn_copy else "Chuyển vào _ThungRac"))

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("🔍 Mở xem (trình xem mặc định)", lambda: self._open_item(self.list.itemAt(pos)))
        menu.addAction("📋 Copy file (dán vào Zalo)", self.copy_selected)
        menu.addAction("📂 Mở thư mục", self.open_folder)
        menu.addSeparator()
        menu.addAction("🗑 Bỏ vào _ThungRac", self.trash_selected)
        menu.exec(self.list.mapToGlobal(pos))

    # ================================================================ kéo thả
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        if not self.room:
            return
        files: List[str] = []
        for u in ev.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.is_file():
                files.append(str(p))
            elif p.is_dir():                      # thả cả THƯ MỤC -> lấy hết media trong đó
                files += [str(f) for f in p.iterdir()
                          if f.is_file() and f.suffix.lower() in
                          (mm.IMAGE_EXTS | mm.VIDEO_EXTS)]
        ev.acceptProposedAction()
        if files:
            self._import(files)
