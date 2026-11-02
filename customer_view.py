# -*- coding: utf-8 -*-
"""customer_view.py - Trang Khách hàng (CRM): pipeline sale + phân tích điểm sai khi sale.

Trả lời câu hỏi "mình SAI ĐIỂM NÀO khi sale khách hàng":
- Bảng khách tiềm pipeline phân cụm theo trạng thái (Mới -> Liên hệ -> Tư vấn ->
  Hẹn xem -> Cọc -> Chốt) với tìm kiếm không dấu + lọc theo trạng thái/nguồn.
- Panel chi tiết: đổi trạng thái (MẤT KHÁCH bắt chọn lý do), gọi/Zalo, ghi tương
  tác (call/zalo/view/note) + lịch sử đầy đủ.
- Tab Phân tích: FUNNEL (khách rơi ở khâu nào), TOP LÝ DO MẤT KHÁCH
  (= điểm mình sai khi sale), nguồn khách, tỷ lệ chốt, thời gian trung bình chốt.

Dữ liệu: SQLite cục bộ qua customer_manager.CustomerManager (offline-first).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListView, QPlainTextEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QStyledItemDelegate, QTableView, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

import theme
from customer_manager import CustomerManager
from dashboard import StatCard
from google_drive import open_phone, open_zalo
from grouped_table import GroupedTableModel, group_row_size_hint, paint_group_row
from models import CUSTOMER_SOURCES, CustomerStatus, LOSE_REASONS, lose_reason_label
from theme import C_ACCENT, C_DANGER, C_OK, C_MUTED

# icon pipeline cho tiêu đề nhóm trong bảng
_STAGE_ICON = {
    "new": "🆕", "contacting": "📞", "consulting": "💬", "viewing": "👁️",
    "deposit": "💵", "won": "✅", "paused": "⏸️", "lost": "❌",
}
_EVENT_ICON = {"call": "📞", "zalo": "💬", "view": "👁️", "note": "📝", "status": "🔄"}


# ------------------------------------------------------------------ helper hiển thị
def _money_short(v) -> str:
    """5000000 -> '5tr' (ngắn cho bảng)."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}tr"
    return f"{int(n):,}".replace(",", ".")


def budget_text(c: Dict[str, Any]) -> str:
    lo, hi = c.get("budget_min"), c.get("budget_max")
    if lo and hi:
        return f"{_money_short(lo)} - {_money_short(hi)}"
    if hi:
        return f"≤ {_money_short(hi)}"
    if lo:
        return f"≥ {_money_short(lo)}"
    return "—"


def _fmt_ts(ts: str) -> str:
    return str(ts or "").replace("T", " ")[:16] or "—"


