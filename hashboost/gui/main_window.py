"""Главное окно: боковое меню и экраны."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core.runtime import Runtime
from ..models import format_hashrate
from . import theme
from .calculator import Calculator
from .dashboard import Dashboard
from .lab import LabView
from .profiles_view import ProfilesView
from .settings_view import SettingsView
from .widgets import Pill, page

PAGES = [  # иконка, пункт меню, заголовок экрана, подзаголовок
    ("dashboard", "Дашборд", "Дашборд рига", "Хешрейт, температуры и прибыль каждой карты в реальном времени"),
    ("calculator", "Калькулятор розетки", "Калькулятор розетки",
     "Тариф, доходность монеты и чистая прибыль с учётом электричества"),
    ("lab", "Лаборатория", "Лаборатория Auto-Tune", "Подбор частот и напряжения под максимум прибыли на ватт"),
    ("profiles", "Профили", "Менеджер профилей", "Сохранённые пресеты карт под разные алгоритмы"),
    ("settings", "Настройки", "Настройки", "Майнер, шаги калибровки и пороги защиты"),
]


class Sidebar(QFrame):
    def __init__(self, simulated: bool):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 20, 14, 16)
        lay.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(theme.icon("logo", theme.ACCENT, theme.ACCENT, 26).pixmap(26, 26))
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f"background: {theme.rgba(theme.ACCENT, 0.12)}; border-radius: 10px;")
        name = QVBoxLayout()
        name.setSpacing(0)
        logo = QLabel("HashBoost")
        logo.setObjectName("logo")
        ver = QLabel(f"v{__version__} · Smart Auto-Tune")
        ver.setObjectName("faint")
        name.addWidget(logo)
        name.addWidget(ver)
        brand.addWidget(mark)
        brand.addLayout(name)
        brand.addStretch()
        lay.addLayout(brand)
        lay.addSpacing(22)

        menu = QLabel("МЕНЮ")
        menu.setObjectName("caption")
        menu.setContentsMargins(12, 0, 0, 6)
        lay.addWidget(menu)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for i, (icon_name, label, _, _) in enumerate(PAGES):
            btn = QPushButton(label)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(theme.icon(icon_name))
            btn.setIconSize(QSize(18, 18))
            self.group.addButton(btn, i)
            self.buttons.append(btn)
            lay.addWidget(btn)
        self.buttons[0].setChecked(True)
        lay.addStretch()

        stat = QFrame()
        stat.setObjectName("sideStat")
        s = QVBoxLayout(stat)
        s.setContentsMargins(14, 12, 14, 12)
        s.setSpacing(2)
        cap = QLabel("ЧИСТЫМИ В СУТКИ")
        cap.setObjectName("caption")
        self.net = QLabel("—")
        self.net.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.rig = QLabel("")
        self.rig.setObjectName("faint")
        s.addWidget(cap)
        s.addWidget(self.net)
        s.addWidget(self.rig)
        lay.addWidget(stat)
        lay.addSpacing(10)
        self.mode = Pill("● СИМУЛЯЦИЯ" if simulated else "● РЕАЛЬНЫЕ КАРТЫ",
                         theme.WARN if simulated else theme.GOOD)
        self.mode.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mode)


class MainWindow(QMainWindow):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        self.setWindowTitle(f"HashBoost {__version__}")
        self.resize(1440, 920)
        self.setMinimumSize(1100, 720)

        self.dashboard = Dashboard(runtime)
        self.calculator = Calculator(runtime)
        self.lab = LabView(runtime)
        self.profiles = ProfilesView(runtime)
        self.settings = SettingsView(runtime)

        self.miner_pill = Pill()
        self.sidebar = Sidebar(runtime.simulated)
        self.tabs = QStackedWidget()  # имя сохранено: экраны переключаются как вкладки
        for widget, (_, _, title, subtitle) in zip(
                (self.dashboard, self.calculator, self.lab, self.profiles, self.settings), PAGES):
            extra = self.miner_pill if widget is self.dashboard else None
            self.tabs.addWidget(page(widget, title, subtitle, extra))
        self.sidebar.group.idClicked.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self._tab_changed)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        mode = "Симуляция — реальные карты не затрагиваются" if runtime.simulated else \
            "Драйверы: " + ", ".join(b.name for b in runtime.rig.backends)
        self.mode_label = QLabel(mode)
        self.statusBar().addPermanentWidget(self.mode_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def _page(self, idx: int) -> QWidget:
        return (self.dashboard, self.calculator, self.lab, self.profiles, self.settings)[idx]

    def _tab_changed(self, idx: int) -> None:
        button = self.sidebar.group.button(idx)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        if self._page(idx) is self.profiles:
            self.profiles.reload()

    def refresh(self) -> None:
        snap = self.runtime.latest()
        if snap.timestamp == 0:
            return
        current = self._page(self.tabs.currentIndex())
        if current is self.dashboard:
            self.dashboard.refresh(snap)
        elif current is self.calculator:
            self.calculator.refresh(snap)
        if snap.miner_online:
            self.miner_pill.set(f"● {snap.algorithm} · майнер онлайн", theme.GOOD)
        else:
            self.miner_pill.set("● майнер не отвечает", theme.BAD)
        if snap.total:
            net = snap.total.net_per_day
            self.sidebar.net.setText(f"{net:+.2f} {self.runtime.cfg.currency}")
            self.sidebar.net.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {theme.money_color(net)};")
            total_hash = sum(g.miner.hashrate for g in snap.gpus.values() if g.miner)
            self.sidebar.rig.setText(f"{len(snap.gpus)} GPU · {format_hashrate(total_hash)} · "
                                     f"{snap.total.wall_power_w:.0f} Вт")
        msg = snap.miner_error or f"Майнер: {snap.algorithm}, карт: {len(snap.gpus)}"
        self.statusBar().showMessage(msg)

    def closeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.lab.stop()
        self.timer.stop()
        super().closeEvent(event)


def setup_app(app: QApplication) -> None:
    """Шрифт, таблица стилей и настройки графиков для всего приложения."""
    import pyqtgraph as pg

    font = QFont()
    font.setFamilies(theme.FONT_FAMILIES)
    font.setPointSizeF(10)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    from ..config import data_dir

    app.setStyleSheet(theme.STYLESHEET + theme.arrow_rules(data_dir() / "ui"))
    pg.setConfigOptions(antialias=True, foreground=theme.MUTED, background=theme.PANEL)


def run_gui(runtime: Runtime) -> int:
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("HashBoost")
    setup_app(app)
    window = MainWindow(runtime)
    window.show()
    runtime.start()
    try:
        return app.exec()
    finally:
        runtime.shutdown()
