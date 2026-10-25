"""Абстракция драйвера видеокарт."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import GpuInfo, GpuTelemetry, OcSettings


class GpuBackendError(RuntimeError):
    """Ошибка драйвера: карта недоступна, драйвер упал, нет прав и т.п."""


@dataclass(frozen=True)
class Capabilities:
    core_lock: bool = True
    core_offset: bool = True
    mem_offset: bool = True
    voltage: bool = True
    power_limit: bool = True
    hotspot_temp: bool = True
    vram_temp: bool = True


class GpuBackend(ABC):
    """Драйверный слой одного производителя (NVML, ADL, симулятор)."""

    name: str = "base"
    capabilities: Capabilities = Capabilities()

    @abstractmethod
    def list_gpus(self) -> list[GpuInfo]:
        """Карты этого backend'а. ``GpuInfo.index`` — локальный индекс внутри backend'а."""

    @abstractmethod
    def read_telemetry(self, index: int) -> GpuTelemetry: ...

    @abstractmethod
    def apply(self, index: int, settings: OcSettings) -> None: ...

    def reset(self, index: int) -> None:
        self.apply(index, OcSettings())

    def close(self) -> None:  # pragma: no cover - по умолчанию ничего
        pass