# ------------------------------------------------------------------ thanh dữ liệu (vẽ tay)
class BarList(QWidget):
    """Danh sách thanh ngang: nhãn | thanh | giá trị (+ % nếu có tổng).

    Dùng cho funnel, lý do mất khách, nguồn, hoạt động (không cần thư viện biểu đồ).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[Tuple[str, int, str]] = []
        self._total = 0
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_data(self, rows: List[tuple], total: int = 0):
        """rows: [(nhãn, giá trị, màu)] - tự sắp xếp giảm dần theo giá trị."""
        clean = [(str(lb), int(v), str(col)) for lb, v, col in rows if int(v) > 0]
        clean.sort(key=lambda x: -x[1])
        self._rows = clean
        self._total = int(total or 0)
        self.setMinimumHeight(max(72, 26 * len(clean) + 10))
        self.update()

    def row_count(self) -> int:
        return len(self._rows)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._rows:
            p.setPen(QColor(theme.c("text3")))
            p.drawText(self.rect(), Qt.AlignCenter, "Chưa có dữ liệu")
            return
        max_v = max(v for _, v, _ in self._rows) or 1
        n = len(self._rows)
        h = max(22, (self.height() - 6) // n)
        label_w = min(240, max(130, self.width() // 3))
        value_w = 78
        bar_max = max(40.0, self.width() - label_w - value_w - 14)
        font = QFont(p.font())
        font.setPixelSize(11)
        p.setFont(font)
        for i, (label, value, color) in enumerate(self._rows):
            y = 3 + i * h
            # nhãn (cắt bớt nếu quá dài)
            p.setPen(QColor(theme.c("text2")))
            p.drawText(QRectF(0, y, label_w - 8, h),
                       int(Qt.AlignRight | Qt.AlignVCenter), label[:34])
            # nền thanh
            track = QRectF(label_w, y + h * 0.26, bar_max, h * 0.48)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.c("track")))
            p.drawRoundedRect(track, 4, 4)
            # giá trị
            w = bar_max * value / max_v
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(label_w, y + h * 0.26, max(6.0, w), h * 0.48), 4, 4)
            # số + %
            txt = str(value)
            if self._total:
                txt += f"  ({round(value * 100 / self._total)}%)"
            p.setPen(QColor(theme.c("text")))
            p.drawText(QRectF(label_w + bar_max + 6, y, value_w, h),
                       int(Qt.AlignRight | Qt.AlignVCenter), txt)


# ------------------------------------------------------------------ form khách hàng
class CustomerForm(QDialog):
    """Thêm/sửa khách hàng tiềm: liên hệ / nhu cầu / bán hàng (cuộn được)."""

    def __init__(self, customer: Optional[Dict[str, Any]] = None,
                 prefill: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sửa khách hàng" if customer else "Thêm khách hàng tiềm năng")
        self.setMinimumWidth(640)
        self.setMinimumHeight(520)
        self.customer = customer or {}
        prefill = dict(prefill or {})
        self.fields: Dict[str, QWidget] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 4, 0)
        inner.setSpacing(12)

        def val(key: str, default=None):
            """Ưu tiên dữ liệu khách đang sửa, sau đó prefill."""
            v = self.customer.get(key)
            if v in (None, ""):
                v = prefill.get(key, default)
            return v

        def group(num: str, title: str) -> QVBoxLayout:
            box = QFrame()
            box.setObjectName("Card")
            gl = QVBoxLayout(box)
            gl.setContentsMargins(16, 12, 16, 14)
            gl.setSpacing(9)
            head = QHBoxLayout()
            head.setSpacing(9)
            badge = QLabel(num)
            badge.setFixedSize(24, 24)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background:{theme.c('accent_soft')}; color:{theme.c('accent_soft_text')};"
                " border-radius:12px; font-size:12px; font-weight:800;")
            head.addWidget(badge)
            t = QLabel(title)
            t.setStyleSheet(
                f"font-size:14px; font-weight:800; color:{theme.c('text')};"
                " background:transparent; letter-spacing:-0.2px;")
            head.addWidget(t)
            head.addStretch(1)
            gl.addLayout(head)
            inner.addWidget(box)
            return gl

        def line(gl: QVBoxLayout, key: str, label: str, placeholder: str = "",
                 default: Any = None) -> QLineEdit:
            ed = QLineEdit(str(val(key, default) or ""))
            ed.setPlaceholderText(placeholder or label)
            self.fields[key] = ed
            row = QHBoxLayout()
            row.setSpacing(10)
            lb = QLabel(label)
            lb.setFixedWidth(118)
            lb.setStyleSheet(
                f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
                " background:transparent;")
            row.addWidget(lb)
            row.addWidget(ed, 1)
            gl.addLayout(row)
            return ed

        # ---- 1. liên hệ ----
        g1 = group("1", "Liên hệ khách hàng")
        line(g1, "name", "Tên khách", "VD: Nguyễn Văn A")
        line(g1, "phone", "Số điện thoại", "09xx xxx xxx")
        line(g1, "zalo", "Zalo", "SĐT Zalo hoặc link zalo.me/...")
        self.cmb_source = QComboBox()
        for s in CUSTOMER_SOURCES:
            self.cmb_source.addItem(s)
        cur_src = str(val("source", "") or "")
        if cur_src and self.cmb_source.findText(cur_src) < 0:
            self.cmb_source.addItem(cur_src)
        if cur_src:
            self.cmb_source.setCurrentText(cur_src)
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel("Nguồn khách")
        lb.setFixedWidth(118)
        lb.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        row.addWidget(lb)
        row.addWidget(self.cmb_source, 1)
        g1.addLayout(row)

        # ---- 2. nhu cầu ----
        g2 = group("2", "Nhu cầu của khách")
        line(g2, "area", "Khu vực quan tâm", "VD: P.13, Bình Thạnh, gần Bình Lợi")
        line(g2, "room_type", "Loại phòng", "VD: Studio, 1PN, 2PN")
        line(g2, "budget_min", "Ngân sách từ", "VD: 5000000")
        line(g2, "budget_max", "Ngân sách đến", "VD: 7000000")
        ed_req = QPlainTextEdit(str(val("requirement", "") or ""))
        ed_req.setPlaceholderText("Yêu cầu gốc của khách (dán nguyên tin nhắn)")
        ed_req.setFixedHeight(56)
        self.fields["requirement"] = ed_req
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel("Yêu cầu gốc")
        lb.setFixedWidth(118)
        lb.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        row.addWidget(lb)
        row.addWidget(ed_req, 1)
        g2.addLayout(row)

        # ---- 3. bán hàng ----
        g3 = group("3", "Bán hàng & theo dõi")
        self.cmb_status = QComboBox()
        for k in CustomerStatus.ORDER:
            self.cmb_status.addItem(CustomerStatus.label(k), k)
        cur_st = CustomerStatus.from_text(self.customer.get("status")) if self.customer else "new"
        self.cmb_status.setCurrentIndex(max(0, self.cmb_status.findData(cur_st)))
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel("Trạng thái")
        lb.setFixedWidth(118)
        lb.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        row.addWidget(lb)
        row.addWidget(self.cmb_status, 1)
        g3.addLayout(row)

        self.spin_rating = QSpinBox()
        self.spin_rating.setRange(0, 5)
        self.spin_rating.setValue(int(val("rating", 0) or 0))
        self.spin_rating.setToolTip("Mức tiềm năng: 0 = chưa đánh giá, 5 = khách rất nóng")
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel("Tiềm năng (sao)")
        lb.setFixedWidth(118)
        lb.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        row.addWidget(lb)
        row.addWidget(self.spin_rating, 1)
        row.addStretch(1)
        g3.addLayout(row)

        line(g3, "next_action", "Việc cần làm tiếp", "VD: Hẹn xem phòng 14h thứ 7")
        line(g3, "follow_up", "Nhắc lịch", "YYYY-MM-DD · để trống = chưa hẹn")
        ed_notes = QPlainTextEdit(str(val("notes", "") or ""))
        ed_notes.setPlaceholderText("Ghi chú về khách (tính cách, hoàn cảnh, thương lượng...)")
        ed_notes.setFixedHeight(56)
        self.fields["notes"] = ed_notes
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel("Ghi chú")
        lb.setFixedWidth(118)
        lb.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        row.addWidget(lb)
        row.addWidget(ed_notes, 1)
        g3.addLayout(row)

        inner.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def payload(self) -> Dict[str, Any]:
        return {
            "name": self.fields["name"].text().strip(),
            "phone": self.fields["phone"].text().strip(),
            "zalo": self.fields["zalo"].text().strip(),
            "source": self.cmb_source.currentText(),
            "area": self.fields["area"].text().strip(),
            "room_type": self.fields["room_type"].text().strip(),
            "budget_min": self.fields["budget_min"].text().strip(),
            "budget_max": self.fields["budget_max"].text().strip(),
            "requirement": self.fields["requirement"].toPlainText().strip(),
            "status": self.cmb_status.currentData(),
            "rating": self.spin_rating.value(),
            "next_action": self.fields["next_action"].text().strip(),
            "follow_up": self.fields["follow_up"].text().strip(),
            "notes": self.fields["notes"].toPlainText().strip(),
        }


# ------------------------------------------------------------------ hộp thoại lý do mất
class LoseReasonDialog(QDialog):
    """Chọn lý do MẤT khách = 'điểm mình sai khi sale' (bắt buộc khi về lost)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mất khách - mình sai điểm nào?")
        self.setMinimumWidth(460)
        self.reason = "other"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        hint = QLabel(
            "Chọn lý do khách KHÔNG thuê (dữ liệu cho tab Phân tích - "
            "biết được mình sai điểm nào khi sale):")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size:13px; color:{theme.c('text2')}; background:transparent;")
        lay.addWidget(hint)

        self.cmb = QComboBox()
        for k, lab in LOSE_REASONS:
            self.cmb.addItem(lab, k)
        lay.addWidget(self.cmb)

        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("Ghi chú thêm (không bắt buộc)")
        lay.addWidget(self.ed_note)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _ok(self):
        self.reason = self.cmb.currentData() or "other"
        self.accept()


