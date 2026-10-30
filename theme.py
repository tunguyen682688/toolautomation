# -*- coding: utf-8 -*-
"""theme.py - Chủ đề giao diện hiện đại, sang trọng (hệ thống quản lý bậc nhất).
Màu sắc: slate/indigo, gradient nhẹ, shadow, border radius lớn, typography sạch.
"""
from __future__ import annotations

from models import RoomStatus

# ------------------------------------------------------------------ BẢNG MÀU HỆ THỐNG
C_BG = "#F3F4F6"            # nền tổng thể (xám rất nhạt)
C_CARD = "#FFFFFF"          # nền thẻ/card trắng
C_BORDER = "#E5E7EB"        # viền nhẹ
C_BORDER_SOFT = "#F3F4F6"   # viền mờ hơn
C_TEXT = "#111827"          # chữ chính (đen xám đậm)
C_TEXT2 = "#6B7280"         # chữ phụ
C_TEXT3 = "#9CA3AF"         # chữ nhạt
C_ACCENT = "#2563EB"        # xanh dương chính
C_ACCENT_HOVER = "#1D4ED8"  # xanh dương hover
C_ACCENT_LIGHT = "#EFF6FF"  # nền xanh dương nhạt
C_OK = "#15803D"            # xanh lá
C_OK_LIGHT = "#DCFCE7"
C_WARN = "#D97706"          # vàng cam
C_WARN_LIGHT = "#FEF3C7"
C_ORANGE = "#EA580C"
C_DANGER = "#DC2626"        # đỏ
C_DANGER_LIGHT = "#FEE2E2"
C_MUTED = "#6B7280"

# Màu nền từng trạng thái phòng (mild pastel)
STATUS_BG = {
    "new": "#EFF6FF",           # xanh dương nhạt
    "unsurveyed": "#E0F2FE",    # xanh cyanh nhạt
    "surveyed": "#CCFBF1",      # xanh ngọc nhạt
    "vacant": "#DCFCE7",        # xanh lá nhạt
    "soon_vacant": "#FEF9C3",   # vàng nhạt
    "holding": "#FFEDD5",       # cam nhạt
    "deposit": "#FFEDD5",
    "rented": "#FEE2E2",        # đỏ nhạt
    "suspended": "#F3F4F6",     # xám nhạt
    "maintenance": "#F3F4F6",
}

