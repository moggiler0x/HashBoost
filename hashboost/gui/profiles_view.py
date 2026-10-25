"""Менеджер профилей: сохранённые пресеты и переключение алгоритма в один клик."""
from __future__ import annotations

import time

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..config import save_config
from ..core.runtime import Runtime
from ..hardware import GpuBackendError
from ..models import format_hashrate


class ProfilesView(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Алгоритм:"))
        self.algo = QComboBox()
        self.algo.setEditable(True)
        bar.addWidget(self.algo, 1)
        apply_btn = QPushButton("Применить профиль ко всем картам")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply)
        bar.addWidget(apply_btn)
        reset_btn = QPushButton("Сбросить на сток")
        reset_btn.clicked.connect(self._reset)
        bar.addWidget(reset_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 7)
        cur = runtime.cfg.currency
        self.table.setHorizontalHeaderLabels(["GPU", "Алгоритм", "Настройки", "Хешрейт", "Вт",
                                              f"Чистыми {cur}/сут", "Создан"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)

        del_btn = QPushButton("Удалить выбранный профиль")
        del_btn.clicked.connect(self._delete)
        lay.addWidget(del_btn)
        hint = QLabel("Карты без профиля для выбранного алгоритма работают на стоковых настройках.")
        hint.setObjectName("muted")
        lay.addWidget(hint)
        self.reload()

    def reload(self) -> None:
        algos = sorted(set(self.runtime.profiles.algorithms()) | set(self.runtime.cfg.algorithms))
        current = self.algo.currentText() or self.runtime.algorithm
        self.algo.clear()
        self.algo.addItems(algos)
        self.algo.setCurrentText(current)
        self._rows = sorted(self.runtime.profiles.all(), key=lambda p: (p.algorithm, p.gpu_name))
        self.table.setRowCount(len(self._rows))
        for row, p in enumerate(self._rows):
            cells = [p.gpu_name, p.algorithm, p.settings.describe(), format_hashrate(p.hashrate),
                     f"{p.power_w:.0f}", f"{p.net_per_day:.2f}", time.strftime("%d.%m.%Y %H:%M", time.localtime(p.created_at))]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _apply(self) -> None:
        algo = self.algo.currentText().strip()
        if not algo:
            return
        try:
            lines = self.runtime.apply_profiles(algo)
        except GpuBackendError as exc:
            QMessageBox.warning(self, "Профили", f"Не удалось применить: {exc}")
            return
        save_config(self.runtime.cfg)
        QMessageBox.information(self, "Профили", f"Алгоритм «{algo}»:\n" + "\n".join(lines) +
                                "\n\nНе забудьте переключить алгоритм в самом майнере, если он запущен не HashBoost.")

    def _reset(self) -> None:
        self.runtime.rig.reset_all()
        for gpu in self.runtime.rig.gpus:
            self.runtime.watchdog.mark_stable(gpu.index, gpu.settings)

    def _delete(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            p = self._rows[row]
            self.runtime.profiles.delete(p.gpu_uid, p.algorithm)
            self.reload()