# ------------------------------------------------------------------ bảng khách
class CustomerTableModel(GroupedTableModel):
    """Bảng khách hàng ảo hoá, phân cụm theo TRẠNG THÁI pipeline."""

    COLS = [
        ("name",        "Tên khách",     170),   # cột co giãn
        ("phone",       "SĐT",           108),
        ("status",      "Trạng thái",    108),
        ("source",      "Nguồn",         88),
        ("rating",      "Tiềm năng",     74),
        ("area",        "Khu vực",       120),
        ("budget",      "Ngân sách",     104),
        ("next_action", "Việc tiếp theo", 150),
        ("follow_up",   "Nhắc lịch",     92),
    ]

    def columns(self):
        return self.COLS

    def right_align_keys(self):
        return {"budget"}

    def center_align_keys(self):
        return {"status", "source", "rating", "follow_up"}

    def group_key_of(self, row):
        return row.get("status") or "new"

    def group_sort_key(self, key):
        order = CustomerStatus.ORDER
        return order.index(key) if key in order else len(order)

    def group_title_of(self, key, rows):
        return f"{_STAGE_ICON.get(key, '•')} {CustomerStatus.label(key)}"

    def group_meta_of(self, key, rows):
        n = len(rows)
        won = sum(1 for r in rows if r.get("status") == "won")
        txt = f"{n} khách"
        if won:
            txt += f" · {won} đã chốt"
        return txt

    def cell_flags(self, col_key):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def cell_data(self, c, key, role):
        if role == Qt.TextAlignmentRole:
            if key in self.right_align_keys():
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if key in self.center_align_keys():
                return int(Qt.AlignHCenter | Qt.AlignVCenter)
            return None
        if role == Qt.ForegroundRole:
            if key == "status":
                return QColor(CustomerStatus.color(c.get("status") or "new"))
            if key == "rating" and int(c.get("rating") or 0) > 0:
                return QColor(theme.c("warn"))
            if key == "follow_up":
                fu = str(c.get("follow_up") or "")
                import datetime as _dt
                if (fu and c.get("status") in CustomerStatus.ACTIVE
                        and fu < _dt.date.today().isoformat()):
                    return QColor(C_DANGER)      # quá hạn nhắc lịch
            return None
        if role == Qt.ToolTipRole:
            return (f"👤 {c.get('name') or '(chưa rõ tên)'} · 📞 {c.get('phone') or '—'}\n"
                    f"Nguồn: {c.get('source') or '—'} · Khu vực: {c.get('area') or '—'}\n"
                    f"Yêu cầu: {c.get('requirement') or '—'}\n"
                    f"Việc tiếp: {c.get('next_action') or '—'}\n"
                    "Double-click để sửa khách")
        if role != Qt.DisplayRole:
            return None
        if key == "status":
            return CustomerStatus.label(c.get("status") or "new")
        if key == "budget":
            return budget_text(c)
        if key == "rating":
            n = int(c.get("rating") or 0)
            return ("⭐" * n + "☆" * (5 - n)) if n else "—"
        if key == "follow_up":
            return c.get("follow_up") or "—"
        if key == "phone":
            return c.get("phone") or "—"
        v = c.get(key, "")
        return str(v) if v not in (None, "") else ""


class CustomerDelegate(QStyledItemDelegate):
    """Delegate vẽ hàng nhóm pipeline (mượn pattern của BuildingDelegate)."""

    def paint(self, painter, option, index):
        if paint_group_row(painter, option, index):
            return
        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        gh = group_row_size_hint(option, index)
        if gh is not None:
            return gh
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 40))
        return s