APP_QSS = f"""
/* ============================ TỔNG THỂ ============================ */
QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: "Segoe UI", "Inter", "SF Pro Text", "Arial", sans-serif;
    font-size: 13px;
    font-weight: 500;
}}
QMainWindow, QDialog {{ background: {C_BG}; }}
QToolTip {{
    background: {C_TEXT}; color: #FFFFFF; border: none; padding: 6px 8px;
    border-radius: 6px; font-size: 12px;
}}

/* ============================ SIDEBAR (kéo dài, hiện đại) ============================ */
#Sidebar {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {C_CARD}, stop:1 {C_BG}
    );
    border-right: 1px solid {C_BORDER};
}}
#AppTitle {{
    font-size: 17px; font-weight: 800; color: {C_ACCENT};
    letter-spacing: -0.5px;
}}
#AppSubtitle {{
    font-size: 11px; color: {C_TEXT2};
    font-weight: 400;
}}
#NavButton {{
    background: transparent; border: none; border-radius: 10px;
    padding: 12px 16px; text-align: left; font-size: 14px; font-weight: 600;
    color: {C_TEXT2};
}}
#NavButton:hover {{ background: {C_ACCENT_LIGHT}; color: {C_ACCENT}; }}
#NavButton[active="true"] {{
    background: {C_ACCENT_LIGHT}; color: {C_ACCENT};
    border-left: 4px solid {C_ACCENT};
    padding-left: 12px;
}}
#NavIcon {{ font-size: 16px; }}

/* ============================ HEADER / THANH TRÊN ============================ */
#TopBar {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {C_ACCENT}, stop:1 {C_ACCENT_HOVER}
    );
    border: none;
    color: #FFFFFF;
}}
#TopBar QLabel {{ color: #FFFFFF; background: transparent; }}
#PageHeaderTitle {{
    font-size: 20px; font-weight: 800; color: #FFFFFF; background: transparent;
    letter-spacing: -0.5px;
}}
#PageHeaderSubtitle {{
    font-size: 12.5px; color: rgba(255,255,255,0.85); background: transparent;
    font-weight: 500;
}}
#PageHeaderSubtitle {{
    font-size: 12.5px; color: rgba(255,255,255,0.85); background: transparent;
    font-weight: 500;
}}
#SearchBox {{
    background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3);
    border-radius: 10px; padding: 10px 14px 10px 36px; font-size: 14px;
    color: #FFFFFF; selection-background-color: {C_ACCENT};
}}
#SearchBox:focus {{ background: rgba(255,255,255,0.25); border: 1px solid #FFFFFF; }}
#SearchBox::placeholder {{ color: rgba(255,255,255,0.7); }}
#SearchIcon {{ color: rgba(255,255,255,0.8); font-size: 16px; background: transparent; border: none; }}
#SearchHint {{ color: rgba(255,255,255,0.65); font-size: 11.5px; }}

/* ============================ NÚT (HỆ THỐNG) ============================ */
QPushButton {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px;
    padding: 8px 16px; font-weight: 600; color: {C_TEXT};
    font-size: 13px;
}}
QPushButton:hover {{ background: {C_BG}; border-color: {C_BORDER}; }}
QPushButton:pressed {{ background: {C_BORDER_SOFT}; }}
QPushButton:disabled {{ color: {C_TEXT3}; background: {C_BORDER_SOFT}; }}
QPushButton#Primary {{
    background: {C_ACCENT}; color: white; border: none; border-radius: 10px;
    padding: 9px 18px; font-weight: 700; font-size: 13.5px;
}}
QPushButton#Primary:hover {{ background: {C_ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: #1E40AF; }}
QPushButton#Danger {{
    background: {C_DANGER_LIGHT}; color: {C_DANGER}; border: 1px solid {C_DANGER_LIGHT};
    border-radius: 10px; padding: 8px 16px; font-weight: 700;
}}
QPushButton#Danger:hover {{ background: #FECACA; }}
QPushButton#Ghost {{
    background: transparent; border: none; color: {C_ACCENT};
    font-weight: 700; font-size: 13px;
}}
QPushButton#Ghost:hover {{ background: {C_ACCENT_LIGHT}; }}
QPushButton#Chip {{
    background: {C_ACCENT_LIGHT}; color: {C_ACCENT}; border: none; border-radius: 20px;
    padding: 4px 14px; font-size: 12px; font-weight: 700;
}}
QPushButton#Chip:hover {{ background: #DBEAFE; }}
QPushButton#DetailAction {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px;
    padding: 9px 14px; font-weight: 600; color: {C_TEXT};
    text-align: left; font-size: 13px;
}}
QPushButton#DetailAction:hover {{ background: {C_ACCENT_LIGHT}; border-color: {C_ACCENT}; color: {C_ACCENT}; }}
QPushButton#DetailAction:pressed {{ background: #DBEAFE; }}

/* ============================ THẺ (CARD) CAO CẤP ============================ */
QFrame#Card {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 16px;
}}
QFrame#Card:hover {{ border-color: {C_BORDER}; }}
QFrame#StatCard {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {C_CARD}, stop:1 #FAFBFC
    );
    border: 1px solid {C_BORDER}; border-radius: 16px;
}}
QFrame#StatCard[clickable="true"]:hover {{
    background: {C_ACCENT_LIGHT};
    border-color: {C_ACCENT};
}}
QLabel#StatValue {{
    font-size: 28px; font-weight: 800; color: {C_TEXT};
    letter-spacing: -0.5px;
}}
QLabel#StatTitle {{
    font-size: 13px; color: {C_TEXT2}; font-weight: 600;
    letter-spacing: -0.2px;
}}
QLabel#StatHint {{ font-size: 11px; color: {C_TEXT3}; }}
QLabel#SectionTitle {{
    font-size: 17px; font-weight: 800; color: {C_TEXT};
    letter-spacing: -0.5px;
}}
QLabel#Muted {{ color: {C_TEXT2}; }}
QLabel#PageTitle {{
    font-size: 22px; font-weight: 800; color: {C_TEXT};
    letter-spacing: -0.5px;
}}

/* ============================ BẢNG DỮ LIỆU (Hiện đại) ============================ */
QTableView {{
    background: {C_CARD};
    alternate-background-color: #FAFBFC;
    border: 1px solid {C_BORDER};
    border-radius: 14px;
    gridline-color: #F3F4F6;
    selection-background-color: {C_ACCENT_LIGHT};
    selection-color: {C_TEXT};
    outline: none;
    font-size: 13px;
}}
QTableView::item {{
    padding: 10px 12px;
    border-bottom: 1px solid {C_BORDER_SOFT};
}}
QTableView::item:selected {{
    background: {C_ACCENT_LIGHT};
    color: {C_TEXT};
}}
QHeaderView::section {{
    background: #FAFBFC; color: {C_TEXT2}; padding: 12px; border: none;
    border-bottom: 1px solid {C_BORDER}; border-right: 1px solid {C_BORDER_SOFT};
    font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
}}
QHeaderView::section:hover {{ background: {C_ACCENT_LIGHT}; color: {C_ACCENT}; }}

/* ============================ THANH CÔNG CỤ / LỌC ============================ */
QFrame#Toolbar {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 14px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF; border: 1px solid {C_BORDER}; border-radius: 10px;
    padding: 9px 12px; selection-background-color: {C_ACCENT};
    font-size: 13px;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1.5px solid {C_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {C_BORDER}; border-radius: 10px;
    selection-background-color: {C_ACCENT_LIGHT}; selection-color: {C_TEXT};
    outline: none; font-size: 13px;
}}
QCheckBox {{ spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px;
    border: 1.5px solid {C_BORDER}; background: white; }}
QCheckBox::indicator:checked {{ background: {C_ACCENT}; border-color: {C_ACCENT}; }}

/* ============================ FORM / NHÓM ============================ */
QGroupBox {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 14px;
    margin-top: 16px; padding-top: 10px; font-weight: 700; color: {C_TEXT};
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 16px; padding: 0 8px;
    color: {C_ACCENT}; font-size: 13px; font-weight: 800;
}}
QFormLayout {{ }}
QLabel {{ background: transparent; }}

/* ============================ THANH CUỘN ============================ */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {C_TEXT3}; border-radius: 5px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: {C_TEXT2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {C_TEXT3}; border-radius: 5px; min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C_TEXT2}; }}
QTabWidget::pane {{
    border: 1px solid {C_BORDER}; border-radius: 14px; background: white; top: -1px;
}}
QTabBar::tab {{
    background: transparent; padding: 11px 22px; color: {C_TEXT2};
    font-weight: 700; font-size: 13px; border-bottom: 3px solid transparent;
}}
QTabBar::tab:selected {{ color: {C_ACCENT}; border-bottom: 3px solid {C_ACCENT}; }}
QTabBar::tab:hover {{ color: {C_ACCENT}; }}

QStatusBar {{
    background: {C_CARD}; border-top: 1px solid {C_BORDER}; color: {C_TEXT2};
    font-size: 12px; font-weight: 500;
}}
QProgressBar {{
    background: {C_BORDER_SOFT}; border: none; border-radius: 6px; height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 6px; }}

/* ============================ POPUP TÌM KIẾM ============================ */
QListView#SearchPopup {{
    background: white; border: 1px solid {C_BORDER}; border-radius: 14px;
    padding: 6px; selection-background-color: {C_ACCENT_LIGHT};
    selection-color: {C_TEXT};
}}
QListView#SearchPopup::item {{ padding: 10px 12px; border-radius: 10px; }}
QListView#SearchPopup::item:selected {{ background: {C_ACCENT_LIGHT}; }}

/* ============================ PANEL CHI TIẾT PHÒNG ============================ */
QFrame#DetailPanel {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 16px;
}}
QLabel#DetailLabel {{ color: {C_TEXT2}; font-size: 12px; font-weight: 700; }}
QLabel#DetailValue {{ color: {C_TEXT}; font-size: 14px; font-weight: 600; }}
"""

# ------------------------------------------------------------------ HÀM HỖ TRỢ
def status_color(key: str) -> str:
    return RoomStatus.color(key)


def status_bg(key: str) -> str:
    return STATUS_BG.get(key, "#F3F4F6")


def status_label(key: str) -> str:
    return RoomStatus.label(key)
