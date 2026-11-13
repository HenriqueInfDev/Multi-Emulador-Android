"""Tema escuro do gerenciador."""

BG = "#0f1218"
SURFACE = "#161a22"
CARD = "#1a1f29"
CARD_HOVER = "#1e2430"
BORDER = "#2a3140"
TEXT = "#e6e9ef"
MUTED = "#8b93a3"
ACCENT = "#3d7bfd"
ACCENT_HOVER = "#5a8fff"
GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"
GRAY = "#5b6375"

STATUS_COLORS = {
    "on": GREEN,
    "booting": AMBER,
    "starting": AMBER,
    "restarting": AMBER,
    "stopping": AMBER,
    "busy": ACCENT,
    "off": GRAY,
    "missing": "#3a4252",
    "error": RED,
}

STATUS_TEXT = {
    "on": "Ligado",
    "booting": "Inicializando",
    "starting": "Iniciando",
    "restarting": "Reiniciando",
    "stopping": "Desligando",
    "busy": "Ocupado",
    "off": "Desligado",
    "missing": "Não criado",
    "error": "Problema",
}

QSS = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#central {{ background: {BG}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; border-radius: 6px; }}

QLabel#title {{ font-size: 17pt; font-weight: 600; }}
QLabel#subtitle {{ color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ font-size: 11pt; font-weight: 600; padding-top: 6px; }}
QLabel#cardName {{ font-size: 12pt; font-weight: 600; }}
QLabel#badge {{ color: {MUTED}; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; padding: 1px 8px; font-size: 9pt; }}
QLabel#infoKey {{ color: {MUTED}; font-size: 9pt; }}
QLabel#infoVal {{ font-size: 9pt; }}

QFrame#panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#card:hover {{ background: {CARD_HOVER}; }}
QFrame#card[running="true"] {{ border: 1px solid #2f6b47; }}
QFrame#card[selected="true"] {{ border: 1px solid {ACCENT}; }}
QFrame#banner {{ border-radius: 10px; padding: 2px; }}
QFrame#banner[kind="warn"] {{ background: #3a2a0d; border: 1px solid #6b4b12; }}
QFrame#banner[kind="error"] {{ background: #3b1518; border: 1px solid #6e2228; }}
QFrame#banner[kind="info"] {{ background: #13233f; border: 1px solid #23417a; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: #202634; border-color: #3a4357; }}
QPushButton:pressed {{ background: #262d3d; }}
QPushButton:disabled {{ color: #565e6e; border-color: #222833; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #2a3a5e; border-color: #2a3a5e; color: #8c9ab8; }}
QPushButton#danger {{ background: #4a1d22; border: 1px solid #7a2a32; color: #ffd5d8; }}
QPushButton#danger:hover {{ background: #5c232a; }}

QToolButton#action {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 2px; color: {MUTED}; font-size: 8pt; }}
QToolButton#action:hover {{ background: #252c3a; border-color: {BORDER}; color: {TEXT}; }}
QToolButton#action:pressed {{ background: #2c3446; }}
QToolButton#action:disabled {{ color: #3e4555; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: #11151c; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 8px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: #5d6575; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: #24314d; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #4a5366; background: #11151c; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QCheckBox::indicator:disabled {{ background: #1a1e26; border-color: #2a303c; }}

QProgressBar {{ background: #11151c; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; height: 16px; font-size: 8pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QProgressBar#thin {{ height: 4px; max-height: 4px; border: none; background: #232a37; border-radius: 2px; }}
QProgressBar#thin::chunk {{ background: {AMBER}; border-radius: 2px; }}
QProgressBar#ram::chunk {{ background: {GREEN}; }}
QProgressBar#ram[level="warn"]::chunk {{ background: {AMBER}; }}
QProgressBar#ram[level="crit"]::chunk {{ background: {RED}; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QTableWidget, QListWidget, QTreeWidget {{ background: #11151c; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER}; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: #24314d; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3442; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4457; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QMessageBox {{ background: {SURFACE}; }}
QMessageBox QLabel {{ min-width: 320px; }}
"""
