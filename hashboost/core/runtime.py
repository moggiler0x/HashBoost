"""Связка всех модулей: опрос телеметрии, история, watchdog, профили."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clock import Clock, ScaledClock
from ..config import AppConfig, data_dir
from ..hardware import GpuBackendError, Rig, detect_backends
from ..miners import MinerApiError, create_miner
from ..models import GpuMinerStats, GpuTelemetry, MinerStats, OcSettings
from .autotune import AutoTuner, TunerCallbacks
from .profiles import Profile, ProfileStore
from .profit import ProfitBreakdown, ProfitEngine
from .watchdog import HealthReport, Watchdog

log = logging.getLogger(__name__)
HISTORY_POINTS = 600


@dataclass
class GpuSnapshot:
    telemetry: Optional[GpuTelemetry]
    miner: Optional[GpuMinerStats]
    profit: Optional[ProfitBreakdown]
    error: str = ""


@dataclass
class Snapshot:
    timestamp: float
    gpus: dict[int, GpuSnapshot] = field(default_factory=dict)
    miner_online: bool = False
    miner_error: str = ""
    algorithm: str = ""
    total: Optional[ProfitBreakdown] = None
    health: Optional[HealthReport] = None


class Runtime:
    def __init__(self, cfg: AppConfig, sim_time_scale: float = 1.0):
        self.cfg = cfg
        self.clock: Clock = ScaledClock(sim_time_scale) if cfg.simulate and sim_time_scale != 1.0 else Clock()
        backends, self.sim = detect_backends(cfg.simulate, cfg.tuning.nvidia_mhz_per_mv, clock=self.clock)
        self.simulated = self.sim is not None
        self.rig = Rig(backends)
        self.miner, self.controller = create_miner(cfg.miner, self.sim)
        self.profit = ProfitEngine(cfg)
        self.profiles = ProfileStore(data_dir() / "profiles.json")
        self.events: deque[str] = deque(maxlen=500)
        self.event_count = 0
        self.event_listeners: list[Callable[[str], None]] = []
        self.watchdog = Watchdog(self.rig, self.miner, self.controller, cfg.watchdog, self.clock, self._event)
        self.history: dict[int, deque[tuple[float, float, float, float]]] = {
            g.index: deque(maxlen=HISTORY_POINTS) for g in self.rig.gpus}  # (t, hashrate, temp, power)
        self.snapshot = Snapshot(timestamp=0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.tuner: Optional[AutoTuner] = None

    # --- события ---
    def _event(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.events.append(f"{stamp}  {msg}")
        self.event_count += 1
        for listener in list(self.event_listeners):
            listener(msg)

    @property
    def algorithm(self) -> str:
        return self.cfg.miner.algorithm

    # --- опрос ---
    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="hashboost-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.tuner:
            self.tuner.cancel()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка цикла опроса")
            self._stop.wait(self.cfg.poll_interval_s)

    def poll_once(self) -> Snapshot:
        snap = Snapshot(timestamp=self.clock.now(), algorithm=self.algorithm)
        telemetry: dict[int, GpuTelemetry] = {}
        errors: dict[int, str] = {}
        for gpu in self.rig.gpus:
            try:
                telemetry[gpu.index] = self.rig.read(gpu.index)
            except GpuBackendError as exc:
                errors[gpu.index] = str(exc)
        stats: Optional[MinerStats] = None
        try:
            stats = self.miner.fetch()
            snap.miner_online = True
            if stats.algorithm:
                snap.algorithm = stats.algorithm
        except MinerApiError as exc:
            snap.miner_error = str(exc)

        rows = []
        for gpu in self.rig.gpus:
            t = telemetry.get(gpu.index)
            m = stats.gpus.get(gpu.index) if stats else None
            p = None
            if t and t.power_w is not None:
                p = self.profit.evaluate(self.algorithm, m.hashrate if m else 0.0, t.power_w)
                rows.append((self.algorithm, m.hashrate if m else 0.0, t.power_w))
            snap.gpus[gpu.index] = GpuSnapshot(t, m, p, errors.get(gpu.index, ""))
            self.history[gpu.index].append((snap.timestamp, m.hashrate if m else 0.0,
                                            (t.gpu_temp_c or 0.0) if t else 0.0, (t.power_w or 0.0) if t else 0.0))
        snap.total = self.profit.rig_total(rows)
        if not self.watchdog.paused:
            snap.health = self.watchdog.check(telemetry if not errors else None, stats, snap.miner_error or None)
        with self._lock:
            self.snapshot = snap
        return snap

    def latest(self) -> Snapshot:
        with self._lock:
            return self.snapshot

    # --- профили ---
    def apply_profiles(self, algorithm: str) -> list[str]:
        """Применяет сохранённые профили алгоритма ко всем картам (без профиля — сток)."""
        applied = []
        for gpu in self.rig.gpus:
            profile = self.profiles.get(gpu.info.uid, algorithm)
            settings = profile.settings if profile else OcSettings()
            self.rig.apply(gpu.index, settings)
            self.watchdog.mark_stable(gpu.index, settings)
            applied.append(f"{gpu.label}: {settings.describe()}")
        self.cfg.miner.algorithm = algorithm
        if self.sim is not None:
            self.sim.restart_miner(algorithm)
        self._event(f"Профиль «{algorithm}» применён")
        return applied

    def make_tuner(self, callbacks: TunerCallbacks) -> AutoTuner:
        self.tuner = AutoTuner(self.rig, self.miner, self.controller, self.profit, self.cfg.tuning,
                               self.cfg.watchdog, self.algorithm, self.clock, callbacks)
        return self.tuner

    def save_tune_result(self, result) -> Profile:
        gpu = self.rig[result.gpu_index]
        profile = Profile(gpu.info.uid, gpu.info.name, result.algorithm, result.final.settings,
                          result.final.hashrate, result.final.power_w, result.final.net_per_day)
        self.profiles.put(profile)
        self.watchdog.mark_stable(result.gpu_index, result.final.settings)
        self._event(f"{gpu.label}: профиль «{result.algorithm}» сохранён")
        return profile

    def shutdown(self, reset_clocks: bool = False) -> None:
        self.stop()
        if reset_clocks:
            self.rig.reset_all()
        self.rig.close()
