"""Симулятор рига: позволяет проверить авто-тюн, watchdog и GUI без реальных карт.

Модель упрощённая, но повторяет главные эффекты:
* хешрейт зависит от частот ядра и памяти с весами, зависящими от алгоритма;
* мощность растёт как V²·f, лимит мощности ограничивает частоту;
* у каждой карты своя «кремниевая лотерея»: запас по андервольту и разгону памяти;
* недостаток напряжения или перегон памяти дают невалидные шары, сильный — отвал.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field

from ..clock import Clock
from ..models import GpuInfo, GpuMinerStats, GpuTelemetry, OcSettings, Vendor
from .base import Capabilities, GpuBackend, GpuBackendError

VOLT_PER_MHZ = 0.45  # наклон стоковой V/F-кривой, мВ на МГц
MIN_VOLTAGE = 650.0
CRASH_DEFICIT_MV = 35.0
CRASH_MEM_EXCESS_MHZ = 300.0


@dataclass
class AlgoPerf:
    base_hashrate: float  # H/s на стоковых частотах
    core_weight: float
    mem_weight: float


@dataclass
class SimGpuSpec:
    name: str
    stock_core: int
    stock_mem: int
    stock_pl: float
    stock_v: int
    idle_w: float
    core_dyn_w: float
    mem_w: float
    algos: dict[str, AlgoPerf]
    uv_headroom_mv: float = 90.0  # насколько ниже стоковой кривой карта ещё стабильна
    mem_headroom_mhz: float = 600.0
    vendor_label: str = "NVIDIA"
    thermal_c_per_w: float = 0.35


DEMO_RIG = [
    SimGpuSpec("NVIDIA GeForce RTX 4060", 2460, 8500, 115, 1050, 18, 80, 17,
               {"poseidon2": AlgoPerf(310e6, 0.92, 0.08), "pearlhash": AlgoPerf(41e6, 0.45, 0.55)},
               uv_headroom_mv=110, mem_headroom_mhz=1200),
    SimGpuSpec("NVIDIA CMP 30HX", 1785, 7000, 125, 1000, 22, 80, 23,
               {"poseidon2": AlgoPerf(190e6, 0.92, 0.08), "pearlhash": AlgoPerf(30e6, 0.45, 0.55)},
               uv_headroom_mv=85, mem_headroom_mhz=700),
    SimGpuSpec("NVIDIA GeForce GTX 1660 SUPER", 1830, 7000, 125, 1043, 20, 82, 23,
               {"poseidon2": AlgoPerf(175e6, 0.92, 0.08), "pearlhash": AlgoPerf(28e6, 0.45, 0.55)},
               uv_headroom_mv=70, mem_headroom_mhz=900),
    SimGpuSpec("AMD Radeon RX 570", 1244, 1750, 150, 1150, 30, 95, 25,
               {"poseidon2": AlgoPerf(120e6, 0.9, 0.1), "pearlhash": AlgoPerf(24e6, 0.4, 0.6)},
               uv_headroom_mv=120, mem_headroom_mhz=200, vendor_label="AMD"),
]


@dataclass
class _GpuState:
    spec: SimGpuSpec
    settings: OcSettings = field(default_factory=OcSettings)
    crashed: bool = False
    accepted: float = 0.0
    invalid: float = 0.0
    rejected: float = 0.0
    hashrate_avg: float = 0.0


@dataclass
class _Operating:
    core: float
    mem: float
    voltage: float
    power: float
    hashrate_factor: float
    errors_per_min: float
    crash: bool


class SimulatedRig:
    """Общее состояние симулятора; его используют и backend, и симулированный майнер."""

    def __init__(self, specs: list[SimGpuSpec] | None = None, clock: Clock | None = None, seed: int = 7):
        self.clock = clock or Clock()
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self.gpus = [_GpuState(spec) for spec in (specs or DEMO_RIG)]
        self.algorithm = "poseidon2"
        self.miner_running = True
        self._last_tick = self.clock.now()
        self.miner_started_at = self._last_tick

    # --- физическая модель ---
    def _operating(self, gpu: _GpuState) -> _Operating:
        sp, st = gpu.spec, gpu.settings

        def v_stock(f: float) -> float:
            return max(MIN_VOLTAGE, sp.stock_v + VOLT_PER_MHZ * (f - sp.stock_core))

        def volt_at(f: float) -> float:
            # Смещение кривой: частота f берётся с точки кривой f - offset
            return max(MIN_VOLTAGE, v_stock(f - st.core_offset_mhz) + st.voltage_offset_mv)

        mem = float(sp.stock_mem + st.mem_offset_mhz)
        mem_power = sp.mem_w * mem / sp.stock_mem

        def power_at(f: float) -> float:
            return sp.idle_w + mem_power + sp.core_dyn_w * (volt_at(f) / sp.stock_v) ** 2 * (f / sp.stock_core)

        core = float(st.core_lock_mhz if st.core_lock_mhz is not None else sp.stock_core + st.core_offset_mhz)
        limit = st.power_limit_w if st.power_limit_w is not None else sp.stock_pl
        if power_at(core) > limit:
            # Лимит мощности: карта опускается по V/F-кривой, пока не впишется в лимит
            lo, hi = 100.0, core
            for _ in range(30):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if power_at(mid) <= limit else (lo, mid)
            core = lo
        voltage = volt_at(core)
        power = power_at(core)
        deficit = (v_stock(core) - sp.uv_headroom_mv) - voltage
        mem_excess = st.mem_offset_mhz - sp.mem_headroom_mhz

        perf = sp.algos.get(self.algorithm) or next(iter(sp.algos.values()))
        factor = (core / sp.stock_core) ** perf.core_weight * (mem / sp.stock_mem) ** perf.mem_weight

        errors = 0.0
        if deficit > 0:
            errors += deficit / 5.0
        if mem_excess > 0:
            errors += mem_excess / 50.0
        crash = deficit > CRASH_DEFICIT_MV or mem_excess > CRASH_MEM_EXCESS_MHZ
        return _Operating(core, mem, voltage, power, factor, errors, crash)

    def tick(self) -> None:
        """Продвигает модель до текущего времени: копит шары и ошибки."""
        with self._lock:
            now = self.clock.now()
            dt = max(0.0, now - self._last_tick)
            self._last_tick = now
            if not self.miner_running:
                return
            for gpu in self.gpus:
                op = self._operating(gpu)
                if op.crash:
                    gpu.crashed = True
                if gpu.crashed:
                    gpu.hashrate_avg = 0.0
                    continue
                hr = self._hashrate(gpu, op)
                gpu.hashrate_avg = hr if gpu.hashrate_avg == 0 else gpu.hashrate_avg * 0.8 + hr * 0.2
                gpu.accepted += dt / 20.0 * (hr / max(hr, 1.0))
                gpu.invalid += op.errors_per_min * dt / 60.0
                gpu.rejected += dt / 2400.0

    def _hashrate(self, gpu: _GpuState, op: _Operating) -> float:
        perf = gpu.spec.algos.get(self.algorithm) or next(iter(gpu.spec.algos.values()))
        noise = 1.0 + self._rng.uniform(-0.004, 0.004)
        error_penalty = max(0.0, 1.0 - op.errors_per_min * 0.01)
        return perf.base_hashrate * op.hashrate_factor * noise * error_penalty

    # --- интерфейс для майнера ---
    def miner_snapshot(self) -> dict[int, GpuMinerStats]:
        self.tick()
        with self._lock:
            out = {}
            for i, gpu in enumerate(self.gpus):
                if gpu.crashed or not self.miner_running:
                    out[i] = GpuMinerStats(0.0, 0.0, int(gpu.accepted), int(gpu.rejected), 0, int(gpu.invalid))
                    continue
                hr = self._hashrate(gpu, self._operating(gpu))
                out[i] = GpuMinerStats(hr, gpu.hashrate_avg, int(gpu.accepted), int(gpu.rejected), 0, int(gpu.invalid))
            return out

    def restart_miner(self, algorithm: str | None = None) -> None:
        with self._lock:
            if algorithm:
                self.algorithm = algorithm
            for gpu in self.gpus:
                gpu.crashed = False
                gpu.hashrate_avg = 0.0
            self.miner_running = True
            self.miner_started_at = self.clock.now()
            self._last_tick = self.miner_started_at

    def stop_miner(self) -> None:
        with self._lock:
            self.tick()
            self.miner_running = False


class SimulatedBackend(GpuBackend):
    name = "Симулятор"
    capabilities = Capabilities()

    def __init__(self, rig: SimulatedRig):
        self.rig = rig
        self._rng = random.Random(11)

    def list_gpus(self) -> list[GpuInfo]:
        result = []
        for i, gpu in enumerate(self.rig.gpus):
            sp = gpu.spec
            result.append(GpuInfo(
                index=i, uid=f"SIM-{i}-{sp.name.replace(' ', '_')}", name=sp.name, vendor=Vendor.SIMULATED,
                stock_core_mhz=sp.stock_core, stock_mem_mhz=sp.stock_mem, stock_power_limit_w=sp.stock_pl,
                min_power_limit_w=round(sp.stock_pl * 0.5), max_power_limit_w=round(sp.stock_pl * 1.2),
                stock_voltage_mv=sp.stock_v,
            ))
        return result

    def read_telemetry(self, index: int) -> GpuTelemetry:
        self.rig.tick()
        try:
            gpu = self.rig.gpus[index]
        except IndexError as exc:
            raise GpuBackendError(f"нет карты {index}") from exc
        op = self.rig._operating(gpu)
        working = self.rig.miner_running and not gpu.crashed
        power = op.power if working else gpu.spec.idle_w
        jitter = self._rng.uniform(-0.6, 0.6)
        temp = 26 + power * gpu.spec.thermal_c_per_w + jitter
        return GpuTelemetry(
            timestamp=self.rig.clock.now(),
            gpu_temp_c=round(temp, 1),
            hotspot_temp_c=round(temp + 11 + power * 0.03, 1),
            vram_temp_c=round(40 + op.mem / gpu.spec.stock_mem * 18 + power * 0.08, 1),
            fan_percent=round(min(100, max(30, (temp - 35) * 2.2)), 0),
            power_w=round(power * (1 + jitter / 100), 1),
            core_mhz=round(op.core if working else 210),
            mem_mhz=round(op.mem if working else 405),
            voltage_mv=round(op.voltage if working else 650),
            utilization=100.0 if working else 0.0,
        )

    def apply(self, index: int, settings: OcSettings) -> None:
        with self.rig._lock:
            self.rig.tick()
            self.rig.gpus[index].settings = settings
