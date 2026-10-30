# -*- coding: utf-8 -*-
"""dashboard.py - Trang Tổng quan: 9 chỉ số KPI, biểu đồ trạng thái, lịch sử thay đổi gần nhất.

Mỗi thẻ KPI bấm vào sẽ mở trang Phòng với bộ lọc tương ứng (mục 1 - Dashboard 9 chỉ số).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import text_utils as tu
from models import RoomFilter, RoomStatus
from theme import C_ACCENT, C_TEXT2, C_MUTED, status_bg, status_color, status_label


# ------------------------------------------------------------------ thẻ chỉ số
class StatCard(QFrame):
    """1 thẻ KPI - bấm để mở trang Phòng với filter tương ứng."""

    clicked = Signal(dict)

    def __init__(self, title: str, value: Any = 0, hint: str = "", color: str = C_ACCENT,
                 icon: str = "", filt: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("clickable", bool(filt))
        self.setCursor(Qt.PointingHandCursor if filt else Qt.ArrowCursor)
        self._filt = filt or {}
        self._color = color

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 13, 16, 13)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(8)
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet(f"font-size:17px; background:transparent; color:{color};")
        lbl_title = QLabel(title)
        lbl_title.setObjectName("StatTitle")
        lbl_title.setWordWrap(True)
        top.addWidget(lbl_icon)
        top.addWidget(lbl_title, 1)
        lay.addLayout(top)

        self.lbl_value = QLabel(str(value))
        self.lbl_value.setObjectName("StatValue")
        lay.addWidget(self.lbl_value)

        self.lbl_hint = QLabel(hint)
        self.lbl_hint.setObjectName("StatHint")
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)

        self.setMinimumWidth(210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: Any, hint: Optional[str] = None, color: Optional[str] = None):
        self.lbl_value.setText(str(value))
        if hint is not None:
            self.lbl_hint.setText(hint)
        if color:
            self._color = color

    def mousePressEvent(self, ev):
        if self._filt:
            self.clicked.emit(dict(self._filt))
        super().mousePressEvent(ev)


# ------------------------------------------------------------------ biểu đồ tròn trạng thái
class StatusPie(QWidget):
    """Biểu đồ tròn phân bố trạng thái (vẽ thủ công - không cần thư viện biểu đồ)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[tuple] = []   # (label, count, color)
        self.setMinimumSize(230, 230)

    def set_data(self, counts: Dict[str, int]):
        items = []
        for key in RoomStatus.ORDER:
            c = int(counts.get(key, 0))
            if c > 0:
                items.append((status_label(key), c, status_color(key)))
        items.sort(key=lambda x: -x[1])
        self._data = items
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(18, 18, -150, -18)
        w = min(rect.width(), rect.height())
        rect.setWidth(w)
        rect.setHeight(w)
        total = sum(c for _, c, _ in self._data) or 1
        if not self._data:
            p.setPen(QColor("#CBD5E1"))
            p.drawText(rect, Qt.AlignCenter, "Chưa có dữ liệu")
            return
        start = 0.0
        for label, count, color in self._data:
            span = 360.0 * count / total
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.setBrush(QColor(color))
            p.drawPie(rect, int(start * 16), int(span * 16))
            start += span
        # chú giải
        y = 26
        p.setFont(p.font())
        for label, count, color in self._data[:8]:
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(self.rect().width() - 138, y - 9, 11, 11, 3, 3)
            p.setPen(QColor("#334155"))
            p.drawText(self.rect().width() - 122, y, f"{label[:16]}  {count}")
            y += 19


