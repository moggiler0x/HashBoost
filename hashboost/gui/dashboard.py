"""Главный дашборд: карточки GPU с графиками и итог по ригу."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from ..config import WatchdogConfig
from ..core.runtime import GpuSnapshot, Runtime, Snapshot
from ..core.watchdog import Severity
from ..hardware import GpuHandle
from ..models import Vendor, format_hashrate
from . import theme
from .widgets import Metric, Pill, Sparkline, StatTile, divider

STATUS = {Severity.OK: ("● Норма", theme.GOOD), Severity.WARN: ("● Внимание", theme.WARN)}


def _fmt(value, suffix: str, digits: int = 0) -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def _vendor(gpu: GpuHandle) -> tuple[str, str]:
    name = gpu.info.name.upper()
    if gpu.info.vendor == Vendor.AMD or "AMD" in name or "RADEON" in name:
        return "AMD", theme.AMD_COLOR
    if gpu.info.vendor == Vendor.NVIDIA or "NVIDIA" in name:
        return "NVIDIA", theme.NVIDIA_COLOR
    return "GPU", theme.MUTED


def _short_name(name: str) -> str:
    for prefix in ("NVIDIA ", "AMD "):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


class GpuCard(QFrame):
    def __init__(self, gpu: GpuHandle, currency: str, limits: WatchdogConfig):
        super().__init__()
        self.setObjectName("card")
        self.gpu = gpu
        self.currency = currency
        self.limits = limits
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        vendor, color = _vendor(gpu)
        badge = QLabel(vendor)
        badge.setStyleSheet(f"background: {theme.rgba(color, 0.14)}; color: {color}; border-radius: 6px;"
                            f"padding: 3px 7px; font-size: 10px; font-weight: 800; letter-spacing: 0.5px;")
        title = QLabel(_short_name(gpu.info.name))
        title.setObjectName("title")
        idx = QLabel(f"GPU{gpu.index}")
        idx.setObjectName("faint")
        self.status = Pill(*STATUS[Severity.OK])
        head.addWidget(badge)
        head.addWidget(title)
        head.addWidget(idx)
        head.addStretch()
        head.addWidget(self.status)
        lay.addLayout(head)

        hero = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(0)
        self.hashrate = QLabel("—")
        self.hashrate.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.settings_label = QLabel()
        self.settings_label.setObjectName("faint")
        left.addWidget(self.hashrate)
        left.addWidget(self.settings_label)
        right = QVBoxLayout()
        right.setSpacing(0)
        self.net = QLabel("—")
        self.net.setStyleSheet("font-size: 22px; font-weight: 700;")
        net_cap = QLabel(f"чистыми, {currency}/сут")
        net_cap.setObjectName("faint")
        for w in (self.net, net_cap):
            right.addWidget(w, 0, Qt.AlignRight)
        hero.addLayout(left, 1)
        hero.addLayout(right)
        lay.addLayout(hero)

        self.spark_hash = Sparkline("хешрейт", theme.HASH_COLOR, height=48, header=False)
        lay.addWidget(self.spark_hash)
        env = QHBoxLayout()
        env.setSpacing(18)
        self.spark_temp = Sparkline("температура GPU", theme.TEMP_COLOR, height=24, fill=False)
        self.spark_power = Sparkline("мощность", theme.POWER_COLOR, height=24, fill=False)
        env.addWidget(self.spark_temp, 1)
        env.addWidget(self.spark_power, 1)
        lay.addLayout(env)
        lay.addWidget(divider())

        row = QHBoxLayout()
        row.setSpacing(12)
        self.m_eff = Metric("эффективность")
        self.m_temp = Metric("GPU / HotSpot")
        self.m_vram = Metric("VRAM")
        self.m_fan = Metric("кулер")
        self.m_shares = Metric("шары ✓ / ✗ / ош.")
        for m in (self.m_eff, self.m_temp, self.m_vram, self.m_fan, self.m_shares):
            row.addWidget(m, 1)
        lay.addLayout(row)

    def update_data(self, snap: GpuSnapshot | None, history, severity: Severity) -> None:
        self.settings_label.setText("Настройки: " + self.gpu.settings.describe())
        text, color = STATUS.get(severity, ("● Сбой", theme.BAD))
        self.status.set(text, color)
        if snap is None:
            return
        t, m, p = snap.telemetry, snap.miner, snap.profit
        if snap.error:
            self.status.setToolTip(snap.error)
            self.status.set("● Ошибка драйвера", theme.BAD)
        self.hashrate.setText(format_hashrate(m.hashrate) if m else "—")
        if m and t and t.power_w:
            self.m_eff.set(format_hashrate(m.hashrate / t.power_w, "H/Вт"))
        if p:
            self.net.setText(f"{p.net_per_day:+.2f}")
            self.net.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme.money_color(p.net_per_day)};")
        if t:
            lim = self.limits
            core = theme.temp_color(t.gpu_temp_c, lim.max_gpu_temp_c)
            hot = theme.temp_color(t.hotspot_temp_c, lim.max_hotspot_temp_c)
            self.m_temp.set(f"{_fmt(t.gpu_temp_c, '°')} / {_fmt(t.hotspot_temp_c, '°')}",
                            core if core != theme.TEXT else hot)
            self.m_vram.set(_fmt(t.vram_temp_c, "°C"), theme.temp_color(t.vram_temp_c, lim.max_vram_temp_c))
            self.m_fan.set(_fmt(t.fan_percent, " %"))
        if m:
            self.m_shares.set(f"{m.accepted} / {m.rejected + m.stale} / {m.invalid}",
                              theme.BAD if m.invalid else None)
        history = list(history or [])  # копия: история дописывается из потока опроса
        if history:
            xs = [h[0] for h in history]
            self.spark_hash.set_data(xs, [h[1] for h in history], format_hashrate(history[-1][1]))
            self.spark_temp.set_data(xs, [h[2] for h in history], f"{history[-1][2]:.0f} °C")
            self.spark_power.set_data(xs, [h[3] for h in history], f"{history[-1][3]:.0f} Вт")


class Dashboard(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        cur = runtime.cfg.currency
        lay = QVBoxLayout(self)
        lay.setSpacing(16)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.s_hash = StatTile("общий хешрейт")
        self.s_power = StatTile("из розетки")
        self.s_gross = StatTile(f"доход, {cur}/сут")
        self.s_cost = StatTile(f"свет, {cur}/сут")
        self.s_net = StatTile(f"чистыми, {cur}/сут", accent=True)
        for w in (self.s_hash, self.s_power, self.s_gross, self.s_cost, self.s_net):
            tiles.addWidget(w, 1)
        lay.addLayout(tiles)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(14)
        self.cards: list[GpuCard] = []
        for i, gpu in enumerate(runtime.rig.gpus):
            card = GpuCard(gpu, cur, runtime.cfg.watchdog)
            self.cards.append(card)
            grid.addWidget(card, i // 2, i % 2)
        grid.setRowStretch(grid.rowCount(), 1)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        log_card = QFrame()
        log_card.setObjectName("card")
        lc = QVBoxLayout(log_card)
        lc.setContentsMargins(16, 10, 16, 8)
        lc.setSpacing(4)
        log_head = QLabel("События watchdog")
        log_head.setObjectName("sectionTitle")
        lc.addWidget(log_head)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setFixedHeight(54)
        self.events.setPlaceholderText("Пока всё спокойно: откаты, перегрев и перезапуски майнера появятся здесь")
        lc.addWidget(self.events)
        lay.addWidget(log_card)
        self._shown_events = 0

    def refresh(self, snap: Snapshot) -> None:
        cur = self.runtime.cfg.currency
        total_hash = sum(g.miner.hashrate for g in snap.gpus.values() if g.miner)
        self.s_hash.set(format_hashrate(total_hash), sub=f"{len(snap.gpus)} карт · {snap.algorithm}")
        if snap.total:
            t = snap.total
            self.s_power.set(f"{t.wall_power_w:.0f} Вт", sub=f"{t.wall_power_w * 24 / 1000:.1f} кВт·ч в сутки")
            self.s_gross.set(f"{t.revenue_per_day:.2f}", sub=f"{t.revenue_per_month:,.0f} {cur}/мес".replace(",", " "))
            self.s_cost.set(f"{t.cost_per_day:.2f}", sub=f"{t.cost_per_month:,.0f} {cur}/мес".replace(",", " "))
            net = t.net_per_day
            self.s_net.set(f"{net:+.2f}", theme.money_color(net),
                           sub=f"{t.net_per_month:+,.0f} {cur}/мес".replace(",", " "))
        for card in self.cards:
            idx = card.gpu.index
            sev = snap.health.worst(idx) if snap.health else Severity.OK
            card.update_data(snap.gpus.get(idx), self.runtime.history.get(idx), sev)
        fresh = self.runtime.event_count - self._shown_events
        if fresh > 0:
            for msg in list(self.runtime.events)[-fresh:]:
                self.events.appendPlainText(msg)
            self._shown_events = self.runtime.event_count
