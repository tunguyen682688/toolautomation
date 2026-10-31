# -*- coding: utf-8 -*-
"""theme.py - DESIGN SYSTEM 2 chế độ (Sáng / Tối) kiểu app quản lý dự án lớn.

Cách dùng:
    import theme
    theme.set_theme("dark")     # gọi TRƯỚC khi import các module giao diện
    app.setStyleSheet(theme.qss())
    theme.c("accent")           # lấy màu theo chế độ HIỆN TẠI (gọi lúc vẽ/refresh)

Token dùng chung cho QSS sinh động + màu vẽ tay trong paintEvent/setStyleSheet
-> đổi 1 lần là cả ứng dụng đổi theo, không còn màu hardcode đẹt.
"""
from __future__ import annotations

from models import RoomStatus

# ------------------------------------------------------------------ BẢNG MÀU HỆ THỐNG (TOKEN)
LIGHT = {
    "bg": "#F4F6FA",              # nền ứng dụng
    "bg_alt": "#EDF1F7",          # nền nhấn (hover/pressed)
    "card": "#FFFFFF",            # thẻ / panel
    "card2": "#F8FAFC",           # thẻ phụ / hàng xen kẽ
    "border": "#E4E9F0",
    "border_soft": "#EEF2F7",
    "text": "#0F172A",            # chữ chính
    "text2": "#64748B",           # chữ phụ
    "text3": "#94A3B8",           # chữ nhạt
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_soft": "#EFF6FF",
    "accent_soft_text": "#1D4ED8",
    "ok": "#16A34A",
    "ok_soft": "#DCFCE7",
    "warn": "#D97706",
    "warn_soft": "#FEF3C7",
    "orange": "#EA580C",
    "danger": "#DC2626",
    "danger_soft": "#FEE2E2",
    "info": "#0EA5E9",
    "info_soft": "#E0F2FE",
    "sidebar_bg": "#FFFFFF",
    "sidebar_border": "#E6EAF2",
    "sidebar_text": "#64748B",
    "sidebar_hover": "#F1F5F9",
    "sidebar_active": "#EFF6FF",
    "topbar_bg": "#FFFFFF",
    "input_bg": "#FFFFFF",
    "header_bg": "#F8FAFC",
    "track": "#E2E8F0",
    "sel": "#EFF6FF",
    "sel_text": "#0F172A",
    "tooltip_bg": "#0F172A",
    "tooltip_fg": "#FFFFFF",
}

DARK = {
    "bg": "#0A1020",              # nền ứng dụng (navy đen - dễ nhìn ban đêm)
    "bg_alt": "#131C31",
    "card": "#111A2E",
    "card2": "#0D1526",
    "border": "#22304A",
    "border_soft": "#1A2438",
    "text": "#E6EDF7",
    "text2": "#94A3B8",
    "text3": "#64748B",
    "accent": "#3B82F6",
    "accent_hover": "#2563EB",
    "accent_soft": "#152238",
    "accent_soft_text": "#7EB0FF",
    "ok": "#22C55E",
    "ok_soft": "#0F2A1A",
    "warn": "#EAB308",
    "warn_soft": "#2C2406",
    "orange": "#F97316",
    "danger": "#EF4444",
    "danger_soft": "#33141A",
    "info": "#38BDF8",
    "info_soft": "#0B2A3E",
    "sidebar_bg": "#070C18",
    "sidebar_border": "#1A2438",
    "sidebar_text": "#8B98B0",
    "sidebar_hover": "#111A2E",
    "sidebar_active": "#172554",
    "topbar_bg": "#0D1424",
    "input_bg": "#0D1424",
    "header_bg": "#0E1526",
    "track": "#1E293B",
    "sel": "#172554",
    "sel_text": "#E6EDF7",
    "tooltip_bg": "#1E293B",
    "tooltip_fg": "#E6EDF7",
}

PALETTES = {"light": LIGHT, "dark": DARK}
_THEME = "dark"
_PAL = DARK

