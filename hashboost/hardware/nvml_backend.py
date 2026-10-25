"""NVIDIA через NVML (пакет nvidia-ml-py).

Управление требует прав администратора (Windows) или root (Linux) и драйвера
с поддержкой V/F-смещений (R520+). NVML не даёт задавать напряжение напрямую,
поэтому андервольт делается так же, как «curve lock» в Afterburner:
частота ядра фиксируется ``nvmlDeviceSetGpuLockedClocks``, а V/F-кривая
поднимается положительным смещением — нужная частота достигается на меньшем
напряжении. ``voltage_offset_mv`` переводится в смещение кривой через
коэффициент ``mhz_per_mv``.
"""
from __future__ import annotations

import time

from ..models import GpuInfo, GpuTelemetry, OcSettings, Vendor
from .base import Capabilities, GpuBackend, GpuBackendError

try:  # pragma: no cover - зависит от машины
    import pynvml
except Exception:  # noqa: BLE001
    pynvml = None


def nvml_available() -> bool:
    if pynvml is None:
        return False
    try:
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        pynvml.nvmlShutdown()
        return count > 0
    except Exception:  # noqa: BLE001
        return False


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class NvmlBackend(GpuBackend):  # pragma: no cover - требует реальную карту
    name = "NVIDIA NVML"
    capabilities = Capabilities(hotspot_temp=False)

    def __init__(self, mhz_per_mv: float = 1.2):
        if pynvml is None:
            raise GpuBackendError("nvidia-ml-py не установлен")
        self.mhz_per_mv = mhz_per_mv
        try:
            pynvml.nvmlInit()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
        except pynvml.NVMLError as exc:
            raise GpuBackendError(f"NVML: {exc}") from exc
        self._infos = [self._read_info(i, h) for i, h in enumerate(self._handles)]

    def _read_info(self, index: int, h) -> GpuInfo:
        nv = pynvml
        try:
            min_pl, max_pl = nv.nvmlDeviceGetPowerManagementLimitConstraints(h)
            default_pl = nv.nvmlDeviceGetPowerManagementDefaultLimit(h)
        except nv.NVMLError:
            min_pl = max_pl = default_pl = 0
        return GpuInfo(
            index=index,
            uid=_text(nv.nvmlDeviceGetUUID(h)),
            name=_text(nv.nvmlDeviceGetName(h)),
            vendor=Vendor.NVIDIA,
            stock_core_mhz=nv.nvmlDeviceGetMaxClockInfo(h, nv.NVML_CLOCK_GRAPHICS),
            stock_mem_mhz=nv.nvmlDeviceGetMaxClockInfo(h, nv.NVML_CLOCK_MEM),
            stock_power_limit_w=default_pl / 1000,
            min_power_limit_w=min_pl / 1000,
            max_power_limit_w=max_pl / 1000,
        )

    def list_gpus(self) -> list[GpuInfo]:
        return list(self._infos)

    def read_telemetry(self, index: int) -> GpuTelemetry:
        nv = pynvml
        h = self._handles[index]
        t = GpuTelemetry(timestamp=time.monotonic())
        try:
            t.gpu_temp_c = nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)
            t.power_w = nv.nvmlDeviceGetPowerUsage(h) / 1000
            t.core_mhz = nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS)
            t.mem_mhz = nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_MEM)
            t.utilization = nv.nvmlDeviceGetUtilizationRates(h).gpu
        except nv.NVMLError as exc:
            # GPU_IS_LOST и подобные — признак отвала драйвера
            raise GpuBackendError(f"NVML: {exc}") from exc
        try:
            t.fan_percent = nv.nvmlDeviceGetFanSpeed(h)
        except nv.NVMLError:
            pass
        try:
            value = nv.nvmlDeviceGetFieldValues(h, [nv.NVML_FI_DEV_MEMORY_TEMP])[0]
            if value.nvmlReturn == nv.NVML_SUCCESS:
                t.vram_temp_c = float(value.value.uiVal)
        except (nv.NVMLError, AttributeError):
            pass
        return t

    def apply(self, index: int, settings: OcSettings) -> None:
        nv = pynvml
        h = self._handles[index]
        info = self._infos[index]
        try:
            limit = settings.power_limit_w or info.stock_power_limit_w
            if limit:
                limit = min(max(limit, info.min_power_limit_w), info.max_power_limit_w)
                nv.nvmlDeviceSetPowerManagementLimit(h, int(limit * 1000))

            core_offset = settings.core_offset_mhz
            if settings.core_lock_mhz is not None:
                core_offset += int(round(-settings.voltage_offset_mv * self.mhz_per_mv))
                nv.nvmlDeviceSetGpuLockedClocks(h, settings.core_lock_mhz, settings.core_lock_mhz)
            else:
                nv.nvmlDeviceResetGpuLockedClocks(h)
            nv.nvmlDeviceSetGpcClkVfOffset(h, core_offset)
            nv.nvmlDeviceSetMemClkVfOffset(h, settings.mem_offset_mhz)
        except nv.NVMLError as exc:
            raise GpuBackendError(f"NVML: не удалось применить настройки: {exc}") from exc

    def close(self) -> None:
        try:
            pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass
