"""Тёмная тема интерфейса: палитра, таблица стилей, иконки и оформление графиков."""
from __future__ import annotations

# --- палитра ---
BG = "#0e1116"          # фон окна
SIDEBAR = "#0a0d11"     # боковое меню
PANEL = "#151a21"       # карточки
PANEL_2 = "#1b212a"     # поля ввода, наведение
BORDER = "#232a35"
BORDER_STRONG = "#2f3846"
TEXT = "#e8ecf2"
MUTED = "#8a94a6"
FAINT = "#5b6577"
ACCENT = "#2ed3a2"
ACCENT_DARK = "#0b1f19"
GOOD = "#34d399"
WARN = "#f5b544"
BAD = "#f26d5b"
INFO = "#7aa2ff"
HASH_COLOR = ACCENT
TEMP_COLOR = WARN
POWER_COLOR = "#8b9cff"
NVIDIA_COLOR = "#76b900"
AMD_COLOR = "#ff4d4d"

FONT_FAMILIES = ["Inter", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Roboto", "Arial"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono"]
MONO_CSS = ", ".join(f'"{f}"' for f in MONO_FAMILIES) + ", monospace"


def rgba(hex_color: str, alpha: float) -> str:
    """Цвет из палитры с прозрачностью — для полупрозрачных подложек."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {int(alpha * 255)})"


def temp_color(value: float | None, limit: float) -> str:
    """Цвет температуры относительно предела watchdog."""
    if value is None:
        return TEXT
    if value >= limit:
        return BAD
    if value >= limit - 8:
        return WARN
    return TEXT


def money_color(value: float) -> str:
    return GOOD if value >= 0 else BAD


STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px;
            border-radius: 6px; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 11px; }}
QLabel#big {{ font-size: 22px; font-weight: 600; }}
QLabel#pageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {MUTED}; font-size: 13px; }}
QLabel#caption {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.6px; }}
QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; }}

/* боковое меню */
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QFrame#sidebar QWidget {{ background: transparent; }}
QLabel#logo {{ font-size: 17px; font-weight: 700; }}
QPushButton#nav {{ background: transparent; border: none; border-radius: 8px; color: {MUTED};
                   text-align: left; padding: 10px 12px; font-size: 13px; font-weight: 500; }}
QPushButton#nav:hover {{ background: {PANEL}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {rgba(ACCENT, 0.12)}; color: {ACCENT}; font-weight: 600; }}
QFrame#sideStat {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}

/* карточки */
QFrame#card, QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#card QWidget, QGroupBox QWidget {{ background: transparent; }}
QFrame#card QLineEdit, QFrame#card QComboBox, QFrame#card QSpinBox, QFrame#card QDoubleSpinBox,
QFrame#card QPlainTextEdit, QGroupBox QLineEdit, QGroupBox QComboBox, QGroupBox QSpinBox,
QGroupBox QDoubleSpinBox {{ background: {PANEL_2}; }}
QFrame#tile {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#tile QWidget {{ background: transparent; }}
QFrame#tileAccent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {rgba(ACCENT, 0.16)},
                     stop:1 {rgba(ACCENT, 0.03)}); border: 1px solid {rgba(ACCENT, 0.45)}; border-radius: 12px; }}
QFrame#tileAccent QWidget {{ background: transparent; }}
QGroupBox {{ margin-top: 0px; padding: 40px 14px 14px 14px; font-size: 14px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: 16px; top: 14px;
                    color: {TEXT}; }}
QGroupBox QLabel {{ font-weight: 400; font-size: 13px; }}
QFrame#divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

/* кнопки */
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 8px 16px;
               font-weight: 500; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_DARK}; border: 1px solid {ACCENT}; font-weight: 700; }}
QPushButton#primary:hover {{ background: #4fe0b5; }}
QPushButton#danger {{ background: {rgba(BAD, 0.14)}; color: {BAD}; border: 1px solid {rgba(BAD, 0.5)};
                      font-weight: 600; }}
QPushButton#danger:hover {{ background: {rgba(BAD, 0.24)}; }}
QPushButton:disabled, QPushButton#primary:disabled, QPushButton#danger:disabled {{
    color: {FAINT}; background: {PANEL_2}; border-color: {BORDER}; }}

/* поля ввода */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {PANEL_2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 10px;
    min-height: 20px; selection-background-color: {rgba(ACCENT, 0.35)}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {FAINT}; }}
QAbstractSpinBox {{ padding-right: 10px; min-height: 17px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
                               padding: 4px; selection-background-color: {rgba(ACCENT, 0.18)};
                               selection-color: {TEXT}; outline: none; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER_STRONG};
                        background: {PANEL_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* журналы и таблицы */
QPlainTextEdit {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px;
                  font-family: {MONO_CSS}; font-size: 12px; color: {MUTED};
                  selection-background-color: {rgba(ACCENT, 0.3)}; }}
QFrame#card QPlainTextEdit {{ background: transparent; border: none; padding: 0px; }}
QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent;
                alternate-background-color: {PANEL_2}; selection-background-color: {rgba(ACCENT, 0.16)};
                selection-color: {TEXT}; outline: none; }}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {BORDER}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER_STRONG};
                        padding: 8px; font-size: 11px; font-weight: 600; }}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}

/* прогресс и прокрутка */
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 #5fe7ff);
                       border-radius: 3px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {SIDEBAR}; color: {FAINT}; border-top: 1px solid {BORDER}; font-size: 11px; }}
QStatusBar QLabel {{ color: {FAINT}; font-size: 11px; padding: 0 8px; }}
QMessageBox {{ background: {PANEL}; }}
"""