# Badge trạng thái - nền SÁNG (chế độ light)
STATUS_BG = dict(RoomStatus.BG)
STATUS_BG.update({   # khớp theme.py cũ
    "new": "#EFF6FF", "unsurveyed": "#E0F2FE", "surveyed": "#CCFBF1",
    "vacant": "#DCFCE7", "soon_vacant": "#FEF9C3", "holding": "#FFEDD5",
    "deposit": "#FFEDD5", "rented": "#FEE2E2", "suspended": "#F3F4F6",
    "maintenance": "#F3F4F6",
})
# Badge trạng thái - nền TỐI + chữ sáng (chế độ dark)
STATUS_BG_DARK = {
    "new": "#16294A", "unsurveyed": "#0E2C41", "surveyed": "#0B322F",
    "vacant": "#0F2E1E", "soon_vacant": "#2E2707", "holding": "#33200A",
    "deposit": "#33200A", "rented": "#3A1518", "suspended": "#1C2437",
    "maintenance": "#1C2437",
}
STATUS_TEXT_DARK = {
    "new": "#7DB3FF", "unsurveyed": "#38BDF8", "surveyed": "#2DD4BF",
    "vacant": "#4ADE80", "soon_vacant": "#FACC15", "holding": "#FB923C",
    "deposit": "#FB923C", "rented": "#F87171", "suspended": "#94A3B8",
    "maintenance": "#94A3B8",
}


# ------------------------------------------------------------------ API CHẾ ĐỘ
def get_theme() -> str:
    return _THEME


def c(key: str) -> str:
    """Lấy màu theo token của chế độ hiện tại."""
    return _PAL.get(key, "")


def set_theme(name: str) -> str:
    """Đổi chế độ giao diện -> cập nhật token, hằng C_*, và APP_QSS."""
    global _THEME, _PAL, APP_QSS
    name = "light" if str(name).lower().startswith("light") else "dark"
    _THEME = name
    _PAL = PALETTES[name]
    # đồng bộ hằng cũ (C_ACCENT...) để module import `from theme import C_X` đúng
    globals().update({
        "C_BG": _PAL["bg"], "C_CARD": _PAL["card"], "C_BORDER": _PAL["border"],
        "C_BORDER_SOFT": _PAL["border_soft"], "C_TEXT": _PAL["text"],
        "C_TEXT2": _PAL["text2"], "C_TEXT3": _PAL["text3"],
        "C_ACCENT": _PAL["accent"], "C_ACCENT_HOVER": _PAL["accent_hover"],
        "C_ACCENT_LIGHT": _PAL["accent_soft"], "C_OK": _PAL["ok"],
        "C_OK_LIGHT": _PAL["ok_soft"], "C_WARN": _PAL["warn"],
        "C_WARN_LIGHT": _PAL["warn_soft"], "C_ORANGE": _PAL["orange"],
        "C_DANGER": _PAL["danger"], "C_DANGER_LIGHT": _PAL["danger_soft"],
        "C_MUTED": _PAL["text2"],
    })
    APP_QSS = build_qss()
    return name


