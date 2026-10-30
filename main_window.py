# -*- coding: utf-8 -*-
"""main_window.py - Cửa sổ chính: sidebar điều hướng, thanh tìm kiếm (debounce 150ms + popup),
trạng thái đồng bộ, phím tắt, và vòng poll sự kiện an toàn từ worker thread.

NGUYÊN TẮC AN TOÀN THREAD: sự kiện từ SyncWorker / InventoryManager chỉ được đọc qua
``QTimer`` trên UI thread (deque) -> không bao giờ chạm widget từ thread nền.
"""
from __future__ import annotations

import queue
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListView, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

import text_utils as tu
from models import RoomFilter, RoomStatus
from theme import APP_QSS, status_bg, status_color, status_label

from config import APP_ENV, env_badge, DATA_DIR

# màu nhận diện môi trường (nhắc người dùng đang thao tác ở đâu)
ENV_COLORS = {"prod": "#16A34A", "staging": "#D97706", "dev": "#6B7280"}

NAV_ITEMS = [
    ("dashboard", "🏠", "Tổng quan"),
    ("buildings", "🏢", "Tòa nhà"),
    ("rooms", "📋", "Phòng"),
]


# ------------------------------------------------------------------ popup gợi ý tìm kiếm
from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402


class SearchPopupReal(QListView):
    chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPopup")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(540)
        self.setFixedHeight(360)
        self.setModel(QStandardItemModel())
        self.clicked.connect(self._on_click)

    def set_results(self, items: List[Dict[str, Any]]):
        m = QStandardItemModel()
        m.setColumnCount(1)
        for it in items:
            st = it.get("status", "")
            item = QStandardItem(
                f"● {it.get('room_code') or '(chưa có mã)'}   ·   {it.get('address', '')}\n"
                f"   {status_label(st)} · {tu.format_money(it.get('price'))} ₫ · "
                f"{it.get('room_type') or '—'} · {it.get('unit_code') or '—'}")
            item.setData(it, Qt.UserRole)
            from PySide6.QtGui import QColor, QFont
            item.setForeground(QColor("#0F172A"))
            f = QFont()
            f.setPointSize(10)
            item.setFont(f)
            m.appendRow(item)
        self.setModel(m)

    def _on_click(self, index: QModelIndex):
        data = index.data(Qt.UserRole)
        if isinstance(data, dict):
            self.chosen.emit(data.get("id", ""))
            self.hide()


