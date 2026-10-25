"""Тёмная тема интерфейса."""

BG = "#14171c"
PANEL = "#1c2027"
BORDER = "#2a303a"
TEXT = "#e3e6eb"
MUTED = "#8b93a1"
ACCENT = "#3fb6a8"
GOOD = "#4cc38a"
WARN = "#e5a54b"
BAD = "#e5604b"
HASH_COLOR = "#3fb6a8"
TEMP_COLOR = "#e5a54b"
POWER_COLOR = "#7c8cf2"

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: {PANEL}; color: {MUTED}; padding: 8px 18px; border: 1px solid {BORDER};
               border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ color: {TEXT}; background: {BG}; }}
QFrame#card, QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QGroupBox {{ margin-top: 14px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#big {{ font-size: 22px; font-weight: 600; }}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: #0d1214; border: none; font-weight: 600; }}
QPushButton#danger {{ background: {BAD}; color: #fff; border: none; }}
QPushButton:disabled {{ color: {MUTED}; background: {BORDER}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTableWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QStatusBar {{ color: {MUTED}; }}
"""
