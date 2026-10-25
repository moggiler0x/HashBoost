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
        assert len(window.dashboard.cards) == 5

        calc = window.calculator
        calc.mode.setCurrentIndex(1)  # двухтарифный
        assert runtime.cfg.tariff_mode == "dual"
        assert runtime.cfg.effective_tariff() < runtime.cfg.tariff_day
        calc.refresh(runtime.poll_once())
        assert "Только ночью" in calc.night_only.text()
        assert calc.advice.item(0, 1).text() == "Pearl"  # RTX 4060
        assert calc.advice.item(2, 1).text() == "Quantus"  # GTX 1660 SUPER
        calc.advice.item(0, 5).setText("20000")
        assert runtime.cfg.card_prices[runtime.rig[0].info.uid] == 20000
        calc.preset.setCurrentIndex(2)
        assert runtime.cfg.tariff_day == 10.11
        assert window.lab.mode_box.count() == 2
        window.close()
    finally:
        runtime.shutdown()
