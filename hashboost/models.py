"""Общие модели данных HashBoost."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class Vendor(str, Enum):
    NVIDIA = "nvidia"
    AMD = "amd"
    SIMULATED = "sim"


@dataclass(frozen=True)
class GpuInfo:
    """Статическая информация о видеокарте."""

    index: int
    uid: str  # стабильный идентификатор (UUID / PCI bus id) для привязки профилей
    name: str
    vendor: Vendor
    stock_core_mhz: int
    stock_mem_mhz: int
    stock_power_limit_w: float
    min_power_limit_w: float
    max_power_limit_w: float
    stock_voltage_mv: Optional[int] = None


@dataclass(frozen=True)
class OcSettings:
    """Настройки разгона/андервольтинга одной карты.

    * ``core_lock_mhz`` — фиксация частоты ядра (Curve Lock). ``None`` — без фиксации.
    * ``core_offset_mhz`` / ``mem_offset_mhz`` — смещения частот относительно стока.
    * ``voltage_offset_mv`` — смещение напряжения ядра (отрицательное = андервольт).
      На NVIDIA через NVML прямого управления напряжением нет, поэтому backend
      переводит его в смещение V/F-кривой при зафиксированной частоте.
    * ``power_limit_w`` — лимит мощности. ``None`` — стоковый.
    """

    core_lock_mhz: Optional[int] = None
    core_offset_mhz: int = 0
    mem_offset_mhz: int = 0
    voltage_offset_mv: int = 0
    power_limit_w: Optional[float] = None

    def replace(self, **changes) -> "OcSettings":
        data = asdict(self)
        data.update(changes)
        return OcSettings(**data)

    def describe(self) -> str:
        parts = []
        if self.core_lock_mhz is not None:
            parts.append(f"ядро {self.core_lock_mhz} МГц")
        if self.core_offset_mhz:
            parts.append(f"ядро {self.core_offset_mhz:+d} МГц")
        if self.mem_offset_mhz:
            parts.append(f"память {self.mem_offset_mhz:+d} МГц")
        if self.voltage_offset_mv:
            parts.append(f"напряжение {self.voltage_offset_mv:+d} мВ")
        if self.power_limit_w is not None:
            parts.append(f"PL {self.power_limit_w:.0f} Вт")
        return ", ".join(parts) or "сток"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "OcSettings":
        known = {k: data[k] for k in OcSettings.__dataclass_fields__ if k in data}
        return OcSettings(**known)


STOCK = OcSettings()


@dataclass
class GpuTelemetry:
    """Мгновенный снимок состояния карты."""

    timestamp: float
    gpu_temp_c: Optional[float] = None
    hotspot_temp_c: Optional[float] = None
    vram_temp_c: Optional[float] = None
    fan_percent: Optional[float] = None
    power_w: Optional[float] = None
    core_mhz: Optional[float] = None
    mem_mhz: Optional[float] = None
    voltage_mv: Optional[float] = None
    utilization: Optional[float] = None


@dataclass
class GpuMinerStats:
    """Показатели майнера по одной карте."""

    hashrate: float = 0.0  # H/s, текущий
    hashrate_avg: float = 0.0  # H/s, средний за окно майнера
    accepted: int = 0
    rejected: int = 0
    stale: int = 0
    invalid: int = 0  # аппаратные ошибки / невалидные шары


@dataclass
class MinerStats:
    """Снимок статистики майнера."""

    timestamp: float
    algorithm: str = ""
    online: bool = True
    uptime_s: float = 0.0
    gpus: dict[int, GpuMinerStats] = field(default_factory=dict)

    @property
    def total_hashrate(self) -> float:
        return sum(g.hashrate for g in self.gpus.values())


@dataclass
class BenchmarkSample:
    """Результат одного шага калибровки."""

    phase: str
    settings: OcSettings
    hashrate: float  # H/s, усреднённый за окно стабилизации
    power_w: float
    stable: bool
    revenue_per_day: float = 0.0
    cost_per_day: float = 0.0
    note: str = ""

    @property
    def net_per_day(self) -> float:
        return self.revenue_per_day - self.cost_per_day

    @property
    def efficiency(self) -> float:
        """Хешрейт на ватт (H/s/W)."""
        return self.hashrate / self.power_w if self.power_w > 0 else 0.0


def format_hashrate(value: float, unit: str = "H/s") -> str:
    prefixes = ["", "K", "M", "G", "T", "P"]
    v = float(value)
    i = 0
    while abs(v) >= 1000 and i < len(prefixes) - 1:
        v /= 1000
        i += 1
    return f"{v:.2f} {prefixes[i]}{unit}"
