"""Health Monitor и Watchdog: контроль стабильности и защита от отвала."""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from ..clock import Clock
from ..config import WatchdogConfig
from ..hardware import GpuBackendError, Rig
from ..miners import MinerApiError, MinerClient, MinerController
from ..models import GpuMinerStats, GpuTelemetry, MinerStats, OcSettings

log = logging.getLogger(__name__)


class Severity(IntEnum):
    OK = 0
    WARN = 1
    UNSTABLE = 2  # ошибки вычислений: нужен откат настроек
    CRITICAL = 3  # перегрев / отвал карты: откат и перезапуск майнера


@dataclass
class HealthIssue:
    gpu: int
    severity: Severity
    message: str
    thermal: bool = False


@dataclass
class HealthReport:
    issues: list[HealthIssue] = field(default_factory=list)

    def worst(self, gpu: Optional[int] = None) -> Severity:
        sev = [i.severity for i in self.issues if gpu is None or i.gpu == gpu]
        return max(sev, default=Severity.OK)


class HealthMonitor:
    """Оценивает состояние каждой карты по телеметрии и статистике майнера."""

    def __init__(self, cfg: WatchdogConfig):
        self.cfg = cfg

    def check_temps(self, gpu: int, t: GpuTelemetry) -> list[HealthIssue]:
        issues = []
        for value, limit, label in ((t.gpu_temp_c, self.cfg.max_gpu_temp_c, "GPU"),
                                    (t.hotspot_temp_c, self.cfg.max_hotspot_temp_c, "HotSpot"),
                                    (t.vram_temp_c, self.cfg.max_vram_temp_c, "VRAM")):
            if value is None:
                continue
            if value >= limit:
                issues.append(HealthIssue(gpu, Severity.CRITICAL, f"перегрев {label}: {value:.0f}°C ≥ {limit:.0f}°C",
                                          thermal=True))
            elif value >= limit - 5:
                issues.append(HealthIssue(gpu, Severity.WARN, f"{label} близко к пределу: {value:.0f}°C", thermal=True))
        return issues

    def check_mining(self, gpu: int, prev: Optional[GpuMinerStats], cur: Optional[GpuMinerStats],
                     dt_s: float, miner_online: bool) -> list[HealthIssue]:
        if not miner_online:
            return []
        if cur is None:
            return [HealthIssue(gpu, Severity.CRITICAL, "карта пропала из статистики майнера")]
        issues = []
        if cur.hashrate <= 0:
            issues.append(HealthIssue(gpu, Severity.CRITICAL, "хешрейт упал до нуля — вероятен отвал"))
        if prev is not None and dt_s > 0:
            new_invalid = cur.invalid - prev.invalid
            per_min = new_invalid / dt_s * 60
            if new_invalid > 0 and per_min >= self.cfg.max_invalid_per_minute:
                issues.append(HealthIssue(gpu, Severity.UNSTABLE, f"аппаратные ошибки: +{new_invalid} (≈{per_min:.1f}/мин)"))
            elif new_invalid > 0:
                issues.append(HealthIssue(gpu, Severity.WARN, f"аппаратные ошибки: +{new_invalid}"))
        return issues


