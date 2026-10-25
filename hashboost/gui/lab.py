"""Экран Лаборатории (Auto-Tune Live): ход калибровки, кривая «хешрейт / ватт», лог шагов."""
from __future__ import annotations

import html
import threading

import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..core.autotune import PHASES, TuneCancelled, TuneFailed, TunerCallbacks, TuneResult
from ..core.runtime import Runtime
from ..models import BenchmarkSample, format_hashrate
from . import theme
from .widgets import Pill, StatTile


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
        lay.setSpacing(14)

        control = QFrame()
        control.setObjectName("card")
        top = QHBoxLayout(control)
        top.setContentsMargins(16, 12, 16, 12)
        top.setSpacing(10)
        card_cap = QLabel("Карта")
        card_cap.setObjectName("muted")
        top.addWidget(card_cap)
        self.gpu_box = QComboBox()
        self.gpu_box.addItem("Все карты по очереди", -1)
        for gpu in runtime.rig.gpus:
            self.gpu_box.addItem(gpu.label, gpu.index)
        self.gpu_box.setMinimumWidth(280)
        top.addWidget(self.gpu_box)
        self.algo_label = Pill()
        top.addWidget(self.algo_label)
        top.addStretch()
        self.start_btn = QPushButton("▶  Начать калибровку")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("■  Остановить")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        lay.addWidget(control)

        status = QFrame()
        status.setObjectName("card")
        st = QVBoxLayout(status)
        st.setContentsMargins(16, 14, 16, 14)
        st.setSpacing(10)
        head = QHBoxLayout()
        self.gpu_label = QLabel("")
        self.gpu_label.setObjectName("muted")
        self.phase_label = QLabel("Ожидание")
        self.phase_label.setObjectName("sectionTitle")
        head.addWidget(self.phase_label)
        head.addStretch()
        head.addWidget(self.gpu_label)
        st.addLayout(head)
        steps = QHBoxLayout()
        steps.setSpacing(8)
        self.steps: list[QLabel] = []
        for i, name in enumerate(PHASES):
            step = QLabel(f"{i + 1}  {name}")
            step.setAlignment(Qt.AlignCenter)
            self.steps.append(step)
            steps.addWidget(step, 1)
        st.addLayout(steps)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(PHASES))
        self.progress.setTextVisible(False)
        st.addWidget(self.progress)
        lay.addWidget(status)
        self._set_step(-1)

        cur = runtime.cfg.currency
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_hash = StatTile("лучший хешрейт", value_size=20)
        self.t_power = StatTile("мощность", value_size=20)
        self.t_eff = StatTile("эффективность", value_size=20)
        self.t_net = StatTile(f"чистыми, {cur}/сут", accent=True, value_size=20)
        for w in (self.t_hash, self.t_power, self.t_eff, self.t_net):
            tiles.addWidget(w, 1)
        lay.addLayout(tiles)
        self.best_label = QLabel()
        self.best_label.setObjectName("muted")
        lay.addWidget(self.best_label)

        plots = QHBoxLayout()
        plots.setSpacing(14)
        curve_box = QGroupBox("Кривая «Хешрейт / Ватт»")
        cb = QVBoxLayout(curve_box)
        self.curve_plot = pg.PlotWidget()
        theme.style_plot(self.curve_plot)
        self.curve_plot.setLabel("bottom", "Мощность", units="W")
        self.curve_plot.setLabel("left", "Хешрейт", units="H/s")
        self.scatter_ok = pg.ScatterPlotItem(size=9, brush=pg.mkBrush(theme.HASH_COLOR + "d9"),
                                             pen=pg.mkPen(theme.HASH_COLOR))
        self.scatter_bad = pg.ScatterPlotItem(size=11, symbol="x", brush=pg.mkBrush(theme.BAD), pen=pg.mkPen(theme.BAD))
        self.scatter_best = pg.ScatterPlotItem(size=20, symbol="star", brush=pg.mkBrush(theme.WARN),
                                               pen=pg.mkPen(theme.BG, width=1))
        for item in (self.scatter_ok, self.scatter_bad, self.scatter_best):
            self.curve_plot.addItem(item)
        cb.addWidget(self.curve_plot)
        legend = QLabel(f"<span style='color:{theme.HASH_COLOR}'>●</span> стабильно&nbsp;&nbsp;&nbsp;"
                        f"<span style='color:{theme.BAD}'>✕</span> нестабильно&nbsp;&nbsp;&nbsp;"
                        f"<span style='color:{theme.WARN}'>★</span> лучшая точка")
        legend.setObjectName("faint")
        cb.addWidget(legend)
        plots.addWidget(curve_box, 1)

        net_box = QGroupBox(f"Чистая прибыль по шагам, {cur}/сут")
        nb = QVBoxLayout(net_box)
        self.net_plot = pg.PlotWidget()
        theme.style_plot(self.net_plot)
        self.net_plot.setLabel("bottom", "Шаг")
        self.net_curve = self.net_plot.plot(pen=pg.mkPen(theme.GOOD, width=2), symbol="o", symbolSize=6,
                                            symbolBrush=theme.GOOD, symbolPen=None)
        self.net_curve.setBrush(theme.fill_brush(theme.GOOD, 0.22))
        nb.addWidget(self.net_plot)
        plots.addWidget(net_box, 1)
        lay.addLayout(plots, 3)

        log_box = QGroupBox("Журнал шагов")
        lb = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lb.addWidget(self.log)
        lay.addWidget(log_box, 2)
        self._update_algo()
        self._redraw()

    def _update_algo(self) -> None:
        cfg = self.runtime.cfg.tuning
        self.algo_label.set(f"{self.runtime.algorithm} · шаг {cfg.stabilization_s:.0f} с", theme.INFO)

    def _set_step(self, current: int) -> None:
        """Подсветка фаз калибровки: пройденные, текущая, ожидающие."""
        for i, step in enumerate(self.steps):
            if i < current:
                color, bg, border = theme.GOOD, theme.rgba(theme.GOOD, 0.08), theme.rgba(theme.GOOD, 0.3)
            elif i == current:
                color, bg, border = theme.ACCENT, theme.rgba(theme.ACCENT, 0.16), theme.ACCENT
            else:
                color, bg, border = theme.FAINT, "transparent", theme.BORDER_STRONG
            step.setStyleSheet(f"color: {color}; background: {bg}; border: 1px solid {border}; border-radius: 8px;"
                               f"padding: 7px 4px; font-size: 12px; font-weight: 600;")

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
        self.gpu_label.setText(self.runtime.rig[gpu].label)
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
        self.gpu_label.setText("")
        self._set_step(-1)

    # --- события тюнера (в GUI-потоке) ---
    def _on_log(self, msg: str) -> None:
        if msg.startswith("==="):
            color, weight = theme.ACCENT, 700
        elif "НЕСТАБИЛЬНО" in msg or msg.startswith("Откат") or "ошибк" in msg.lower():
            color, weight = theme.BAD, 400
        elif msg.startswith(("Готово", "Профиль сохранён", "Порог")):
            color, weight = theme.GOOD, 600
        elif msg.startswith("Калибровка"):
            color, weight = theme.TEXT, 700
        else:
            color, weight = theme.MUTED, 400
        self.log.appendHtml(f"<span style='color:{color}; font-weight:{weight}'>{html.escape(msg)}</span>")

    def _on_phase(self, idx: int, name: str) -> None:
        self.phase_label.setText(name)
        self.progress.setValue(idx)
        self._set_step(idx)

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
        nets = [s.net_per_day for s in ok]
        self.net_curve.setFillLevel(min(nets) if nets else 0)
        self.net_curve.setData(list(range(1, len(ok) + 1)), nets)
        if best:
            self.best_label.setText(f"Лучшая точка: {best.settings.describe()}")
            self.t_hash.set(format_hashrate(best.hashrate))
            self.t_power.set(f"{best.power_w:.0f} Вт")
            self.t_eff.set(format_hashrate(best.hashrate / best.power_w, "H/Вт") if best.power_w else "—")
            self.t_net.set(f"{best.net_per_day:+.2f}", theme.money_color(best.net_per_day))
        else:
            self.best_label.setText("Лучшая точка появится после первого стабильного замера")
            for tile in (self.t_hash, self.t_power, self.t_eff, self.t_net):
                tile.set("—")

    def _on_finished(self, result: TuneResult | None, error: str) -> None:
        if result is not None:
            self.progress.setValue(len(PHASES))
            self._set_step(len(PHASES))
            profile = self.runtime.save_tune_result(result)
            cur = self.runtime.cfg.currency
            self.log.appendPlainText(f"Профиль сохранён: {profile.gpu_name} / {profile.algorithm} "
                                     f"({result.gain_per_day:+.2f} {cur}/сут к стоку)")
        else:
            self.log.appendPlainText(error)
            if "остановлена" not in error:
                QMessageBox.warning(self, "Калибровка", error)
        self._next()