# ------------------------------------------------------------------ panel chi tiết
class CustomerDetailPanel(QFrame):
    """Chi tiết 1 khách: đổi trạng thái, gọi/Zalo, ghi tương tác, lịch sử."""

    changed = Signal()              # có thay đổi -> page refresh
    edit_requested = Signal(str)    # customer_id -> mở form sửa

    def __init__(self, cm: CustomerManager, parent=None):
        super().__init__(parent)
        self.cm = cm
        self.customer: Optional[Dict[str, Any]] = None
        self.setObjectName("Card")
        self.setMinimumWidth(320)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # ---------- trạng thái rỗng ----------
        self.empty = QLabel("Chọn một khách hàng trong bảng\nđể xem chi tiết & ghi tương tác.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(
            f"font-size:13px; color:{theme.c('text3')}; background:transparent;")
        lay.addWidget(self.empty, 1)

        # ---------- nội dung ----------
        self.box = QWidget()
        self.box.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(self.box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        lay.addWidget(self.box, 1)

        # header: avatar + tên + SĐT + nút sửa/xóa
        head = QHBoxLayout()
        head.setSpacing(10)
        self.avatar = QLabel("?")
        self.avatar.setFixedSize(40, 40)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            f"background:{theme.c('accent')}; color:white; border-radius:20px;"
            " font-size:14px; font-weight:800;")
        head.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.lbl_title = QLabel("—")
        self.lbl_title.setStyleSheet(
            f"font-size:15px; font-weight:800; color:{theme.c('text')};"
            " background:transparent; letter-spacing:-0.2px;")
        self.lbl_title.setWordWrap(True)
        col.addWidget(self.lbl_title)
        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet(
            f"font-size:12px; color:{theme.c('text2')}; background:transparent;")
        self.lbl_sub.setWordWrap(True)
        col.addWidget(self.lbl_sub)
        head.addLayout(col, 1)
        self.btn_edit = QToolButton()
        self.btn_edit.setText("✏️")
        self.btn_edit.setObjectName("IconButton")
        self.btn_edit.setToolTip("Sửa thông tin khách")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(
            lambda: self.edit_requested.emit((self.customer or {}).get("id", "")))
        head.addWidget(self.btn_edit)
        self.btn_del = QToolButton()
        self.btn_del.setText("🗑")
        self.btn_del.setObjectName("IconButton")
        self.btn_del.setToolTip("Xóa khách (chuyển thùng rác)")
        self.btn_del.setCursor(Qt.PointingHandCursor)
        self.btn_del.clicked.connect(self._delete)
        head.addWidget(self.btn_del)
        bl.addLayout(head)

        # trạng thái pipeline: đổi trực tiếp trên combo
        st_row = QHBoxLayout()
        st_row.setSpacing(8)
        lb = QLabel("Trạng thái")
        lb.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent;")
        st_row.addWidget(lb)
        self.cmb_status = QComboBox()
        for k in CustomerStatus.ORDER:
            self.cmb_status.addItem(f"{_STAGE_ICON.get(k, '')} {CustomerStatus.label(k)}", k)
        self.cmb_status.currentIndexChanged.connect(self._status_changed)
        st_row.addWidget(self.cmb_status, 1)
        bl.addLayout(st_row)

        # gọi / zalo
        act = QHBoxLayout()
        act.setSpacing(8)
        self.btn_call = QPushButton("📞  Gọi")
        self.btn_call.clicked.connect(self._call)
        act.addWidget(self.btn_call)
        self.btn_zalo = QPushButton("💬  Zalo")
        self.btn_zalo.clicked.connect(self._zalo)
        act.addWidget(self.btn_zalo)
        bl.addLayout(act)

        # ghi tương tác nhanh
        log_row = QHBoxLayout()
        log_row.setSpacing(6)
        for text, tip, ev, lbl in (
            ("📞 Đã gọi", "Ghi nhận đã gọi cho khách", "call", "Đã gọi"),
            ("💬 Đã nhắn", "Ghi nhận đã nhắn Zalo", "zalo", "Đã nhắn Zalo"),
            ("👁 Đã xem", "Ghi nhận khách đã xem phòng", "view", "Đã xem phòng"),
            ("📝 Ghi chú", "Thêm ghi chú tương tác", "note", ""),
        ):
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, e=ev, l=lbl: self._log(e, l))
            log_row.addWidget(b)
        log_row.addStretch(1)
        bl.addLayout(log_row)

        # thông tin đọc nhanh
        self.info = QFormLayout()
        self.info.setHorizontalSpacing(10)
        self.info.setVerticalSpacing(6)
        self._vals: Dict[str, QLabel] = {}
        for key, label in (
            ("source", "Nguồn"), ("area", "Khu vực"), ("room_type", "Loại phòng"),
            ("budget", "Ngân sách"), ("requirement", "Yêu cầu"),
            ("next_action", "Việc tiếp theo"), ("follow_up", "Nhắc lịch"),
            ("rating", "Tiềm năng"), ("notes", "Ghi chú"),
        ):
            lb = QLabel(label)
            lb.setStyleSheet(
                f"font-size:11.5px; font-weight:700; color:{theme.c('text3')};"
                " background:transparent;")
            v = QLabel("—")
            v.setWordWrap(True)
            v.setStyleSheet(
                f"font-size:12.5px; color:{theme.c('text')}; background:transparent;")
            self._vals[key] = v
            self.info.addRow(lb, v)
        bl.addLayout(self.info)

        # lịch sử tương tác
        hl = QLabel("LỊCH SỬ TƯƠNG TÁC")
        hl.setStyleSheet(
            f"font-size:11px; font-weight:800; color:{theme.c('text3')};"
            " background:transparent; letter-spacing:0.6px;")
        bl.addWidget(hl)
        self.events_model = QStandardItemModel()
        self.events_list = QListView()
        self.events_list.setObjectName("EventList")
        self.events_list.setModel(self.events_model)
        self.events_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.events_list.setFixedHeight(150)
        bl.addWidget(self.events_list)

        self.box.hide()

    # ------------------------------------------------------------------
    def set_customer(self, c: Optional[Dict[str, Any]]):
        self.customer = c
        if not c:
            self.box.hide()
            self.empty.show()
            return
        self.empty.hide()
        self.box.show()

        name = str(c.get("name") or "").strip() or "(chưa rõ tên)"
        self.lbl_title.setText(name)
        parts = [p for p in (str(c.get("phone") or "").strip(),
                             str(c.get("zalo") or "").strip()) if p]
        parts.append(f"Nguồn: {c.get('source') or '—'}")
        self.lbl_sub.setText("  ·  ".join(parts))
        initials = "".join(w[0] for w in name.split()[:2]).upper() or "?"
        self.avatar.setText(initials)

        self._sync_status_combo()
        st = c.get("status") or "new"
        self.avatar.setStyleSheet(
            f"background:{CustomerStatus.color(st)}; color:white; border-radius:20px;"
            " font-size:14px; font-weight:800;")

        self._vals["source"].setText(str(c.get("source") or "—"))
        self._vals["area"].setText(str(c.get("area") or "—"))
        self._vals["room_type"].setText(str(c.get("room_type") or "—"))
        self._vals["budget"].setText(budget_text(c))
        self._vals["requirement"].setText(str(c.get("requirement") or "—"))
        self._vals["next_action"].setText(str(c.get("next_action") or "—"))
        fu = str(c.get("follow_up") or "")
        import datetime as _dt
        overdue = (bool(fu) and st in CustomerStatus.ACTIVE
                   and fu < _dt.date.today().isoformat())
        self._vals["follow_up"].setText(
            (fu + "  ⚠️ quá hạn" if overdue else fu) or "—")
        self._vals["follow_up"].setStyleSheet(
            f"font-size:12.5px; background:transparent; color:"
            f"{C_DANGER if overdue else theme.c('text')};")
        n = int(c.get("rating") or 0)
        self._vals["rating"].setText(("⭐" * n + "☆" * (5 - n)) if n else "—")
        self._vals["notes"].setText(str(c.get("notes") or "—"))

        self._load_events()

    def _sync_status_combo(self):
        cur = (self.customer or {}).get("status", "new")
        self.cmb_status.blockSignals(True)
        i = self.cmb_status.findData(cur)
        self.cmb_status.setCurrentIndex(max(0, i))
        self.cmb_status.blockSignals(False)

    def _load_events(self):
        self.events_model.clear()
        cid = (self.customer or {}).get("id", "")
        for e in (self.cm.events(cid) if cid else []):
            icon = _EVENT_ICON.get(e.get("event"), "•")
            detail = str(e.get("detail") or "").strip() or e.get("event")
            item = QStandardItem(f"{icon}  {detail}\n     {_fmt_ts(e.get('created_at'))}")
            item.setEditable(False)
            item.setForeground(QColor(theme.c("text2")))
            self.events_model.appendRow(item)

    # ------------------------------------------------------------------ trạng thái
    def apply_status(self, new_status: str, lose_reason: str = "",
                     note: str = "") -> bool:
        """Chuyển trạng thái pipeline; mất khách -> bắt buộc chọn lý do (nếu chưa có)."""
        c = self.customer
        if not c:
            return False
        new_status = CustomerStatus.from_text(new_status)
        if new_status == (c.get("status") or "new") and not note:
            self._sync_status_combo()
            return False
        if new_status == "lost" and not lose_reason:
            dlg = LoseReasonDialog(self)
            if dlg.exec() != QDialog.Accepted:
                self._sync_status_combo()      # hủy -> đưa combo về như cũ
                return False
            lose_reason = dlg.reason
        self.cm.change_status(c["id"], new_status, lose_reason=lose_reason, note=note)
        self.changed.emit()
        self.set_customer(self.cm.customer(c["id"]))
        return True

    def _status_changed(self, *_):
        if not self.customer:
            return
        key = self.cmb_status.currentData()
        if key and key != (self.customer.get("status") or "new"):
            self.apply_status(key)

    # ------------------------------------------------------------------ gọi / zalo / log
    def _call(self):
        c = self.customer or {}
        phone = str(c.get("phone") or "")
        if not phone or not open_phone(phone):
            QMessageBox.information(self, "Chưa có SĐT",
                                    "Khách chưa có số điện thoại để gọi.")
            return
        self._log("call", "Đã gọi", auto=True)

    def _zalo(self):
        c = self.customer or {}
        link = str(c.get("zalo") or "").strip()
        if not link.startswith("http"):
            ph = "".join(ch for ch in str(c.get("phone") or "") if ch.isdigit())
            link = f"https://zalo.me/{ph}" if ph else ""
        if not link or not open_zalo(link):
            QMessageBox.information(self, "Chưa có Zalo",
                                    "Khách chưa có SĐT/Zalo để mở Zalo.")
            return
        self._log("zalo", "Đã nhắn Zalo", auto=True)

    def _log(self, event: str, label: str, auto: bool = False):
        c = self.customer
        if not c:
            return
        detail = label
        if event == "note" and not auto:
            text, ok = QInputDialog.getMultiLineText(
                self, "Ghi chú tương tác", "Nội dung ghi chú:", "")
            if not ok or not text.strip():
                return
            detail = text.strip()
        self.cm.log_event(c["id"], event, detail)
        self.changed.emit()
        self.set_customer(self.cm.customer(c["id"]))

    def _delete(self):
        c = self.customer
        if not c:
            return
        name = c.get("name") or c.get("phone") or "khách này"
        if QMessageBox.question(
                self, "Xóa khách", f"Xóa «{name}» khỏi danh sách?") != QMessageBox.Yes:
            return
        self.cm.delete_customer(c["id"])
        self.customer = None
        self.changed.emit()
        self.set_customer(None)