def build_qss() -> str:
    """Sinh QSS đầy đủ từ token của chế độ hiện tại."""
    p = _PAL
    (bg, bg_alt, card, card2, border, border_soft) = (
        p["bg"], p["bg_alt"], p["card"], p["card2"], p["border"], p["border_soft"])
    text, text2, text3 = p["text"], p["text2"], p["text3"]
    accent, accent_hover = p["accent"], p["accent_hover"]
    accent_soft, accent_soft_text = p["accent_soft"], p["accent_soft_text"]
    ok, ok_soft, warn, warn_soft = p["ok"], p["ok_soft"], p["warn"], p["warn_soft"]
    orange, danger, danger_soft = p["orange"], p["danger"], p["danger_soft"]
    info, info_soft = p["info"], p["info_soft"]
    (sidebar_bg, sidebar_border, sidebar_text, sidebar_hover, sidebar_active) = (
        p["sidebar_bg"], p["sidebar_border"], p["sidebar_text"],
        p["sidebar_hover"], p["sidebar_active"])
    topbar_bg, input_bg, header_bg = p["topbar_bg"], p["input_bg"], p["header_bg"]
    track, sel, sel_text = p["track"], p["sel"], p["sel_text"]
    tooltip_bg, tooltip_fg = p["tooltip_bg"], p["tooltip_fg"]

    return f"""
/* ============================ TỔNG THỂ ============================ */
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Segoe UI", "Inter", "SF Pro Text", "Arial", sans-serif;
    font-size: 13px;
    font-weight: 500;
}}
QMainWindow, QDialog {{ background: {bg}; }}
QToolTip {{
    background: {tooltip_bg}; color: {tooltip_fg}; border: none; padding: 6px 9px;
    border-radius: 6px; font-size: 12px;
}}

/* ============================ SIDEBAR (Linear/Notion style) ============================ */
#Sidebar {{
    background: {sidebar_bg};
    border-right: 1px solid {sidebar_border};
}}
#AppTitle {{
    font-size: 16.5px; font-weight: 800; color: {accent};
    letter-spacing: -0.4px; background: transparent;
}}
#AppSubtitle {{
    font-size: 11px; color: {text3}; font-weight: 400; background: transparent;
}}
#NavSection {{
    font-size: 10.5px; font-weight: 800; color: {text3};
    letter-spacing: 1.2px; padding: 8px 12px 2px 12px; background: transparent;
}}
#NavButton {{
    background: transparent; border: none; border-radius: 9px;
    padding: 9px 14px; text-align: left; font-size: 13.5px; font-weight: 600;
    color: {sidebar_text};
}}
#NavButton:hover {{ background: {sidebar_hover}; color: {text}; }}
#NavButton:pressed {{ background: {sidebar_active}; }}
#NavButton[active="true"] {{
    background: {sidebar_active}; color: {accent_soft_text}; font-weight: 700;
}}
#SidebarLine {{
    background: transparent; border-top: 1px solid {sidebar_border};
    max-height: 1px; min-height: 1px;
}}
#NavIcon {{ font-size: 16px; }}

/* ============================ TOPBAR (phẳng, tinh gọn) ============================ */
#TopBar {{
    background: {topbar_bg};
    border-bottom: 1px solid {border};
}}
#PageHeaderTitle {{
    font-size: 19px; font-weight: 800; color: {text};
    letter-spacing: -0.4px; background: transparent;
}}
#PageHeaderSubtitle {{
    font-size: 12.5px; color: {text2}; background: transparent; font-weight: 500;
}}
#SearchBox {{
    background: {input_bg}; border: 1px solid {border}; border-radius: 10px;
    padding: 9px 14px; font-size: 13.5px; color: {text};
    selection-background-color: {accent}; selection-color: #FFFFFF;
}}
#SearchBox:focus {{ border: 1.5px solid {accent}; }}
#SearchBox::placeholder {{ color: {text3}; }}
#SearchIcon {{ color: {text3}; font-size: 15px; background: transparent; border: none; }}
#SearchHint {{ color: {text3}; font-size: 11.5px; background: transparent; }}

/* ============================ NÚT (HỆ THỐNG) ============================ */
QPushButton {{
    background: {card}; border: 1px solid {border}; border-radius: 9px;
    padding: 8px 15px; font-weight: 600; color: {text}; font-size: 13px;
}}
QPushButton:hover {{ background: {bg_alt}; border-color: {border}; }}
QPushButton:pressed {{ background: {border_soft}; }}
QPushButton:disabled {{ color: {text3}; background: {card2}; border-color: {border_soft}; }}
QPushButton#Primary {{
    background: {accent}; color: white; border: none; border-radius: 9px;
    padding: 9px 18px; font-weight: 700; font-size: 13.5px;
}}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Primary:pressed {{ background: {accent_hover}; }}
QPushButton#Primary:disabled {{ background: {card2}; color: {text3}; }}
QPushButton#Danger {{
    background: {danger_soft}; color: {danger}; border: 1px solid transparent;
    border-radius: 9px; padding: 8px 15px; font-weight: 700;
}}
QPushButton#Danger:hover {{ border-color: {danger}; }}
QPushButton#Ghost {{
    background: transparent; border: none; color: {accent};
    font-weight: 700; font-size: 13px;
}}
QPushButton#Ghost:hover {{ background: {accent_soft}; }}
QPushButton#Chip {{
    background: {accent_soft}; color: {accent_soft_text}; border: none;
    border-radius: 16px; padding: 5px 13px; font-size: 12px; font-weight: 700;
}}
QPushButton#Chip:hover {{ background: {sidebar_active}; }}
QPushButton#DetailAction {{
    background: {card}; border: 1px solid {border}; border-radius: 10px;
    padding: 9px 14px; font-weight: 600; color: {text};
    text-align: left; font-size: 13px;
}}
QPushButton#DetailAction:hover {{
    background: {accent_soft}; border-color: {accent}; color: {accent_soft_text};
}}

/* ============================ THẺ (CARD) ============================ */
QFrame#Card {{
    background: {card}; border: 1px solid {border}; border-radius: 14px;
}}
QFrame#StatCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {card}, stop:1 {card2});
    border: 1px solid {border}; border-radius: 14px;
}}
QFrame#StatCard[clickable="true"]:hover {{
    background: {accent_soft}; border-color: {accent};
}}
QLabel#StatValue {{ font-size: 28px; font-weight: 800; color: {text}; letter-spacing: -0.5px; background: transparent; }}
QLabel#StatTitle {{ font-size: 13px; color: {text2}; font-weight: 600; letter-spacing: -0.2px; background: transparent; }}
QLabel#StatHint {{ font-size: 11px; color: {text3}; background: transparent; }}
QLabel#SectionTitle {{ font-size: 16.5px; font-weight: 800; color: {text}; letter-spacing: -0.4px; background: transparent; }}
QLabel#Muted {{ color: {text2}; background: transparent; }}
QLabel#PageTitle {{ font-size: 22px; font-weight: 800; color: {text}; letter-spacing: -0.5px; background: transparent; }}

/* ============================ BẢNG DỮ LIỆU ============================ */
QTableView {{
    background: {card};
    alternate-background-color: {card2};
    border: 1px solid {border};
    border-radius: 14px;
    gridline-color: {border_soft};
    selection-background-color: {sel};
    selection-color: {sel_text};
    outline: none;
    font-size: 13px;
}}
QTableView::item {{ padding: 10px 12px; border-bottom: 1px solid {border_soft}; }}
QTableView::item:selected {{ background: {sel}; color: {sel_text}; }}
QHeaderView::section {{
    background: {header_bg}; color: {text2}; padding: 12px; border: none;
    border-bottom: 1px solid {border}; border-right: 1px solid {border_soft};
    font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
}}
QHeaderView::section:hover {{ background: {accent_soft}; color: {accent_soft_text}; }}

/* ============================ THANH CÔNG CỤ / LỌC ============================ */
QFrame#Toolbar {{
    background: {card}; border: 1px solid {border}; border-radius: 14px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    background: {input_bg}; border: 1px solid {border}; border-radius: 9px;
    padding: 8px 12px; selection-background-color: {accent}; selection-color: #FFFFFF;
    font-size: 13px; color: {text};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1.5px solid {accent}; }}
QLineEdit:read-only, QSpinBox:read-only {{ color: {text2}; background: {card2}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {card}; border: 1px solid {border}; border-radius: 10px;
    selection-background-color: {accent_soft}; selection-color: {accent_soft_text};
    outline: none; font-size: 13px; color: {text};
}}
QCheckBox {{ spacing: 8px; font-size: 13px; color: {text}; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px;
    border: 1.5px solid {border}; background: {input_bg}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

/* ============================ MENU CHUỘT PHẢI ============================ */
QMenu {{
    background: {card}; border: 1px solid {border}; border-radius: 10px;
    padding: 6px; color: {text}; font-size: 13px;
}}
QMenu::item {{ background: transparent; border-radius: 7px; padding: 8px 22px 8px 14px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {accent_soft_text}; }}
QMenu::separator {{ height: 1px; background: {border_soft}; margin: 5px 8px; }}

/* ============================ FORM / NHÓM ============================ */
QGroupBox {{
    background: {card}; border: 1px solid {border}; border-radius: 14px;
    margin-top: 16px; padding-top: 10px; font-weight: 700; color: {text};
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 16px; padding: 0 8px;
    color: {accent_soft_text}; font-size: 13px; font-weight: 800;
}}
QFormLayout {{ }}
QLabel {{ background: transparent; }}

/* ============================ THANH CUỘN ============================ */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {text3}; border-radius: 5px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {text2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {text3}; border-radius: 5px; min-width: 40px; }}
QScrollBar::handle:horizontal:hover {{ background: {text2}; }}
QTabWidget::pane {{
    border: 1px solid {border}; border-radius: 14px; background: {card}; top: -1px;
}}
QTabBar::tab {{
    background: transparent; padding: 11px 22px; color: {text2};
    font-weight: 700; font-size: 13px; border-bottom: 3px solid transparent;
}}
QTabBar::tab:selected {{ color: {accent_soft_text}; border-bottom: 3px solid {accent}; }}
QTabBar::tab:hover {{ color: {accent_soft_text}; }}

QStatusBar {{
    background: {card}; border-top: 1px solid {border}; color: {text2};
    font-size: 12px; font-weight: 500;
}}
QProgressBar {{
    background: {track}; border: none; border-radius: 6px; height: 8px;
    text-align: center; color: {text};
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}

/* ============================ THANH KÉO (SPLITTER) ============================ */
QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {accent}; }}

/* ============================ POPUP TÌM KIẾM ============================ */
QListView#SearchPopup {{
    background: {card}; border: 1px solid {border}; border-radius: 14px;
    padding: 6px; selection-background-color: {accent_soft};
    selection-color: {accent_soft_text}; color: {text};
}}
QListView#SearchPopup::item {{ padding: 10px 12px; border-radius: 10px; }}
QListView#SearchPopup::item:selected {{ background: {accent_soft}; }}

/* ============================ PANEL CHI TIẾT PHÒNG ============================ */
QFrame#DetailPanel {{
    background: {card}; border: 1px solid {border}; border-radius: 14px;
}}
QLabel#DetailLabel {{ color: {text2}; font-size: 12px; font-weight: 700; }}
QLabel#DetailValue {{ color: {text}; font-size: 14px; font-weight: 600; }}

/* ============================ BIỂU MẪU PHỤ ============================ */
QLabel#Badge {{ background: {accent_soft}; color: {accent_soft_text}; border-radius: 10px; }}
""" + _legend_qss(p)


