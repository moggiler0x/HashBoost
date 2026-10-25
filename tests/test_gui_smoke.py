"""Окно открывается в режиме симуляции (на всех ОС, включая macOS)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # нет системных библиотек Qt (например, libEGL)
    pytest.skip(f"Qt недоступен: {exc}", allow_module_level=True)

from hashboost.config import AppConfig
from hashboost.core.runtime import Runtime


def test_main_window_in_simulation():
    from hashboost.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    runtime = Runtime(AppConfig(simulate=True))
    try:
        window = MainWindow(runtime)
        runtime.poll_once()
        for i in range(window.tabs.count()):
            window.tabs.setCurrentIndex(i)
            window.refresh()
            app.processEvents()
        assert runtime.simulated
        assert len(window.dashboard.cards) == 4
        window.close()
    finally:
        runtime.shutdown()