# ------------------------------------------------------------------ tab phân tích
class AnalyticsPanel(QWidget):
    """Phân tích sale: funnel rơi ở khâu nào + điểm sai khi sale + nguồn + chốt."""

    def __init__(self, cm: CustomerManager, parent=None):
        super().__init__(parent)
        self.cm = cm

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        v = QVBoxLayout(body)
        v.setContentsMargins(2, 2, 6, 10)
        v.setSpacing(12)

        # ---- KPI ----
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.kpi: Dict[str, StatCard] = {}
        for i, (key, title, icon, color) in enumerate((
            ("total", "Tổng khách", "👥", C_ACCENT),
            ("active", "Đang xử lý", "🔄", C_ACCENT),
            ("won", "Đã chốt thuê", "✅", C_OK),
            ("conv", "Tỷ lệ chốt", "🎯", C_OK),
            ("lost", "Mất khách", "❌", C_DANGER),
        )):
            card = StatCard(title, 0, "", color, icon)
            self.kpi[key] = card
            grid.addWidget(card, i // 3, i % 3)
        v.addLayout(grid)

        # ---- FUNNEL ----
        v.addWidget(self._card_head(
            "🔻  FUNNEL BÁN HÀNG - khách rơi ở khâu nào",
            "Số khách đã TỪNG tới từng khâu (tính từ lịch sử trạng thái)"))
        self.funnel_bars = BarList()
        v.addWidget(self._wrap(self.funnel_bars))
        self.lbl_funnel_hint = QLabel("")
        self.lbl_funnel_hint.setWordWrap(True)
        self.lbl_funnel_hint.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{theme.c('warn')};"
            " background:transparent;")
        v.addWidget(self.lbl_funnel_hint)

        # ---- ĐIỂM SAI KHI SALE ----
        v.addWidget(self._card_head(
            "❌  ĐIỂM SAI KHI SALE - lý do mất khách",
            "Khách đã mất tập trung ở điểm nào? (chọn lý do khi chuyển về Mất khách)"))
        self.reason_bars = BarList()
        v.addWidget(self._wrap(self.reason_bars))
        self.lbl_reason_hint = QLabel("")
        self.lbl_reason_hint.setWordWrap(True)
        self.lbl_reason_hint.setStyleSheet(
            f"font-size:12.5px; font-weight:700; color:{C_DANGER};"
            " background:transparent;")
        v.addWidget(self.lbl_reason_hint)

        # ---- nguồn + hoạt động ----
        row = QHBoxLayout()
        row.setSpacing(12)
        col1 = QVBoxLayout()
        col1.setSpacing(6)
        col1.addWidget(self._card_head("📡  NGUỒN KHÁCH", "Khách đến từ đâu"))
        self.source_bars = BarList()
        col1.addWidget(self._wrap(self.source_bars))
        row.addLayout(col1, 1)
        col2 = QVBoxLayout()
        col2.setSpacing(6)
        col2.addWidget(self._card_head("📊  HOẠT ĐỘNG SELLING",
                                       "Số lần gọi / nhắn / xem phòng / ghi chú"))
        self.activity_bars = BarList()
        col2.addWidget(self._wrap(self.activity_bars))
        row.addLayout(col2, 1)
        v.addLayout(row)

        # ---- nhận định tự động ----
        self.lbl_insight = QLabel("")
        self.lbl_insight.setWordWrap(True)
        self.lbl_insight.setObjectName("Card")
        self.lbl_insight.setStyleSheet(
            f"QLabel#Card {{ background:{theme.c('card')}; border:1px solid "
            f"{theme.c('border_soft')}; border-radius:12px; padding:14px 16px;"
            f" font-size:13px; color:{theme.c('text')}; }}")
        v.addWidget(self.lbl_insight)

        v.addStretch(1)
        scroll.setWidget(body)
        self.refresh()

    # ------------------------------------------------------------------ helper
    @staticmethod
    def _card_head(title: str, sub: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 6, 2, 0)
        lay.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:14px; font-weight:800; color:{theme.c('text')};"
            " background:transparent; letter-spacing:-0.2px;")
        lay.addWidget(t)
        s = QLabel(sub)
        s.setStyleSheet(
            f"font-size:11.5px; color:{theme.c('text3')}; background:transparent;")
        lay.addWidget(s)
        return w

    @staticmethod
    def _wrap(w: QWidget) -> QWidget:
        box = QFrame()
        box.setObjectName("Card")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(w)
        return box

    # ------------------------------------------------------------------
    def refresh(self):
        st = self.cm.stats()
        total = int(st.get("total", 0))
        closed = int(st.get("won", 0)) + int(st.get("lost", 0))

        self.kpi["total"].set_value(total, "khách trong CRM")
        self.kpi["active"].set_value(st.get("active", 0), "đang trong pipeline")
        self.kpi["won"].set_value(st.get("won", 0), "đã chốt thuê")
        conv = st.get("conversion")
        self.kpi["conv"].set_value(
            f"{conv}%" if conv is not None else "—",
            f"trên {closed} khách đã kết thúc" if closed else "chưa có khách kết thúc")
        self.kpi["lost"].set_value(
            st.get("lost", 0), "xem lý do ở ngay bên dưới" if st.get("lost") else "chưa mất khách nào")

        # ---- funnel ----
        fr = st.get("funnel_reached") or []
        self.funnel_bars.set_data(
            [(f"{_STAGE_ICON.get(k, '')} {lab}", n,
              CustomerStatus.color(k)) for k, lab, n in fr], total)
        hint = ""
        drops = [(fr[i][2] - fr[i + 1][2], i) for i in range(len(fr) - 1)]
        if drops:
            d, i = max(drops)
            if d > 0:
                hint = (f"⚠️ Rơi nhiều nhất SAU khâu «{fr[i][1]}»: {d} khách "
                        f"đã tới đó nhưng không đi tiếp (sang {fr[i + 1][1]})")
            else:
                hint = "✅ Chưa có khách rơi giữa các khâu"
        self.lbl_funnel_hint.setText(hint)

        # ---- điểm sai khi sale ----
        reasons = st.get("top_reasons") or []
        self.reason_bars.set_data(
            [(lose_reason_label(k) if k else "Khác", n, C_DANGER)
             for k, _, n in reasons], int(st.get("lost", 0)))
        if reasons:
            k, lab, n = reasons[0]
            pct = round(n * 100 / st["lost"]) if st.get("lost") else 0
            self.lbl_reason_hint.setText(
                f"🔴 Điểm sai #1: «{lab}» - {n}/{st['lost']} khách mất ({pct}%)")
        else:
            self.lbl_reason_hint.setText(
                "Chưa có khách mất → chưa có dữ liệu điểm sai (hãy chọn lý do khi chuyển khách về Mất khách)")

        # ---- nguồn ----
        self.source_bars.set_data(
            [(src, n, C_ACCENT) for src, n in (st.get("by_source") or {}).items()], total)

        # ---- hoạt động ----
        act = st.get("activity") or {}
        self.activity_bars.set_data([
            ("📞 Đã gọi", act.get("call", 0), C_ACCENT),
            ("💬 Đã nhắn Zalo", act.get("zalo", 0), C_ACCENT),
            ("👁 Đã xem phòng", act.get("view", 0), C_ACCENT),
            ("📝 Ghi chú", act.get("note", 0), C_ACCENT),
            ("🔄 Đổi trạng thái", act.get("status", 0), C_MUTED),
        ])

        # ---- nhận định ----
        parts: List[str] = []
        if conv is not None:
            parts.append(f"🎯 Tỷ lệ chốt <b>{conv}%</b> trên {closed} khách đã kết thúc")
        if st.get("won_avg_days") is not None:
            parts.append(f"⏱ trung bình <b>{st['won_avg_days']} ngày</b> từ lúc thêm khách tới lúc chốt")
        if reasons:
            k, lab, n = reasons[0]
            parts.append(f"🔴 lý do mất nhiều nhất: <b>{lab}</b> ({n} khách)")
        if st.get("activity", {}).get("call", 0) or st.get("activity", {}).get("zalo", 0):
            calls = st["activity"].get("call", 0) + st["activity"].get("zalo", 0)
            parts.append(f"📞 {calls} lượt liên hệ đã ghi nhận")
        self.lbl_insight.setText(
            "<b>Nhận định:</b> " + "  ·  ".join(parts)
            if parts else
            "<b>Nhận định:</b> Chưa đủ dữ liệu - hãy thêm khách, ghi nhận tương tác "
            "và chọn lý do khi mất khách để hệ thống phân tích.")