# ------------------------------------------------------------------ cửa sổ chính
class MainWindow(QMainWindow):
    def __init__(self, manager, worker, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.worker = worker
        self.event_queue: "queue.Queue[Dict]" = queue.Queue()
        self._nav = "dashboard"

        self.setWindowTitle(
            f"Kho Phòng Căn Hộ - Quản lý kho căn hộ cho thuê  [{env_badge()}]")
        self.resize(1440, 900)
        self.setStyleSheet(APP_QSS)

        self._build_ui()
        self._build_shortcuts()
        self._wire_events()

        # poll sự kiện từ thread nền (UI thread an toàn)
        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._drain_events)
        self._poll.start()

        # đồng bộ trạng thái chu kỳ
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._update_sync_status)
        self._status_timer.start()

        self.navigate("dashboard")
        self._update_sync_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sidebar ----
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 16)
        sl.setSpacing(4)

        title = QLabel("🏠 KHO PHÒNG")
        title.setObjectName("AppTitle")
        sl.addWidget(title)
        sub = QLabel("Quản lý kho căn hộ cho thuê")
        sub.setObjectName("AppSubtitle")
        sl.addWidget(sub)
        sl.addSpacing(18)

        self.nav_buttons: Dict[str, QPushButton] = {}
        for key, icon, label in NAV_ITEMS:
            b = QPushButton(f"{icon}  {label}")
            b.setObjectName("NavButton")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, k=key: self.navigate(k))
            sl.addWidget(b)
            self.nav_buttons[key] = b

        sl.addSpacing(10)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#E4E8F0;")
        sl.addWidget(line)
        sl.addSpacing(6)

        self.btn_import = QPushButton("📥  Nhập Excel")
        self.btn_import.setObjectName("NavButton")
        self.btn_import.clicked.connect(self.open_import)
        sl.addWidget(self.btn_import)

        self.btn_export = QPushButton("📤  Xuất Excel")
        self.btn_export.setObjectName("NavButton")
        self.btn_export.clicked.connect(self.open_export)
        sl.addWidget(self.btn_export)

        self.btn_settings = QPushButton("⚙️  Cài đặt")
        self.btn_settings.setObjectName("NavButton")
        self.btn_settings.clicked.connect(self.open_settings)
        sl.addWidget(self.btn_settings)

        sl.addStretch(1)

        self.sync_badge = QPushButton("☁️ Google: Tắt")
        self.sync_badge.setObjectName("Chip")
        self.sync_badge.setCursor(Qt.PointingHandCursor)
        self.sync_badge.setToolTip("Bấm để mở Cài đặt → Google")
        self.sync_badge.clicked.connect(self.open_settings)
        sl.addWidget(self.sync_badge)

        root.addWidget(side)

        # ---- vùng phải ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(18, 11, 18, 11)
        tl.setSpacing(10)

        self.search_icon = QLabel("🔎")
        self.search_icon.setObjectName("SearchIcon")
        self.search_icon.setFixedWidth(22)
        tl.addWidget(self.search_icon)

        from PySide6.QtWidgets import QLineEdit
        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText(
            "Tìm nhanh: địa chỉ, mã phòng, số căn, loại phòng, SĐT, giá...  (Ctrl+F)")
        self.search.setMinimumWidth(380)
        tl.addWidget(self.search, 1)

        self.lbl_hint = QLabel("Không dấu / không phân biệt hoa thường")
        self.lbl_hint.setObjectName("SearchHint")
        tl.addWidget(self.lbl_hint)

        self.btn_new_room = QPushButton("＋ Thêm phòng")
        self.btn_new_room.setObjectName("Primary")
        self.btn_new_room.clicked.connect(self.add_room)
        tl.addWidget(self.btn_new_room)
        rl.addWidget(top)

        # ---- trang ----
        from dashboard import DashboardPage
        from building_view import BuildingPage
        from room_view import RoomPage

        self.stack = QStackedWidget()
        self.page_dashboard = DashboardPage(self.mgr)
        self.page_buildings = BuildingPage(self.mgr)
        self.page_rooms = RoomPage(self.mgr)

        self.page_dashboard.open_rooms.connect(self._open_rooms_from_dashboard)
        self.page_dashboard.open_buildings.connect(lambda: self.navigate("buildings"))
        self.page_buildings.open_rooms.connect(self._open_rooms_from_building)
        self.page_buildings.building_selected.connect(lambda d: None)  # panel tự cập nhật bên trong BuildingPage
        self.page_buildings.open_detail.connect(self._focus_room)
        self.page_rooms.duplicate_open.connect(self._focus_room)

        self.stack.addWidget(self.page_dashboard)     # 0
        self.stack.addWidget(self.page_buildings)     # 1
        self.stack.addWidget(self.page_rooms)         # 2
        rl.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        self.setCentralWidget(central)

        # popup tìm kiếm
        self.popup = SearchPopupReal(self)
        self.popup.chosen.connect(self._focus_room)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)               # DEBOUNCE 150ms
        self._debounce.timeout.connect(self._do_search)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        self.search.returnPressed.connect(lambda: self._do_search(show_popup=False))

        # status bar
        sb = QStatusBar()
        sb.setFixedHeight(26)

        # huy hiệu môi trường - luôn hiện để không ai gõ nhầm dữ liệu prod khi đang test
        self.lbl_env = QLabel(f" {env_badge()} ")
        self.lbl_env.setFixedHeight(20)
        self.lbl_env.setAlignment(Qt.AlignCenter)
        self.lbl_env.setStyleSheet(
            f"background: {ENV_COLORS.get(APP_ENV, '#6B7280')}; color: white;"
            "font-weight: 700; font-size: 11px; border-radius: 4px; padding: 0 8px;")
        self.lbl_env.setToolTip(
            f"Môi trường hiện tại: {APP_ENV}\n"
            f"Dữ liệu: {DATA_DIR}\n\n"
            "Đổi môi trường bằng cờ --env dev|staging|prod khi khởi động.")
        sb.addPermanentWidget(self.lbl_env, 0)

        self.lbl_status = QLabel("Sẵn sàng")
        sb.addWidget(self.lbl_status, 1)
        self.lbl_counts = QLabel("")
        sb.addPermanentWidget(self.lbl_counts)
        self.setStatusBar(sb)

    def _build_shortcuts(self):
        pairs = [
            ("Ctrl+N", self.add_room),
            ("Ctrl+F", self.focus_search),
            ("Ctrl+I", self.open_import),
            ("Ctrl+E", self.open_export),
            ("Ctrl+Shift+S", self.open_settings),
            ("F5", self.refresh_all),
            ("Ctrl+1", lambda: self.navigate("dashboard")),
            ("Ctrl+2", lambda: self.navigate("buildings")),
            ("Ctrl+3", lambda: self.navigate("rooms")),
            ("Ctrl+Z", self.page_rooms._undo),
            ("Esc", self._hide_popup),
        ]
        for seq, slot in pairs:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)

    def _wire_events(self):
        # sự kiện từ manager (bắn từ UI hoặc worker) -> đưa vào queue -> poll trên UI thread
        def listener(event: str, data: Dict[str, Any]):
            self.event_queue.put({"event": event, "data": data})

        self.mgr.subscribe(listener)

    # ------------------------------------------------------------------ điều hướng
    def navigate(self, key: str):
        self._nav = key
        idx = {"dashboard": 0, "buildings": 1, "rooms": 2}.get(key, 0)
        self.stack.setCurrentIndex(idx)
        for k, b in self.nav_buttons.items():
            b.setProperty("active", "true" if k == key else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        if key == "dashboard":
            self.page_dashboard.refresh()
        elif key == "buildings":
            self.page_buildings.refresh()
        elif key == "rooms":
            self.page_rooms.set_text(self.search.text())
            self.page_rooms.refresh()

    def _open_rooms_from_dashboard(self, filt: Dict):
        self.navigate("rooms")
        self.page_rooms.set_query(text=self.search.text(), filter_dict=filt,
                                  title=filt.get("title") or "Lọc theo chỉ số")

    def _open_rooms_from_building(self, filt: Dict):
        self.navigate("rooms")
        self.page_rooms.set_query(text="", filter_dict=filt,
                                  title=f"Tòa: {filt.get('title', '')}")

    def _focus_room(self, rid: str):
        r = self.mgr.room(rid)
        if not r:
            return
        self.navigate("rooms")
        self.search.setText(r.get("room_code") or "")
        self.page_rooms.set_query(text=self.search.text(), filter_dict={"filter": RoomFilter()},
                                  title=f"Định vị: {r.get('room_code')}")
        self.page_rooms._open_detail(rid)

    # ------------------------------------------------------------------ tìm kiếm
    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _do_search(self, show_popup: bool = True):
        text = self.search.text().strip()
        if not text:
            self.popup.hide()
            if self._nav == "rooms":
                self.page_rooms.set_text("")
            return
        # nếu đang ở trang phòng -> lọc trực tiếp
        if self._nav == "rooms":
            self.page_rooms.set_text(text)
            self.popup.hide()
            return
        # còn nếu ở trang khác -> hiện popup gợi ý (nhấn Enter vào trang Phòng)
        ids = self.mgr.index.query(text, None)
        rows = self.mgr.db.get_rooms(ids[:8]) if ids else []
        if not rows:
            self.popup.hide()
            return
        self.popup.set_results(rows)
        if show_popup:
            self._show_popup()

    def _show_popup(self):
        g = self.search.mapToGlobal(QPoint(0, self.search.height() + 6))
        self.popup.move(g)
        self.popup.show()
        self.popup.raise_()

    def _hide_popup(self):
        if self.popup.isVisible():
            self.popup.hide()

    def eventFilter(self, obj, ev):
        if obj is self.popup and ev.type() == QEvent.FocusOut:
            self.popup.hide()
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------ hành động
    def add_room(self):
        from edit_form import RoomEditForm
        dlg = RoomEditForm(self.mgr, None, self)
        dlg.exec()
        self.refresh_all()

    def open_import(self):
        from import_dialog import ImportDialog
        dlg = ImportDialog(self.mgr, self)
        dlg.imported.connect(lambda *_: self.refresh_all())
        dlg.exec()

    def open_export(self):
        from export_dialog import ExportDialog
        dlg = ExportDialog(self.mgr, self)
        dlg.exec()

    def open_settings(self):
        from settings import SettingsDialog
        dlg = SettingsDialog(self.mgr.settings, self)

        def on_saved(vals: Dict[str, Any]):
            if "google_enabled" in vals and vals.get("google_enabled"):
                n = self.mgr.enqueue_all_pending()
                if self.worker:
                    self.worker.notify()
                self.lbl_status.setText(f"Đã bật Google Sheets - {n} bản ghi đưa vào hàng đợi.")
            if self.worker:
                self.worker.client.reset()
                self.worker.notify()
            self._update_sync_status()

        dlg.saved.connect(on_saved)
        dlg.exec()

    def refresh_all(self):
        self.page_dashboard.refresh()
        self.page_buildings.refresh()
        self.page_rooms.refresh()
        self.lbl_status.setText("Đã làm mới (F5)")

    # ------------------------------------------------------------------ vòng sự kiện
    def _drain_events(self):
        dirty = {"rooms_changed": False, "buildings_changed": False,
                 "stats_changed": False, "queue_changed": False}
        latest: Dict[str, Any] = {}
        try:
            while True:
                ev = self.event_queue.get_nowait()
                name = ev.get("event", "")
                if name in dirty:
                    dirty[name] = True
                    latest = ev.get("data", {}) or latest
                if name == "error":
                    self.lbl_status.setText(f"Lỗi đồng bộ: {ev.get('data', {}).get('message', '')}")
        except queue.Empty:
            pass

        if dirty["stats_changed"] or dirty["rooms_changed"]:
            if self._nav == "dashboard":
                self.page_dashboard.refresh()
            self.page_rooms.refresh()
            self._update_counts()
        if dirty["buildings_changed"]:
            self.page_buildings.refresh()
            self.page_dashboard.refresh()
        if dirty["queue_changed"] or dirty["stats_changed"]:
            self._update_sync_status()

    def _update_counts(self):
        s = self.mgr.stats()
        st = s.get("status", {})
        self.lbl_counts.setText(
            f"Σ {s.get('total', 0)} phòng · 🟢 trống {st.get('vacant', 0)} · "
            f"🟡 sắp trống {st.get('soon_vacant', 0)} · 🔴 thuê {st.get('rented', 0)} · "
            f"🏢 {s.get('buildings', 0)} tòa")

    def _update_sync_status(self):
        self._update_counts()
        if not self.worker:
            return
        st = self.worker.status()
        if not st.get("enabled"):
            self.sync_badge.setText("☁️ Google: Tắt")
            self.sync_badge.setToolTip("Chưa bật đồng bộ - bấm để vào Cài đặt")
            return
        if not st.get("ready"):
            self.sync_badge.setText("☁️ Google: Chưa cấu hình")
            self.sync_badge.setToolTip(st.get("sheets_status", ""))
            return
        pending = st.get("pending", 0)
        conflict = st.get("conflict", 0)
        state = st.get("state", "idle")
        dot = {"offline": "🔴", "syncing": "🟠", "error": "⛔",
               "locked": "🔒", "idle": "🟢"}.get(state, "⚪")
        label = f"{dot} Đồng bộ: {pending} chờ" + (f" · {conflict} đụng" if conflict else "")
        self.sync_badge.setText(label)
        self.sync_badge.setToolTip(
            f"Trạng thái: {state}\nLần cuối: {st.get('last_sync') or 'chưa có'}\n"
            f"Mạng: {'online' if st.get('online') else 'offline'}\n"
            f"Lỗi: {st.get('last_error') or 'không'}")

    # ------------------------------------------------------------------ lifecycle
    def closeEvent(self, ev):
        try:
            if self.worker:
                self.worker.stop(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(ev)
