# -*- coding: utf-8 -*-
"""theme.py - Chủ đề giao diện sáng, sạch, chuyên nghiệp (QSS) + tiện ích màu sắc."""
from __future__ import annotations

from models import RoomStatus

# Bảng màu chung
C_BG = "#F4F6FB"
C_CARD = "#FFFFFF"
C_BORDER = "#E4E8F0"
C_TEXT = "#0F172A"
C_TEXT2 = "#64748B"
C_ACCENT = "#2563EB"
C_ACCENT_HOVER = "#1D4ED8"
C_OK = "#16A34A"
C_WARN = "#EAB308"
C_ORANGE = "#F97316"
C_DANGER = "#DC2626"
C_MUTED = "#6B7280"

APP_QSS = f"""
/* ============================ TỔNG THỂ ============================ */
QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: "Segoe UI", "Inter", "Arial", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {C_BG}; }}
QToolTip {{
    background: #0F172A; color: #FFFFFF; border: none; padding: 6px 8px;
    border-radius: 6px; font-size: 12px;
}}

/* ============================ SIDEBAR ============================ */
#Sidebar {{
    background: {C_CARD};
    border-right: 1px solid {C_BORDER};
}}
#AppTitle {{ font-size: 17px; font-weight: 800; color: {C_ACCENT}; letter-spacing: .4px; }}
#AppSubtitle {{ font-size: 11px; color: {C_TEXT2}; }}
#NavButton {{
    background: transparent; border: none; border-radius: 9px;
    padding: 11px 14px; text-align: left; font-size: 13.5px; font-weight: 600;
    color: #334155;
}}
#NavButton:hover {{ background: #EEF2FF; color: {C_ACCENT}; }}
#NavButton[active="true"] {{ background: #E8EEFF; color: {C_ACCENT}; }}
#NavIcon {{ font-size: 16px; }}

/* ============================ THANH TRÊN ============================ */
#TopBar {{ background: {C_CARD}; border-bottom: 1px solid {C_BORDER}; }}
#SearchBox {{
    background: #F1F5F9; border: 1.5px solid {C_BORDER}; border-radius: 11px;
    padding: 11px 14px 11px 38px; font-size: 15px; selection-background-color: {C_ACCENT};
}}
#SearchBox:focus {{ background: #FFFFFF; border: 1.5px solid {C_ACCENT}; }}
#SearchIcon {{ color: {C_TEXT2}; font-size: 16px; background: transparent; border: none; }}
#SearchHint {{ color: #94A3B8; font-size: 11.5px; }}

/* ============================ NÚT ============================ */
QPushButton {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px;
    padding: 7px 14px; font-weight: 600; color: #1E293B;
}}
QPushButton:hover {{ background: #F8FAFC; border-color: #CBD5E1; }}
QPushButton:pressed {{ background: #EEF2F7; }}
QPushButton:disabled {{ color: #94A3B8; background: #F1F5F9; }}
QPushButton#Primary {{
    background: {C_ACCENT}; color: white; border: none; border-radius: 8px; padding: 8px 16px;
}}
QPushButton#Primary:hover {{ background: {C_ACCENT_HOVER}; }}
QPushButton#Danger {{ background: #FEF2F2; color: {C_DANGER}; border: 1px solid #FECACA; }}
QPushButton#Danger:hover {{ background: #FEE2E2; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {C_ACCENT}; }}
QPushButton#Ghost:hover {{ background: #EEF2FF; }}
QPushButton#Chip {{
    background: #EEF2FF; color: {C_ACCENT}; border: none; border-radius: 12px;
    padding: 5px 12px; font-size: 12px;
}}

/* ============================ THẺ (CARD) ============================ */
QFrame#Card {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px;
}}
QFrame#Card:hover {{ border-color: #C7D2FE; }}
QFrame#StatCard {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px;
}}
QFrame#StatCard[clickable="true"]:hover {{ border-color: {C_ACCENT}; background: #FBFDFF; }}
QLabel#StatValue {{ font-size: 26px; font-weight: 800; color: {C_TEXT}; }}
QLabel#StatTitle {{ font-size: 12.5px; color: {C_TEXT2}; font-weight: 600; }}
QLabel#StatHint {{ font-size: 11px; color: #94A3B8; }}
QLabel#SectionTitle {{ font-size: 16px; font-weight: 800; color: {C_TEXT}; }}
QLabel#Muted {{ color: {C_TEXT2}; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 800; }}

/* ============================ BẢNG DỮ LIỆU ============================ */
QTableView {{
    background: {C_CARD};
    alternate-background-color: #FAFBFD;
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    gridline-color: #EEF1F6;
    selection-background-color: #DBEAFE;
    selection-color: #0F172A;
    outline: none;
}}
QTableView::item {{ padding: 6px 8px; border-bottom: 1px solid #F1F5F9; }}
QTableView::item:selected {{ background: #DBEAFE; color: #0F172A; }}
QHeaderView::section {{
    background: #F8FAFC; color: #475569; padding: 8px; border: none;
    border-bottom: 1px solid {C_BORDER}; border-right: 1px solid #F1F5F9;
    font-weight: 700; font-size: 12px;
}}
QHeaderView::section:hover {{ background: #EEF2F7; }}

/* ============================ THANH CÔNG CỤ / LỌC ============================ */
QFrame#Toolbar {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF; border: 1px solid {C_BORDER}; border-radius: 8px;
    padding: 6px 9px; selection-background-color: {C_ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1.5px solid {C_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {C_BORDER}; border-radius: 8px;
    selection-background-color: #EEF2FF; selection-color: {C_ACCENT};
    outline: none;
}}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid #CBD5E1; background: white; }}
QCheckBox::indicator:checked {{ background: {C_ACCENT}; border-color: {C_ACCENT}; }}

/* ============================ GROUPBOX / FORM ============================ */
QGroupBox {{
    background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px;
    margin-top: 14px; padding-top: 8px; font-weight: 700; color: #1E293B;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {C_ACCENT}; font-size: 13px;
}}
QFormLayout {{ }}
QLabel {{ background: transparent; }}

/* ============================ THANH CUỘN / KHÁC ============================ */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #CBD5E1; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CBD5E1; border-radius: 5px; min-width: 30px; }}
QTabWidget::pane {{ border: 1px solid {C_BORDER}; border-radius: 10px; background: white; top: -1px; }}
QTabBar::tab {{
    background: transparent; padding: 9px 18px; color: {C_TEXT2}; font-weight: 700;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {C_ACCENT}; border-bottom: 2px solid {C_ACCENT}; }}
QTabBar::tab:hover {{ color: {C_ACCENT}; }}

QStatusBar {{ background: {C_CARD}; border-top: 1px solid {C_BORDER}; color: {C_TEXT2}; }}
QProgressBar {{ background: #E2E8F0; border: none; border-radius: 5px; height: 7px; text-align: center; }}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 5px; }}

/* ============================ POPUP KẾT QUẢ TÌM ============================ */
QListView#SearchPopup {{
    background: white; border: 1px solid {C_BORDER}; border-radius: 10px;
    padding: 4px; selection-background-color: #EEF2FF; selection-color: {C_TEXT};
}}
QListView#SearchPopup::item {{ padding: 8px 10px; border-radius: 7px; }}
QListView#SearchPopup::item:selected {{ background: #EEF2FF; }}
"""


def status_color(key: str) -> str:
    return RoomStatus.color(key)


def status_bg(key: str) -> str:
    return RoomStatus.bg(key)


def status_label(key: str) -> str:
    return RoomStatus.label(key)