# ------------------------------------------------------------------ trang khách hàng
class CustomerPage(QWidget):
    """Trang quản lý khách hàng: bảng pipeline + chi tiết + phân tích điểm sai."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.cm = CustomerManager(manager.db, getattr(manager, "settings", None))
        self._model = CustomerTableModel(self)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- toolbar ----
        from PySide6.QtWidgets import QLineEdit as _QLE
        filt = QFrame()
        filt.setObjectName("Toolbar")
        fl = QHBoxLayout(filt)
        fl.setContentsMargins(22, 10, 22, 10)
        fl.setSpacing(10)

        self.ed_search = _QLE()
        self.ed_search.setPlaceholderText("🔎 Tên / SĐT / Zalo / yêu cầu khách...")
        self.ed_search.setMinimumWidth(230)
        self.ed_search.textChanged.connect(self.refresh)
        fl.addWidget(self.ed_search, 1)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Tất cả trạng thái", None)
        for k in CustomerStatus.ORDER:
            self.cmb_status.addItem(
                f"{_STAGE_ICON.get(k, '')} {CustomerStatus.label(k)}", k)
        self.cmb_status.setToolTip("Lọc theo khâu trong pipeline")
        self.cmb_status.currentIndexChanged.connect(self.refresh)
        fl.addWidget(self.cmb_status)

        self.cmb_source = QComboBox()
        self.cmb_source.addItem("Tất cả nguồn", None)
        for s in CUSTOMER_SOURCES:
            self.cmb_source.addItem(s)
        self.cmb_source.currentIndexChanged.connect(self.refresh)
        fl.addWidget(self.cmb_source)

        self.chk_group = QCheckBox("🧩 Phân cụm pipeline")
        self.chk_group.setChecked(True)
        self.chk_group.setToolTip("Gộp bảng theo từng trạng thái bán hàng")
        self.chk_group.toggled.connect(self.refresh)
        fl.addWidget(self.chk_group)

        self.lbl_sum = QLabel("")
        self.lbl_sum.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{theme.c('text2')};"
            " background:transparent; padding:0 6px;")
        fl.addWidget(self.lbl_sum)

        self.btn_add = QPushButton("＋ Thêm khách hàng")
        self.btn_add.setObjectName("Primary")
        self.btn_add.clicked.connect(self._add)
        fl.addWidget(self.btn_add)
        lay.addWidget(filt)

        # ---- body: splitter bảng | tab [chi tiết, phân tích] ----
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setItemDelegate(CustomerDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, _, w) in enumerate(CustomerTableModel.COLS):
            self.table.setColumnWidth(i, w)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)      # tên khách co giãn
        self.table.clicked.connect(self._on_row_clicked)
        self.table.doubleClicked.connect(self._on_double)
        split.addWidget(self.table)

        self.tabs = QTabWidget()
        self.panel = CustomerDetailPanel(self.cm)
        self.panel.changed.connect(self.refresh)
        self.panel.edit_requested.connect(self._edit)
        self.tabs.addTab(self.panel, "🔎  Chi tiết")
        self.analytics = AnalyticsPanel(self.cm)
        self.tabs.addTab(self.analytics, "📊  Phân tích điểm sai khi sale")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([860, 460])

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(22, 4, 22, 12)
        bl.addWidget(split)
        lay.addWidget(body, 1)

    # ------------------------------------------------------------------ dữ liệu
    def refresh(self, *_):
        text = self.ed_search.text()
        status = self.cmb_status.currentData()
        source = self.cmb_source.currentData()
        rows = self.cm.customers(text=text, status=status, source=source)

        sel_id = (self.panel.customer or {}).get("id")
        self._model.set_rows(rows)
        self._model.set_grouped(self.chk_group.isChecked())

        extra = []
        if status:
            extra.append(CustomerStatus.label(status))
        if source:
            extra.append(source)
        self.lbl_sum.setText(
            f"{len(rows)} khách" + ("  ·  " + " · ".join(extra) if extra else ""))

        self.analytics.refresh()

        # giữ selection: khách đang xem còn trong bảng -> chọn lại; không còn -> chọn khách đầu
        target = None
        if sel_id:
            target = next((r for r in rows if r.get("id") == sel_id), None)
        if target is None and rows:
            target = rows[0]
        if target:
            self._select_row(target["id"])
            if (self.panel.customer or {}).get("id") != target["id"]:
                self.panel.set_customer(target)
        else:
            self.panel.set_customer(None)

    def _select_row(self, cid: str):
        for r in range(self._model.rowCount()):
            rec = self._model.data_row_at(r)
            if rec and rec.get("id") == cid:
                idx = self._model.index(r, 0)
                self.table.selectRow(r)
                return idx
        return None

    def _on_row_clicked(self, idx: QModelIndex):
        if not idx.isValid():
            return
        rec = self._model.data_row_at(idx.row())
        if rec:
            self.panel.set_customer(rec)

    def _on_double(self, idx: QModelIndex):
        if not idx.isValid():
            return
        rec = self._model.data_row_at(idx.row())
        if rec:
            self._edit(rec["id"])

    # ------------------------------------------------------------------ thêm / sửa
    def _collect(self, dlg: CustomerForm) -> Optional[Dict[str, Any]]:
        payload = dlg.payload()
        if not (payload.get("name") or payload.get("phone")):
            QMessageBox.warning(self, "Thiếu dữ liệu",
                                "Cần ít nhất TÊN hoặc SỐ ĐIỆN THOẠI của khách hàng.")
            return None
        fu = payload.get("follow_up") or ""
        if fu and not re.match(r"^\d{4}-\d{2}-\d{2}$", fu):
            QMessageBox.warning(self, "Sai định dạng",
                                "Nhắc lịch phải là YYYY-MM-DD (VD: 2026-11-05) hoặc để trống.")
            return None
        return payload

    def _add(self):
        dlg = CustomerForm(None, None, self)
        if dlg.exec() != QDialog.Accepted:
            return
        payload = self._collect(dlg)
        if payload is None:
            return
        try:
            c = self.cm.add_customer(payload)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không lưu được", str(e))
            return
        self.refresh()
        if c:
            self.panel.set_customer(c)

    def _edit(self, cid: str):
        c = self.cm.customer(cid)
        if not c:
            return
        dlg = CustomerForm(c, None, self)
        if dlg.exec() != QDialog.Accepted:
            return
        payload = self._collect(dlg)
        if payload is None:
            return
        try:
            self.cm.update_customer(cid, payload)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không lưu được", str(e))
            return
        self.refresh()
