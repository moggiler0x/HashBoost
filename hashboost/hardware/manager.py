"""Сборка рига из доступных драйверов и единая нумерация карт."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from ..models import GpuInfo, GpuTelemetry, OcSettings
from .base import GpuBackend, GpuBackendError

log = logging.getLogger(__name__)


@dataclass
class GpuHandle:
    """Карта рига: глобальный индекс, драйвер и последние применённые настройки."""

    index: int
    info: GpuInfo
    backend: GpuBackend
    local_index: int
    settings: OcSettings = field(default_factory=OcSettings)

    @property
    def label(self) -> str:
        return f"GPU{self.index} · {self.info.name}"


class Rig:
    def __init__(self, backends: list[GpuBackend]):
        self.backends = backends
        self.gpus: list[GpuHandle] = []
        self._lock = threading.RLock()
        for backend in backends:
            for info in backend.list_gpus():
                self.gpus.append(GpuHandle(len(self.gpus), info, backend, info.index))

    def __len__(self) -> int:
        return len(self.gpus)

    def __getitem__(self, index: int) -> GpuHandle:
        return self.gpus[index]

    def read(self, index: int) -> GpuTelemetry:
        gpu = self.gpus[index]
        with self._lock:
            return gpu.backend.read_telemetry(gpu.local_index)

    def apply(self, index: int, settings: OcSettings) -> None:
        gpu = self.gpus[index]
        with self._lock:
            gpu.backend.apply(gpu.local_index, settings)
            gpu.settings = settings
        log.info("%s: применено — %s", gpu.label, settings.describe())

    def reset_all(self) -> None:
        for gpu in self.gpus:
            try:
                self.apply(gpu.index, OcSettings())
            except GpuBackendError as exc:
                log.warning("%s: сброс не удался: %s", gpu.label, exc)

    def close(self) -> None:
        for backend in self.backends:
            backend.close()


def detect_backends(simulate: bool = False, mhz_per_mv: float = 1.2, clock=None):
    """Возвращает (список backend'ов, симулятор или None)."""
    if not simulate:
        backends: list[GpuBackend] = []
        from .nvml_backend import NvmlBackend, nvml_available

        if nvml_available():
            try:
                backends.append(NvmlBackend(mhz_per_mv))
            except GpuBackendError as exc:
                log.warning("NVML недоступен: %s", exc)
        from .adl_backend import AdlBackend, adl_available

        if adl_available():
            try:
                backends.append(AdlBackend())
            except GpuBackendError as exc:
                log.warning("ADL недоступен: %s", exc)
        if backends:
            return backends, None
        log.warning("Видеокарты не найдены — запускаю режим симуляции")

    from .simulator import SimulatedBackend, SimulatedRig

    sim = SimulatedRig(clock=clock)
    return [SimulatedBackend(sim)], sim
