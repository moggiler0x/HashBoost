"""Главное окно."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QTabWidget

from .. import __version__
from ..core.runtime import Runtime
from . import theme
from .calculator import Calculator
from .dashboard import Dashboard
from .lab import LabView
from .profiles_view import ProfilesView
from .settings_view import SettingsView


class MainWindow(QMainWindow):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        self.setWindowTitle(f"HashBoost {__version__}")
        self.resize(1360, 900)

        self.tabs = QTabWidget()
        self.dashboard = Dashboard(runtime)
        self.calculator = Calculator(runtime)
        self.lab = LabView(runtime)
        self.profiles = ProfilesView(runtime)
        self.settings = SettingsView(runtime)
        self.tabs.addTab(self.dashboard, "Дашборд")
        self.tabs.addTab(self.calculator, "Калькулятор розетки")
        self.tabs.addTab(self.lab, "Лаборатория")
        self.tabs.addTab(self.profiles, "Профили")
        self.tabs.addTab(self.settings, "Настройки")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        mode = "СИМУЛЯЦИЯ — реальные карты не затрагиваются" if runtime.simulated else \
            "Драйверы: " + ", ".join(b.name for b in runtime.rig.backends)
        self.mode_label = QLabel(mode)
        self.statusBar().addPermanentWidget(self.mode_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is self.profiles:
            self.profiles.reload()

    def refresh(self) -> None:
        snap = self.runtime.latest()
        if snap.timestamp == 0:
            return
        current = self.tabs.currentWidget()
        if current is self.dashboard:
            self.dashboard.refresh(snap)
        elif current is self.calculator:
            self.calculator.refresh(snap)
        msg = snap.miner_error or f"Майнер: {snap.algorithm}, карт: {len(snap.gpus)}"
        self.statusBar().showMessage(msg)

    def closeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.lab.stop()
        self.timer.stop()
        super().closeEvent(event)


def run_gui(runtime: Runtime) -> int:
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("HashBoost")
    app.setStyleSheet(theme.STYLESHEET)
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, foreground=theme.MUTED)
    window = MainWindow(runtime)
    window.show()
    runtime.start()
    try:
        return app.exec()
    finally:
        runtime.shutdown()
