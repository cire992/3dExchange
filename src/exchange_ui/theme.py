"""Colors and the Qt style sheet, taken from the main-window mockup (dark, teal accent)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

BG = "#121418"
PANEL = "#16181c"
SURFACE = "#1a1d22"
CARD = "#20242a"
CARD_HOVER = "#262a31"
BORDER = "#2b3038"
TEXT = "#e7e9ec"
TEXT_2 = "#c9ced6"
MUTED = "#8a919d"
MUTED_2 = "#a0a7b2"
ACCENT = "#57c4d3"
ACCENT_LIGHT = "#8adbe6"
ACCENT_BG = "#1f3438"
ACCENT_DARK = "#0e1a1c"
WARN = "#e9a84c"
WARN_LIGHT = "#f0c27e"
WARN_BG = "#241e15"
WARN_BORDER = "#4a3a22"
ERROR = "#e88b8b"

UI_FAMILIES = ["Inter", "Segoe UI", "system-ui", "sans-serif"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Mono", "Consolas", "monospace"]


def color(name: str) -> QColor:
    return QColor(name)


def palette() -> QPalette:
    """Dark colors for the controls the style sheet does not draw (combo boxes, check boxes ...)."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: SURFACE, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG, QPalette.ColorRole.AlternateBase: PANEL,
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: CARD,
        QPalette.ColorRole.ButtonText: TEXT_2, QPalette.ColorRole.Highlight: ACCENT_BG,
        QPalette.ColorRole.HighlightedText: ACCENT_LIGHT, QPalette.ColorRole.ToolTipBase: SURFACE,
        QPalette.ColorRole.ToolTipText: TEXT, QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.Light: CARD_HOVER, QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: PANEL, QPalette.ColorRole.Shadow: BG,
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(MUTED))
    return p


def ui_font(size: float = 9.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(UI_FAMILIES)
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def mono_font(size: float = 7.5) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setFamilies(MONO_FAMILIES)
    font.setPointSizeF(size)
    return font


STYLE = f"""
* {{ color: {TEXT}; }}
QMainWindow, QWidget#central {{ background: {BG}; }}
QWidget#topbar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QWidget#sidebar, QTreeView#sidebarTree {{ background: {PANEL}; border: none; }}
QWidget#inspector {{ background: {PANEL}; border-left: 1px solid {BORDER}; }}
QWidget#statusbar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel#appName {{ font-weight: 600; font-size: 11pt; }}
QLabel#sectionLabel {{ color: {MUTED}; font-size: 7.5pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#breadcrumb, QLabel#muted {{ color: {MUTED}; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#subtitle {{ color: {MUTED_2}; }}
QLabel#error {{ color: {ERROR}; }}
QLabel#inspectorName {{ font-size: 12pt; font-weight: 600; }}
QLabel#chip {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 9px; padding: 1px 8px; color: {TEXT_2}; }}
QLabel#warnChip {{ background: {WARN_BG}; border: 1px solid {WARN_BORDER}; border-radius: 9px; padding: 1px 8px; color: {WARN_LIGHT}; }}
QLineEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 10px;
    selection-background-color: {ACCENT_BG};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 10px; color: {TEXT_2}; }}
QComboBox:hover {{ background: {CARD_HOVER}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_BG}; }}
QPlainTextEdit {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; color: {TEXT_2};
}}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_DARK}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_LIGHT}; }}
QPushButton#primary:disabled {{ background: {ACCENT_BG}; color: {MUTED}; }}
QPushButton#segment {{ border-radius: 0; padding: 5px 12px; }}
QPushButton#segment:checked {{ background: {ACCENT_BG}; color: {ACCENT_LIGHT}; border-color: {ACCENT_BG}; }}
QPushButton#unidentified {{
    background: {WARN_BG}; border: 1px solid {WARN_BORDER}; color: {WARN_LIGHT}; text-align: left; padding: 8px 12px;
}}
QPushButton#unidentified:checked {{ border-color: {WARN}; }}
QTreeView {{ outline: 0; show-decoration-selected: 1; }}
QTreeView::item {{ padding: 5px 4px; border-radius: 5px; }}
QTreeView::item:hover {{ background: {CARD}; }}
QTreeView::item:selected {{ background: {ACCENT_BG}; color: {ACCENT_LIGHT}; }}
QListView {{ background: {BG}; border: none; outline: 0; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar::tab {{ background: transparent; color: {MUTED_2}; padding: 7px 10px; border: none; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QTableWidget {{ background: transparent; border: none; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; padding: 4px; }}
QProgressBar {{ background: {CARD}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_BG}; color: {ACCENT_LIGHT}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QSplitter::handle {{ background: {BORDER}; }}
"""