# ------------------------------------------------------------------ biểu đồ cột theo loại phòng
class TypeBars(QWidget):
    """Thanh ngang thống kê số phòng theo từng dạng phòng."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[tuple] = []
        self.setMinimumHeight(120)

    def set_data(self, by_type: Dict[str, Dict[str, int]]):
        rows = sorted(((t, d.get("total", 0), d.get("vacant", 0))
                       for t, d in by_type.items() if t != "(chưa rõ)"),
                      key=lambda x: -x[1])[:7]
        self._rows = rows
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._rows:
            p.setPen(QColor("#94A3B8"))
            p.drawText(self.rect(), Qt.AlignCenter, "Chưa có dữ liệu loại phòng")
            return
        max_v = max((t for _, t, _ in self._rows), default=1) or 1
        h = max(20, (self.height() - 6) // len(self._rows))
        label_w = 120
        bar_w = self.width() - label_w - 70
        for i, (name, total, vacant) in enumerate(self._rows):
            y = i * h + 3
            p.setPen(QColor("#475569"))
            p.drawText(4, y + h - 7, name[:16])
            p.setBrush(QColor("#E2E8F0"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(label_w, y + 4, bar_w, h - 12, 5, 5)
            w = int(bar_w * total / max_v)
            p.setBrush(QColor(C_ACCENT))
            p.drawRoundedRect(label_w, y + 4, max(6, w), h - 12, 5, 5)
            if vacant:
                wv = int(bar_w * vacant / max_v)
                p.setBrush(QColor("#16A34A"))
                p.drawRoundedRect(label_w, y + 4, max(4, wv), h - 12, 5, 5)
            p.setPen(QColor("#0F172A"))
            p.drawText(label_w + bar_w + 8, y + h - 7, f"{total} (trống {vacant})")


# ------------------------------------------------------------------ hàng lịch sử
class HistoryRow(QFrame):
    def __init__(self, rec: Dict[str, Any], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{status_color(rec.get('new_status', ''))}; font-size:13px; background:transparent;")
        lay.addWidget(dot)

        code = rec.get("room_code") or rec.get("room_id", "")[-8:]
        main = QLabel(
            f"<b>{code}</b> &nbsp; {status_label(rec.get('old_status', ''))} "
            f"<span style='color:#94A3B8'>→</span> <b>{status_label(rec.get('new_status', ''))}</b>"
        )
        main.setTextFormat(Qt.RichText)
        main.setStyleSheet("background:transparent;")
        lay.addWidget(main, 1)

        who = QLabel(f"{rec.get('actor', '')} · {rec.get('changed_at', '')}")
        who.setObjectName("Muted")
        who.setStyleSheet("background:transparent; font-size:11.5px;")
        lay.addWidget(who)


# ------------------------------------------------------------------ trang tổng quan
class DashboardPage(QWidget):
    """Dashboard 9 chỉ số + biểu đồ + lịch sử thay đổi."""

    open_rooms = Signal(dict)       # {filter: RoomFilter..., text: str}
    open_buildings = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self._cards: Dict[str, StatCard] = {}
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("Tổng quan kho phòng")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_updated = QLabel("")
        self.lbl_updated.setObjectName("Muted")
        head.addWidget(self.lbl_updated)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(14)

        # ---- lưới 9 thẻ KPI ----
        grid = QGridLayout()
        grid.setSpacing(12)
        specs = [
            ("total",       "Tổng số phòng",       "📊", C_ACCENT, {"text": ""}),
            ("vacant",      "Trống ở ngay",         "✅", "#16A34A", {"statuses": ["vacant"]}),
            ("soon_vacant", "Sắp trống",            "⏳", "#EAB308", {"statuses": ["soon_vacant"]}),
            ("rented",      "Đã cho thuê",          "🏠", "#DC2626", {"statuses": ["rented"]}),
            ("deposit",     "Đã nhận cọc / giữ chỗ", "💰", "#F97316", {"statuses": ["deposit", "holding"]}),
            ("surveyed",    "Đã khảo sát (có ảnh)", "📸", "#0D9488", {"surveyed": True}),
            ("ev",          "Hỗ trợ xe điện ⚡",     "⚡", "#2563EB", {"ev_support": True}),
            ("pet",         "Cho nuôi pet 🐾",       "🐾", "#7C3AED", {"pet_allowed": True}),
            ("buildings",   "Tòa nhà / địa điểm",   "🏢", "#0EA5E9", {"__buildings__": True}),
        ]
        for i, (key, title_, icon, color, filt) in enumerate(specs):
            hint = {
                "total": "Tất cả căn hộ đang quản lý",
                "vacant": "Ưu tiên chốt khách ngay",
                "soon_vacant": "Chào khách nhận tháng tới",
                "rented": "Đang khai thác",
                "deposit": "Chờ khách nhận nhà",
                "surveyed": "Sẵn sàng gửi media",
                "ev": "Khách đi xe điện",
                "pet": "Khách nuôi chó/mèo",
                "buildings": "Số địa điểm trong danh mục",
            }[key]
            card = StatCard(title_, 0, hint, color, icon, filt)
            card.clicked.connect(self._on_card_clicked)
            self._cards[key] = card
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)

        # ---- biểu đồ ----
        charts = QHBoxLayout()
        charts.setSpacing(12)

        pie_card = QFrame()
        pie_card.setObjectName("Card")
        pl = QVBoxLayout(pie_card)
        pl.setContentsMargins(16, 14, 16, 14)
        t1 = QLabel("Phân bố trạng thái phòng")
        t1.setObjectName("SectionTitle")
        pl.addWidget(t1)
        self.pie = StatusPie()
        pl.addWidget(self.pie, 1)
        pie_card.setMinimumWidth(360)
        charts.addWidget(pie_card, 1)

        bar_card = QFrame()
        bar_card.setObjectName("Card")
        bl = QVBoxLayout(bar_card)
        bl.setContentsMargins(16, 14, 16, 14)
        t2 = QLabel("Số phòng theo dạng phòng")
        t2.setObjectName("SectionTitle")
        bl.addWidget(t2)
        t2h = QLabel("Thanh xanh đậm = tổng số · thanh xanh lá = đang trống")
        t2h.setObjectName("Muted")
        t2h.setStyleSheet("font-size:11.5px;")
        bl.addWidget(t2h)
        self.bars = TypeBars()
        bl.addWidget(self.bars, 1)
        charts.addWidget(bar_card, 1)
        lay.addLayout(charts)

        # ---- trạng thái đồng bộ + lịch sử ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        sync_card = QFrame()
        sync_card.setObjectName("Card")
        sl = QVBoxLayout(sync_card)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(8)
        t3 = QLabel("Đồng bộ dữ liệu")
        t3.setObjectName("SectionTitle")
        sl.addWidget(t3)
        self.lbl_sync = QLabel("—")
        self.lbl_sync.setWordWrap(True)
        self.lbl_sync.setStyleSheet("background:transparent;")
        sl.addWidget(self.lbl_sync)
        self.lbl_queue = QLabel("—")
        self.lbl_queue.setWordWrap(True)
        self.lbl_queue.setStyleSheet("background:transparent;")
        sl.addWidget(self.lbl_queue)
        btn_row = QHBoxLayout()
        self.btn_building = QLabel("<a href='#'>Xem danh mục tòa nhà →</a>")
        self.btn_building.setOpenExternalLinks(False)
        self.btn_building.linkActivated.connect(lambda *_: self.open_buildings.emit())
        btn_row.addWidget(self.btn_building)
        btn_row.addStretch(1)
        sl.addLayout(btn_row)
        sl.addStretch(1)
        sync_card.setMinimumWidth(330)
        bottom.addWidget(sync_card, 1)

        hist_card = QFrame()
        hist_card.setObjectName("Card")
        hl = QVBoxLayout(hist_card)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(4)
        t4 = QLabel("Lịch sử thay đổi gần nhất")
        t4.setObjectName("SectionTitle")
        hl.addWidget(t4)
        self.hist_box = QVBoxLayout()
        self.hist_box.setSpacing(2)
        hl.addLayout(self.hist_box, 1)
        bottom.addWidget(hist_card, 2)
        lay.addLayout(bottom)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    # ------------------------------------------------------------------ cập nhật
    def _on_card_clicked(self, filt: Dict):
        if filt.pop("__buildings__", None):
            self.open_buildings.emit()
            return
        self.open_rooms.emit(filt)

    def refresh(self):
        s = self.mgr.stats()

        def st(key):
            return int(s.get("status", {}).get(key, 0))

        vals = {
            "total": s.get("total", 0),
            "vacant": st("vacant"),
            "soon_vacant": st("soon_vacant"),
            "rented": st("rented"),
            "deposit": st("deposit") + st("holding"),
            "surveyed": s.get("surveyed", 0),
            "ev": s.get("ev", 0),
            "pet": s.get("pet", 0),
            "buildings": s.get("buildings", 0),
        }
        total = max(1, int(vals["total"]))
        for k, v in vals.items():
            card = self._cards[k]
            if k in ("total", "buildings"):
                card.set_value(v)
            else:
                pct = 100.0 * v / total
                card.set_value(v, f"{pct:.0f}% tổng số phòng")

        self.pie.set_data(s.get("status", {}))
        self.bars.set_data(s.get("by_type", {}))

        queue = s.get("queue", {}) or {}
        pending = int(queue.get("pending", 0) or 0)
        conflict = int(queue.get("conflict", 0) or 0)
        google_on = bool(self.mgr.settings.get("google_enabled"))
        if not google_on:
            self.lbl_sync.setText(
                "<b>Chế độ ngoại tuyến (Offline-first)</b><br>"
                "Dữ liệu lưu an toàn trong SQLite. Bật đồng bộ Google trong "
                "<b>Cài đặt → Google</b> để kéo/đẩy dữ liệu lên Google Sheets."
            )
        else:
            self.lbl_sync.setText(
                "<b>Đồng bộ Google Sheets: đang bật</b><br>"
                f"Lệnh chờ: <b>{pending}</b> · Xung đột: <b>{conflict}</b>"
            )
        self.lbl_queue.setText(
            f"Hàng đợi chờ đồng bộ: {pending} lệnh"
            + (f" · {conflict} xung đột cần xác nhận" if conflict else "")
        )

        self.lbl_updated.setText(f"Cập nhật: {tu.now_str() if hasattr(tu, 'now_str') else ''}"
                                 f"{_now()}")

        # lịch sử gần nhất
        while self.hist_box.count():
            item = self.hist_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        recs = self.mgr.recent_changes(8)
        if not recs:
            empty = QLabel("Chưa có thay đổi nào được ghi lại.")
            empty.setObjectName("Muted")
            empty.setStyleSheet("background:transparent;")
            self.hist_box.addWidget(empty)
        for rec in recs:
            self.hist_box.addWidget(HistoryRow(rec))
        self.hist_box.addStretch(1)


def _now() -> str:
    from config import now_iso
    return now_iso()
