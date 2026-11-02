# -*- coding: utf-8 -*-
"""request_dialog.py - Hộp thoại "Tìm theo yêu cầu khách".

Khách hỏi (Zalo/điện thoại): "phòng 7tr full nội thất có thang máy, gửi xe,
xung quanh P13 hay đường Bình Lợi" ->
1) dán/yêu cầu vào ô text -> parser tách giá / tiện ích / khu vực (chip hiển thị)
2) bấm Tìm -> 4 vòng kết quả: Đúng khu vực -> Lân cận (cùng quận)
   -> Giáp ranh (quận liền kề) -> Toàn kho
3) mỗi vòng có nút "Mở trên bảng phòng" (lọc đúng vòng đó).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import text_utils as tu
import theme
from models import RoomFilter, RoomStatus
from request_parser import Request, parse_request, search_tiers
from theme import status_color, status_label


def _chip(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background:{color}1A; color:{color}; border:1px solid {color}40;"
        "border-radius:11px; padding:2px 10px; font-size:11.5px; font-weight:700;")
    return lbl


class RequestDialog(QDialog):
    """Nhập yêu cầu khách -> kết quả 4 vòng mở rộng khu vực."""

    open_rooms = Signal(dict)     # {filter, title} -> mở trang Phòng

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.req: Optional[Request] = None
        self.setWindowTitle("🎯 Tìm theo yêu cầu khách")
        self.setMinimumSize(880, 640)
        self.resize(960, 720)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # ---- ô nhập yêu cầu (paste nguyên câu khách hỏi) ----
        t = QLabel("Yêu cầu của khách (gõ/y nguyên câu khách nói)")
        t.setStyleSheet(
            f"font-size:13.5px; font-weight:800; color:{theme.c('text')};"
            " background:transparent;")
        lay.addWidget(t)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(
            "VD: khách tìm phòng 7tr full nội thất có thang máy, gửi xe, "
            "xung quanh P13 hay đường Bình Lợi")
        self.ed.setClearButtonEnabled(True)
        self.ed.textChanged.connect(self._schedule_parse)
        lay.addWidget(self.ed)

        # ---- chip các tiêu chí đã tách được ----
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.chips_wrap = QWidget()
        self.chips_wrap.setStyleSheet("background:transparent;")
        self.chips_wrap.setLayout(self.chips)
        lay.addWidget(self.chips_wrap)

        # ---- nút tìm ----
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_find = QPushButton("🔎  Tìm phòng")
        self.btn_find.setObjectName("Primary")
        self.btn_find.clicked.connect(self.run_search)
        row.addWidget(self.btn_find)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Muted")
        row.addWidget(self.lbl_status, 1)
        lay.addLayout(row)

        # ---- khu vực kết quả (cuộn) ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.body.setStyleSheet("background:transparent;")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 6, 0)
        self.body_lay.setSpacing(12)
        scroll.setWidget(self.body)
        lay.addWidget(scroll, 1)

        # parse live (debounce 250ms) + tìm lần đầu
        self._deb = QTimer(self)
        self._deb.setSingleShot(True)
        self._deb.setInterval(250)
        self._deb.timeout.connect(self._parse_only)

        self._show_hint()
        QTimer.singleShot(0, self.ed.setFocus)

    # ------------------------------------------------------------------
    def _schedule_parse(self, *_):
        self._deb.start()

    def _parse_only(self):
        self.req = parse_request(self.ed.text())
        self._render_chips()

    def _render_chips(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        req = self.req
        if not req or req.is_empty():
            lbl = QLabel("Chưa nhận diện được tiêu chí nào.")
            lbl.setStyleSheet(
                f"color:{theme.c('text3')}; background:transparent; font-size:12px;")
            self.chips.addWidget(lbl)
            self.chips.addStretch(1)
            return
        if req.price_label:
            self.chips.addWidget(_chip(f"💰 {req.price_label}", theme.c("accent")))
        if req.area_label:
            self.chips.addWidget(_chip(f"📍 {req.area_label}", theme.c("info")))
        for name in req.keywords_label:
            self.chips.addWidget(_chip(f"✦ {name}", theme.c("ok")))
        for rt in req.room_types:
            self.chips.addWidget(_chip(f"🛏 {rt}", theme.c("warn")))
        if req.nearby:
            self.chips.addWidget(_chip("🧭 Ưu tiên khu vực lân cận", theme.c("orange")))
        self.chips.addStretch(1)

    def _show_hint(self):
        hint = QLabel(
            "Cách dùng: dán nguyên tin nhắn khách hỏi, ví dụ\n"
            "  “phòng 7tr full nội thất có thang máy, gửi xe, xung quanh P13 hay đường Bình Lợi”\n"
            "Phần mềm tự tách giá, tiện ích, phường/đường và tìm theo 4 vòng: "
            "đúng khu vực → lân cận cùng quận → giáp ranh → toàn kho.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{theme.c('text2')}; background:transparent; font-size:12.5px;"
            " line-height:150%;")
        self.body_lay.addWidget(hint)

    # ------------------------------------------------------------------
    def run_search(self):
        self.req = parse_request(self.ed.text())
        self._render_chips()
        # dọn kết quả cũ
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if self.req.is_empty():
            self.lbl_status.setText("Chưa nhận diện được tiêu chí nào để tìm.")
            self._show_hint()
            return

        tiers = search_tiers(self.mgr, self.req)
        real = [t for t in tiers if t.get("total")]
        total = sum(t["total"] for t in real)
        self.lbl_status.setText(
            f"Tìm thấy {total} phòng khớp yêu cầu"
            + (f" trong {len(real)} vùng." if real else " - thử bỏ bớt tiêu chí."))

        if not real:
            empty = QLabel(
                "❌ Không có phòng nào khớp toàn bộ yêu cầu.\n"
                "Thử: nới khoảng giá, bỏ bớt tiện ích, hoặc đổi khu vực khác.")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color:{theme.c('text2')}; background:{theme.c('danger_soft')};"
                " border-radius:10px; padding:14px; font-size:13px;")
            self.body_lay.addWidget(empty)
            for t in tiers:                      # gợi ý nới lỏng (nếu có)
                self.body_lay.addWidget(self._tier_card(t))
            self.body_lay.addStretch(1)
            return

        for t in tiers:
            self.body_lay.addWidget(self._tier_card(t))
        self.body_lay.addStretch(1)

    # ------------------------------------------------------------------
    def _tier_card(self, t: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(t["title"])
        title.setStyleSheet(
            f"font-size:14px; font-weight:800; color:{theme.c('text')};"
            " background:transparent;")
        head.addWidget(title)
        if t.get("total"):
            badge = QLabel(f"{t['total']} phòng")
            badge.setStyleSheet(
                f"background:{theme.c('accent_soft')}; color:{theme.c('accent_soft_text')};"
                " border-radius:10px; padding:2px 10px; font-size:11.5px; font-weight:800;")
            head.addWidget(badge)
        if t.get("hint"):
            hint = QLabel(t["hint"])
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color:{theme.c('text3')}; background:transparent; font-size:12px;")
            head.addWidget(hint, 1)
        head.addStretch(1)
        if t.get("total"):
            btn_open = QPushButton("📋 Mở trên bảng phòng")
            btn_open.setObjectName("SmallPrimary")
            btn_open.clicked.connect(lambda checked=False, tt=t: self._open_tier(tt))
            head.addWidget(btn_open)
        lay.addLayout(head)

        for r in t["rooms"][:12]:
            lay.addWidget(self._room_row(r))
        if t["total"] > 12:
            more = QLabel(f"… và {t['total'] - 12} phòng nữa (bấm “Mở trên bảng phòng”)")
            more.setStyleSheet(
                f"color:{theme.c('text3')}; background:transparent; font-size:12px;")
            lay.addWidget(more)
        return card

    def _room_row(self, r: Dict[str, Any]) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(10)
        st = r.get("status", "")
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color:{status_color(st)}; background:transparent; font-size:11px;")
        h.addWidget(dot)
        code = QLabel(r.get("room_code") or "(chưa có mã)")
        code.setStyleSheet(
            f"font-weight:800; font-size:12.5px; color:{theme.c('text')};"
            " background:transparent;")
        code.setMinimumWidth(76)
        h.addWidget(code)
        pr = r.get("price")
        price = QLabel(f"{tu.format_money(pr)}₫" if pr not in (None, "") else "Chưa biết")
        price.setStyleSheet(
            f"font-weight:800; font-size:12.5px; color:{theme.c('accent')};"
            " background:transparent;")
        price.setMinimumWidth(96)
        h.addWidget(price)
        st_lbl = QLabel(status_label(st))
        st_lbl.setStyleSheet(
            f"color:{status_color(st)}; background:transparent; font-size:12px; font-weight:600;")
        st_lbl.setMinimumWidth(110)
        h.addWidget(st_lbl)
        addr = QLabel(r.get("address") or "")
        addr.setStyleSheet(
            f"color:{theme.c('text2')}; background:transparent; font-size:12px;")
        addr.setMinimumWidth(0)
        h.addWidget(addr, 1)
        return w

    # ------------------------------------------------------------------
    def _open_tier(self, t: Dict[str, Any]):
        self.open_rooms.emit({
            "filter": t.get("filter") or RoomFilter(),
            "title": f"{t['title']} · {self.ed.text().strip()[:40]}",
        })
        self.accept()