def arrow_rules(cache_dir) -> str:
    """Стрелка выпадающего списка: QSS принимает картинку только файлом, поэтому SVG кладётся в кэш."""
    from pathlib import Path

    path = Path(cache_dir) / "chevron.svg"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(icon_svg("chevron", MUTED, 2.2))
    except OSError:
        return ""
    return (f"QComboBox::down-arrow {{ image: url(\"{path.as_posix()}\"); width: 12px; height: 12px; }}"
            f"QComboBox::down-arrow:on {{ top: 1px; }}")


def pill_style(color: str) -> str:
    """Стиль «таблетки»-статуса заданного цвета."""
    return (f"background: {rgba(color, 0.14)}; color: {color}; border: 1px solid {rgba(color, 0.35)};"
            f"border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;")


# --- иконки бокового меню (SVG, 24×24, обводка) ---
_ICON_PATHS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "calculator": '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
    "lab": '<path d="M9 3h6"/><path d="M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/>'
           '<path d="M7.5 15h9"/>',
    "profiles": '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
    "settings": '<path d="M4 6h10"/><path d="M18 6h2"/><circle cx="16" cy="6" r="2"/><path d="M4 12h4"/>'
                '<path d="M12 12h8"/><circle cx="10" cy="12" r="2"/><path d="M4 18h12"/><path d="M20 18h0"/>'
                '<circle cx="18" cy="18" r="2"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "logo": '<path d="M12 2 3 7v10l9 5 9-5V7l-9-5z"/><path d="M13 7 9 13h3l-1 4 4-6h-3l1-4z"/>',
}


def icon_svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    body = _ICON_PATHS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def icon(name: str, color: str = MUTED, active: str = ACCENT, size: int = 18):
    """QIcon с обычным и активным (checked) состоянием."""
    from PySide6.QtCore import QByteArray, QSize
    from PySide6.QtGui import QIcon, QPixmap

    result = QIcon()
    for col, state in ((color, QIcon.Off), (active, QIcon.On)):
        pix = QPixmap()
        pix.loadFromData(QByteArray(icon_svg(name, col)), "SVG")
        if not pix.isNull():
            result.addPixmap(pix.scaled(QSize(size * 2, size * 2)), QIcon.Normal, state)
    return result


# --- графики pyqtgraph ---
def style_plot(plot, *, axes: bool = True) -> None:
    """Единый вид графика: прозрачный фон, приглушённые оси и сетка."""
    import pyqtgraph as pg

    plot.setBackground(None)
    plot.setMouseEnabled(False, False)
    plot.hideButtons()
    plot.setMenuEnabled(False)
    item = plot.getPlotItem()
    if not axes:
        for side in ("left", "bottom", "right", "top"):
            item.hideAxis(side)
        item.getViewBox().setDefaultPadding(0.02)
        return
    for side in ("left", "bottom"):
        axis = item.getAxis(side)
        axis.setPen(pg.mkPen(BORDER_STRONG))
        axis.setTextPen(pg.mkPen(MUTED))
        axis.setStyle(tickLength=-4)
    plot.showGrid(x=True, y=True, alpha=0.08)


def fill_brush(color: str, alpha: float = 0.28):
    """Вертикальный градиент под кривой (сверху цвет, снизу прозрачно)."""
    from PySide6.QtGui import QBrush, QColor, QGradient, QLinearGradient

    grad = QLinearGradient(0, 0, 0, 1)
    grad.setCoordinateMode(QGradient.ObjectMode)
    top = QColor(color)
    top.setAlphaF(alpha)
    bottom = QColor(color)
    bottom.setAlphaF(0.0)
    grad.setColorAt(0, top)
    grad.setColorAt(1, bottom)
    return QBrush(grad)