def _legend_qss(p: dict) -> str:
    """QSS cho các chi tiết vẽ tay thường dùng."""
    return f"""
QFrame#MetricBox {{
    background: {p['card2']}; border: 1px solid {p['border']}; border-radius: 10px;
}}
QLabel#Kicker {{
    color: {p['text3']}; font-size: 11px; font-weight: 800;
    letter-spacing: 0.5px; background: transparent;
}}
QLabel#MetaText {{
    color: {p['text3']}; font-size: 11px; font-weight: 600;
    background: transparent;
}}
"""


# ------------------------------------------------------------------ HÀM HỖ TRỢ
def status_color(key: str) -> str:
    """Màu CHỮ trạng thái theo chế độ hiện tại."""
    if _THEME == "dark":
        return STATUS_TEXT_DARK.get(key, "#94A3B8")
    return RoomStatus.color(key)


def status_bg(key: str) -> str:
    """Màu NỀN badge trạng thái theo chế độ hiện tại."""
    if _THEME == "dark":
        return STATUS_BG_DARK.get(key, "#1C2437")
    return STATUS_BG.get(key, "#F3F4F6")


def status_label(key: str) -> str:
    return RoomStatus.label(key)


# ------------------------------------------------------------------ KHỞI TẠO
# Hằng kiểu cũ (module `from theme import C_X` lấy giá trị lúc import).
# main.py gọi set_theme() TRƯỚC khi import giao diện -> luôn đúng chế độ.
# Mặc định DARK (phong cách app quản lý dự án).
_THEME = "dark"
_PAL = DARK
globals().update({
    "C_BG": DARK["bg"], "C_CARD": DARK["card"], "C_BORDER": DARK["border"],
    "C_BORDER_SOFT": DARK["border_soft"], "C_TEXT": DARK["text"],
    "C_TEXT2": DARK["text2"], "C_TEXT3": DARK["text3"],
    "C_ACCENT": DARK["accent"], "C_ACCENT_HOVER": DARK["accent_hover"],
    "C_ACCENT_LIGHT": DARK["accent_soft"], "C_OK": DARK["ok"],
    "C_OK_LIGHT": DARK["ok_soft"], "C_WARN": DARK["warn"],
    "C_WARN_LIGHT": DARK["warn_soft"], "C_ORANGE": DARK["orange"],
    "C_DANGER": DARK["danger"], "C_DANGER_LIGHT": DARK["danger_soft"],
    "C_MUTED": DARK["text2"],
})
APP_QSS = build_qss()
