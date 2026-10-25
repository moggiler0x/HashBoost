"""Главный дашборд: карточки GPU с графиками и итог по ригу."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core.runtime import GpuSnapshot, Runtime, Snapshot
from ..core.watchdog import Severity
from ..hardware import GpuHandle
from ..models import format_hashrate
from . import theme


def _fmt(value, suffix: str, digits: int = 0) -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


class Metric(QWidget):
    def __init__(self, caption: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 15px; font-weight: 600;")
        cap = QLabel(caption)
        cap.setObjectName("muted")
        cap.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.value)
        lay.addWidget(cap)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color or theme.TEXT};")


class GpuCard(QFrame):
    def __init__(self, gpu: GpuHandle, currency: str):
        super().__init__()
        self.setObjectName("card")
        self.gpu = gpu
        self.currency = currency
        lay = QVBoxLayout(self)

        head = QHBoxLayout()
        title = QLabel(gpu.label)
        title.setObjectName("title")
        self.status = QLabel("●")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.status)
        lay.addLayout(head)
        self.settings_label = QLabel()
        self.settings_label.setObjectName("muted")
        lay.addWidget(self.settings_label)

        grid = QGridLayout()
        self.m_hash = Metric("хешрейт")
        self.m_power = Metric("мощность")
        self.m_eff = Metric("эффективность")
        self.m_net = Metric(f"чистыми, {currency}/сут")
        self.m_temp = Metric("GPU / HotSpot")
        self.m_vram = Metric("VRAM")
        self.m_fan = Metric("кулер")
        self.m_shares = Metric("шары ✓ / ✗ / ошибки")
        for i, m in enumerate([self.m_hash, self.m_power, self.m_eff, self.m_net,
                               self.m_temp, self.m_vram, self.m_fan, self.m_shares]):
            grid.addWidget(m, i // 4, i % 4)
        lay.addLayout(grid)

        self.plot_hash = self._small_plot()
        self.plot_env = self._small_plot()
        self.curve_hash = self.plot_hash.plot(pen=pg.mkPen(theme.HASH_COLOR, width=2))
        self.curve_temp = self.plot_env.plot(pen=pg.mkPen(theme.TEMP_COLOR, width=1.5))
        self.curve_power = self.plot_env.plot(pen=pg.mkPen(theme.POWER_COLOR, width=1.5))
        lay.addWidget(self.plot_hash)
        lay.addWidget(self.plot_env)
        legend = QLabel(f"<span style='color:{theme.HASH_COLOR}'>━ хешрейт</span>  "
                        f"<span style='color:{theme.TEMP_COLOR}'>━ °C</span>  "
                        f"<span style='color:{theme.POWER_COLOR}'>━ Вт</span>")
        legend.setObjectName("muted")
        lay.addWidget(legend)

    @staticmethod
    def _small_plot() -> pg.PlotWidget:
        plot = pg.PlotWidget(background=theme.PANEL)
        plot.setFixedHeight(70)
        plot.hideAxis("bottom")
        plot.getAxis("left").setTextPen(theme.MUTED)
        plot.getAxis("left").setWidth(42)
        plot.setMouseEnabled(False, False)
        plot.hideButtons()
        plot.showGrid(y=True, alpha=0.15)
        return plot

    def update_data(self, snap: GpuSnapshot | None, history, severity: Severity) -> None:
        self.settings_label.setText("Настройки: " + self.gpu.settings.describe())
        color = {Severity.OK: theme.GOOD, Severity.WARN: theme.WARN}.get(severity, theme.BAD)
        self.status.setStyleSheet(f"color: {color}; font-size: 16px;")
        if snap is None:
            return
        t, m, p = snap.telemetry, snap.miner, snap.profit
        if snap.error:
            self.status.setToolTip(snap.error)
            self.status.setStyleSheet(f"color: {theme.BAD}; font-size: 16px;")
        self.m_hash.set(format_hashrate(m.hashrate) if m else "—")
        self.m_power.set(_fmt(t.power_w if t else None, " Вт"))
        if m and t and t.power_w:
            self.m_eff.set(format_hashrate(m.hashrate / t.power_w, "H/Вт"))
        if p:
            self.m_net.set(f"{p.net_per_day:.2f}", theme.GOOD if p.net_per_day >= 0 else theme.BAD)
        if t:
            self.m_temp.set(f"{_fmt(t.gpu_temp_c, '°')} / {_fmt(t.hotspot_temp_c, '°')}")
            self.m_vram.set(_fmt(t.vram_temp_c, "°C"))
            self.m_fan.set(_fmt(t.fan_percent, " %"))
        if m:
            self.m_shares.set(f"{m.accepted} / {m.rejected + m.stale} / {m.invalid}",
                              theme.BAD if m.invalid else None)
        history = list(history or [])  # копия: история дописывается из потока опроса
        if history:
            xs = [h[0] for h in history]
            hashes = [h[1] for h in history]
            self.curve_hash.setData(xs, hashes)
            self.plot_hash.setYRange(0, max(max(hashes), 1.0) * 1.15, padding=0)
            self.curve_temp.setData(xs, [h[2] for h in history])
            self.curve_power.setData(xs, [h[3] for h in history])


class Dashboard(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        cur = runtime.cfg.currency
        lay = QVBoxLayout(self)

        summary = QFrame()
        summary.setObjectName("card")
        s_lay = QHBoxLayout(summary)
        self.s_hash = Metric("общий хешрейт")
        self.s_power = Metric("из розетки")
        self.s_gross = Metric(f"доход, {cur}/сут")
        self.s_cost = Metric(f"свет, {cur}/сут")
        self.s_net = Metric(f"чистыми, {cur}/сут")
        self.s_miner = Metric("майнер")
        for w in (self.s_hash, self.s_power, self.s_gross, self.s_cost, self.s_net, self.s_miner):
            s_lay.addWidget(w)
        lay.addWidget(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        grid = QGridLayout(holder)
        self.cards: list[GpuCard] = []
        for i, gpu in enumerate(runtime.rig.gpus):
            card = GpuCard(gpu, cur)
            self.cards.append(card)
            grid.addWidget(card, i // 2, i % 2)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setMaximumHeight(110)
        self.events.setPlaceholderText("События watchdog появятся здесь")
        lay.addWidget(self.events)
        self._shown_events = 0

    def refresh(self, snap: Snapshot) -> None:
        total_hash = sum(g.miner.hashrate for g in snap.gpus.values() if g.miner)
        self.s_hash.set(format_hashrate(total_hash))
        if snap.total:
            self.s_power.set(f"{snap.total.wall_power_w:.0f} Вт")
            self.s_gross.set(f"{snap.total.revenue_per_day:.2f}")
            self.s_cost.set(f"{snap.total.cost_per_day:.2f}")
            net = snap.total.net_per_day
            self.s_net.set(f"{net:.2f}", theme.GOOD if net >= 0 else theme.BAD)
        self.s_miner.set(snap.algorithm + (" ✓" if snap.miner_online else " ✗"),
                         theme.GOOD if snap.miner_online else theme.BAD)
        for card in self.cards:
            idx = card.gpu.index
            sev = snap.health.worst(idx) if snap.health else Severity.OK
            card.update_data(snap.gpus.get(idx), self.runtime.history.get(idx), sev)
        fresh = self.runtime.event_count - self._shown_events
        if fresh > 0:
            for msg in list(self.runtime.events)[-fresh:]:
                self.events.appendPlainText(msg)
            self._shown_events = self.runtime.event_count
