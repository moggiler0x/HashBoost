"""Экран Лаборатории (Auto-Tune Live): ход калибровки, кривая «хешрейт / ватт», лог шагов."""
from __future__ import annotations

import threading

import pyqtgraph as pg
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..core.autotune import PHASES, TuneCancelled, TuneFailed, TunerCallbacks, TuneResult
from ..core.runtime import Runtime
from ..models import BenchmarkSample, format_hashrate
from . import theme


class _Bridge(QObject):
    log = Signal(str)
    sample = Signal(object)
    phase = Signal(int, str)
    finished = Signal(object, str)  # TuneResult | None, сообщение об ошибке


class LabView(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        self.bridge = _Bridge()
        self.bridge.log.connect(self._on_log)
        self.bridge.sample.connect(self._on_sample)
        self.bridge.phase.connect(self._on_phase)
        self.bridge.finished.connect(self._on_finished)
        self._queue: list[int] = []
        self._thread: threading.Thread | None = None
        self.samples: list[BenchmarkSample] = []

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Карта:"))
        self.gpu_box = QComboBox()
        self.gpu_box.addItem("Все карты по очереди", -1)
        for gpu in runtime.rig.gpus:
            self.gpu_box.addItem(gpu.label, gpu.index)
        top.addWidget(self.gpu_box, 1)
        self.algo_label = QLabel()
        top.addWidget(self.algo_label)
        self.start_btn = QPushButton("Начать калибровку")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        lay.addLayout(top)

        status = QHBoxLayout()
        self.phase_label = QLabel("Ожидание")
        self.phase_label.setObjectName("title")
        self.progress = QProgressBar()
        self.progress.setRange(0, len(PHASES))
        self.progress.setFormat("%v / %m фаз")
        self.best_label = QLabel()
        self.best_label.setObjectName("muted")
        status.addWidget(self.phase_label)
        status.addWidget(self.progress, 1)
        lay.addLayout(status)
        lay.addWidget(self.best_label)

        plots = QHBoxLayout()
        curve_box = QGroupBox("Кривая «Хешрейт / Ватт»")
        cb = QVBoxLayout(curve_box)
        self.curve_plot = pg.PlotWidget(background=theme.PANEL)
        self.curve_plot.setLabel("bottom", "Мощность", units="W")
        self.curve_plot.setLabel("left", "Хешрейт", units="H/s")
        self.curve_plot.showGrid(x=True, y=True, alpha=0.15)
        self.scatter_ok = pg.ScatterPlotItem(size=9, brush=pg.mkBrush(theme.HASH_COLOR), pen=None)
        self.scatter_bad = pg.ScatterPlotItem(size=11, symbol="x", brush=pg.mkBrush(theme.BAD), pen=pg.mkPen(theme.BAD))
        self.scatter_best = pg.ScatterPlotItem(size=16, symbol="star", brush=pg.mkBrush(theme.WARN), pen=None)
        for item in (self.scatter_ok, self.scatter_bad, self.scatter_best):
            self.curve_plot.addItem(item)
        cb.addWidget(self.curve_plot)
        plots.addWidget(curve_box, 1)

        net_box = QGroupBox(f"Чистая прибыль по шагам, {runtime.cfg.currency}/сут")
        nb = QVBoxLayout(net_box)
        self.net_plot = pg.PlotWidget(background=theme.PANEL)
        self.net_plot.setLabel("bottom", "Шаг")
        self.net_plot.showGrid(x=True, y=True, alpha=0.15)
        self.net_curve = self.net_plot.plot(pen=pg.mkPen(theme.GOOD, width=2), symbol="o", symbolSize=6,
                                            symbolBrush=theme.GOOD)
        nb.addWidget(self.net_plot)
        plots.addWidget(net_box, 1)
        lay.addLayout(plots, 2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        self._update_algo()

    def _update_algo(self) -> None:
        cfg = self.runtime.cfg.tuning
        self.algo_label.setText(f"Алгоритм: {self.runtime.algorithm} · шаг {cfg.stabilization_s:.0f} с")

    # --- управление ---
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        choice = self.gpu_box.currentData()
        self._queue = [g.index for g in self.runtime.rig.gpus] if choice == -1 else [choice]
        self._update_algo()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.runtime.watchdog.paused = True
        self._next()

    def stop(self) -> None:
        self._queue = []
        if self.runtime.tuner:
            self.runtime.tuner.cancel()

    def _next(self) -> None:
        if not self._queue:
            self._done()
            return
        gpu = self._queue.pop(0)
        self.samples = []
        self._redraw()
        self.log.appendPlainText("")
        callbacks = TunerCallbacks(on_log=self.bridge.log.emit, on_sample=self.bridge.sample.emit,
                                   on_phase=self.bridge.phase.emit)
        tuner = self.runtime.make_tuner(callbacks)

        def work():
            try:
                self.bridge.finished.emit(tuner.run(gpu), "")
            except TuneCancelled:
                self.bridge.finished.emit(None, "Калибровка остановлена, настройки возвращены")
            except TuneFailed as exc:
                self.bridge.finished.emit(None, f"Калибровка прервана: {exc}")
            except Exception as exc:  # noqa: BLE001
                self.bridge.finished.emit(None, f"Ошибка: {exc}")

        self._thread = threading.Thread(target=work, name="hashboost-tune", daemon=True)
        self._thread.start()

    def _done(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.runtime.watchdog.paused = False
        self.phase_label.setText("Ожидание")

    # --- события тюнера (в GUI-потоке) ---
    def _on_log(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def _on_phase(self, idx: int, name: str) -> None:
        self.phase_label.setText(name)
        self.progress.setValue(idx)

    def _on_sample(self, sample: BenchmarkSample) -> None:
        self.samples.append(sample)
        self._redraw()

    def _redraw(self) -> None:
        ok = [s for s in self.samples if s.stable]
        bad = [s for s in self.samples if not s.stable and s.power_w > 0]
        self.scatter_ok.setData([s.power_w for s in ok], [s.hashrate for s in ok])
        self.scatter_bad.setData([s.power_w for s in bad], [s.hashrate for s in bad])
        best = max(ok, key=lambda s: s.net_per_day, default=None)
        self.scatter_best.setData([best.power_w] if best else [], [best.hashrate] if best else [])
        self.net_curve.setData(list(range(1, len(ok) + 1)), [s.net_per_day for s in ok])
        if best:
            cur = self.runtime.cfg.currency
            self.best_label.setText(f"Лучшая точка: {best.settings.describe()} — {format_hashrate(best.hashrate)}, "
                                    f"{best.power_w:.0f} Вт, {best.net_per_day:.2f} {cur}/сут")
        else:
            self.best_label.setText("")

    def _on_finished(self, result: TuneResult | None, error: str) -> None:
        if result is not None:
            self.progress.setValue(len(PHASES))
            profile = self.runtime.save_tune_result(result)
            cur = self.runtime.cfg.currency
            self.log.appendPlainText(f"Профиль сохранён: {profile.gpu_name} / {profile.algorithm} "
                                     f"({result.gain_per_day:+.2f} {cur}/сут к стоку)")
        else:
            self.log.appendPlainText(error)
            if "остановлена" not in error:
                QMessageBox.warning(self, "Калибровка", error)
        self._next()