class Watchdog:
    """Фоновая защита в обычном режиме работы рига.

    Помнит последние стабильные настройки каждой карты. При ошибках откатывает
    карту на них, при отвале или пропаже API — ещё и перезапускает майнер.
    """

    def __init__(self, rig: Rig, miner: MinerClient, controller: MinerController, cfg: WatchdogConfig,
                 clock: Clock | None = None, on_event: Callable[[str], None] | None = None):
        self.rig = rig
        self.miner = miner
        self.controller = controller
        self.cfg = cfg
        self.clock = clock or Clock()
        self.monitor = HealthMonitor(cfg)
        self.on_event = on_event or (lambda msg: None)
        self.stable: dict[int, OcSettings] = {}
        self._prev: Optional[MinerStats] = None
        self._last_ok = self.clock.now()
        self._restarts: deque[float] = deque()
        self._lock = threading.Lock()
        self.paused = False  # на время калибровки за картами следит сам авто-тюн

    def mark_stable(self, gpu: int, settings: OcSettings) -> None:
        self.stable[gpu] = settings

    def _event(self, msg: str) -> None:
        log.warning(msg)
        self.on_event(msg)

    def check(self, telemetry: dict[int, GpuTelemetry] | None = None,
              stats: MinerStats | None = None, miner_error: str | None = None) -> HealthReport:
        """Один цикл проверки. Данные можно передать снаружи, чтобы не опрашивать дважды."""
        with self._lock:
            report = HealthReport()
            if not self.cfg.enabled or self.paused:
                return report
            now = self.clock.now()
            if telemetry is None:
                telemetry = {}
                for gpu in self.rig.gpus:
                    try:
                        telemetry[gpu.index] = self.rig.read(gpu.index)
                    except GpuBackendError as exc:
                        report.issues.append(HealthIssue(gpu.index, Severity.CRITICAL, f"драйвер: {exc}"))
            if stats is None and miner_error is None:
                try:
                    stats = self.miner.fetch()
                except MinerApiError as exc:
                    miner_error = str(exc)

            for idx, t in telemetry.items():
                report.issues.extend(self.monitor.check_temps(idx, t))

            if stats is not None:
                self._last_ok = now
                dt = stats.timestamp - self._prev.timestamp if self._prev else 0.0
                for gpu in self.rig.gpus:
                    prev = self._prev.gpus.get(gpu.index) if self._prev else None
                    report.issues.extend(self.monitor.check_mining(gpu.index, prev, stats.gpus.get(gpu.index), dt, True))
                self._prev = stats
            elif now - self._last_ok > self.cfg.miner_timeout_s:
                self._event(f"Майнер не отвечает {now - self._last_ok:.0f} с: {miner_error}")
                self._restart_miner(now)

            self._react(report, now)
            return report

    def _react(self, report: HealthReport, now: float) -> None:
        need_restart = False
        for gpu in self.rig.gpus:
            bad = [i for i in report.issues if i.gpu == gpu.index and i.severity >= Severity.UNSTABLE]
            if not bad:
                continue
            reasons = "; ".join(i.message for i in bad)
            if all(i.thermal for i in bad):
                self._cool_down(gpu, reasons)
                continue
            target = self.stable.get(gpu.index, OcSettings())
            if gpu.settings != target:
                self._event(f"{gpu.label}: {reasons} → откат на «{target.describe()}»")
                try:
                    self.rig.apply(gpu.index, target)
                except GpuBackendError as exc:
                    self._event(f"{gpu.label}: откат не удался: {exc}")
            else:
                self._event(f"{gpu.label}: {reasons}")
            if any(i.severity == Severity.CRITICAL and not i.thermal for i in bad):
                need_restart = True
        if need_restart:
            self._restart_miner(now)

    def _cool_down(self, gpu, reasons: str) -> None:
        """Перегрев: снижаем лимит мощности на 10 %, не ниже минимального."""
        info = gpu.info
        current = gpu.settings.power_limit_w or info.stock_power_limit_w
        if not current:
            self._event(f"{gpu.label}: {reasons} (лимит мощности недоступен — проверьте охлаждение)")
            return
        new_limit = max(info.min_power_limit_w, round(current * 0.9))
        if new_limit >= current:
            self._event(f"{gpu.label}: {reasons}, лимит мощности уже минимальный")
            return
        self._event(f"{gpu.label}: {reasons} → лимит мощности {new_limit:.0f} Вт")
        settings = gpu.settings.replace(power_limit_w=float(new_limit))
        try:
            self.rig.apply(gpu.index, settings)
            if gpu.index in self.stable:
                self.stable[gpu.index] = settings
        except GpuBackendError as exc:
            self._event(f"{gpu.label}: не удалось снизить лимит: {exc}")

    def _restart_miner(self, now: float) -> None:
        while self._restarts and now - self._restarts[0] > 3600:
            self._restarts.popleft()
        if len(self._restarts) >= self.cfg.max_restarts_per_hour:
            self._event("Лимит перезапусков майнера за час исчерпан — нужна проверка вручную")
            return
        self._restarts.append(now)
        self._event("Перезапуск майнера")
        try:
            self.controller.restart()
        except Exception as exc:  # noqa: BLE001
            self._event(f"Не удалось перезапустить майнер: {exc}")
        self._prev = None
        self._last_ok = now
