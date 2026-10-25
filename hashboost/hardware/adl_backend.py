"""AMD через ADL (atiadlxx.dll, только Windows), интерфейс OverdriveN.

Экспериментально: OverdriveN покрывает Polaris/Vega (RX 470–590, Vega 56/64).
Для RDNA нужен Overdrive8 — запланирован отдельно. Частоты ADL отдаёт в
единицах 10 кГц, температуры — в милли-градусах.
"""
from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass

from ..models import GpuInfo, GpuTelemetry, OcSettings, Vendor
from .base import Capabilities, GpuBackend, GpuBackendError

ADL_OK = 0
AMD_VENDOR_ID = 1002
ODN_CONTROL_MANUAL = 3
ODN_TEMP_EDGE, ODN_TEMP_MEM, ODN_TEMP_HOTSPOT = 1, 2, 7
MAX_LEVELS = 8
c_int = ctypes.c_int


class AdapterInfo(ctypes.Structure):
    _fields_ = [
        ("iSize", c_int), ("iAdapterIndex", c_int), ("strUDID", ctypes.c_char * 256),
        ("iBusNumber", c_int), ("iDeviceNumber", c_int), ("iFunctionNumber", c_int),
        ("iVendorID", c_int), ("strAdapterName", ctypes.c_char * 256),
        ("strDisplayName", ctypes.c_char * 256), ("iPresent", c_int), ("iExist", c_int),
        ("strDriverPath", ctypes.c_char * 256), ("strDriverPathExt", ctypes.c_char * 256),
        ("strPNPString", ctypes.c_char * 256), ("iOSDisplayIndex", c_int),
    ]


class ParameterRange(ctypes.Structure):
    _fields_ = [("iMode", c_int), ("iMin", c_int), ("iMax", c_int), ("iStep", c_int), ("iDefault", c_int)]


class OdnCapabilities(ctypes.Structure):
    _fields_ = [
        ("iMaximumNumberOfPerformanceLevels", c_int),
        ("sEngineClockRange", ParameterRange), ("sMemoryClockRange", ParameterRange),
        ("svddcRange", ParameterRange), ("power", ParameterRange),
        ("powerTuneTemperature", ParameterRange), ("fanTemperature", ParameterRange),
        ("fanSpeed", ParameterRange), ("minimumPerformanceClock", ParameterRange),
    ]


class OdnLevel(ctypes.Structure):
    _fields_ = [("iClock", c_int), ("iVddc", c_int), ("iEnabled", c_int)]


class OdnLevels(ctypes.Structure):
    _fields_ = [("iSize", c_int), ("iMode", c_int), ("iNumberOfPerformanceLevels", c_int),
                ("aLevels", OdnLevel * MAX_LEVELS)]


class OdnPerformanceStatus(ctypes.Structure):
    _fields_ = [(name, c_int) for name in (
        "iCoreClock", "iMemoryClock", "iDCEFClock", "iGFXClock", "iUVDClock", "iVCEClock",
        "iGPUActivityPercent", "iCurrentCorePerformanceLevel", "iCurrentMemoryPerformanceLevel",
        "iCurrentDCEFPerformanceLevel", "iCurrentGFXPerformanceLevel", "iUVDPerformanceLevel",
        "iVCEPerformanceLevel", "iCurrentBusSpeed", "iCurrentBusLanes", "iMaximumBusLanes",
        "iVDDC", "iVDDCI")]


class OdnFanControl(ctypes.Structure):
    _fields_ = [(name, c_int) for name in (
        "iMode", "iFanControlMode", "iCurrentFanSpeedMode", "iCurrentFanSpeed",
        "iTargetFanSpeed", "iTargetTemperature", "iMinPerformanceClock", "iMinFanLimit")]


@dataclass
class _Adapter:
    adl_index: int
    info: GpuInfo
    default_sclk: OdnLevels
    default_mclk: OdnLevels


_MALLOC = ctypes.CFUNCTYPE(ctypes.c_void_p, c_int)
_ADL_BUFFERS: list = []  # ADL не освобождает выделенное через колбэк — держим ссылки


@_MALLOC
def _adl_malloc(size):  # pragma: no cover - вызывается драйвером
    buf = ctypes.create_string_buffer(size)
    _ADL_BUFFERS.append(buf)
    return ctypes.cast(buf, ctypes.c_void_p).value


def adl_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.WinDLL("atiadlxx.dll")
        return True
    except OSError:
        return False


class AdlBackend(GpuBackend):  # pragma: no cover - требует Windows и карту AMD
    name = "AMD ADL"
    capabilities = Capabilities(power_limit=False)

    def __init__(self):
        if sys.platform != "win32":
            raise GpuBackendError("ADL доступен только в Windows")
        try:
            self._dll = ctypes.WinDLL("atiadlxx.dll")
        except OSError as exc:
            raise GpuBackendError("atiadlxx.dll не найден — установлен ли драйвер AMD?") from exc
        self._ctx = ctypes.c_void_p()
        self._call("ADL2_Main_Control_Create", _adl_malloc, 1, ctypes.byref(self._ctx))
        self._adapters = self._enumerate()

    def _call(self, fn: str, *args) -> None:
        func = getattr(self._dll, fn)
        rc = func(*args) if fn == "ADL2_Main_Control_Create" else func(self._ctx, *args)
        if rc != ADL_OK:
            raise GpuBackendError(f"{fn} вернул код {rc}")

    def _enumerate(self) -> list[_Adapter]:
        count = c_int()
        self._call("ADL2_Adapter_NumberOfAdapters_Get", ctypes.byref(count))
        infos = (AdapterInfo * count.value)()
        self._call("ADL2_Adapter_AdapterInfo_Get", infos, ctypes.sizeof(infos))
        seen_bus, adapters = set(), []
        for ai in infos:
            if ai.iVendorID != AMD_VENDOR_ID or ai.iBusNumber in seen_bus:
                continue
            active = c_int()
            try:
                self._call("ADL2_Adapter_Active_Get", ai.iAdapterIndex, ctypes.byref(active))
            except GpuBackendError:
                continue
            seen_bus.add(ai.iBusNumber)
            caps = OdnCapabilities()
            self._call("ADL2_OverdriveN_Capabilities_Get", ai.iAdapterIndex, ctypes.byref(caps))
            sclk, mclk = self._levels("System", ai.iAdapterIndex), self._levels("Memory", ai.iAdapterIndex)
            top = sclk.aLevels[sclk.iNumberOfPerformanceLevels - 1]
            info = GpuInfo(
                index=len(adapters), uid=f"PCI:{ai.iBusNumber}:{ai.iDeviceNumber}",
                name=ai.strAdapterName.decode(errors="replace").strip(), vendor=Vendor.AMD,
                stock_core_mhz=caps.sEngineClockRange.iDefault // 100,
                stock_mem_mhz=caps.sMemoryClockRange.iDefault // 100,
                stock_power_limit_w=0.0, min_power_limit_w=0.0, max_power_limit_w=0.0,
                stock_voltage_mv=top.iVddc or None,
            )
            adapters.append(_Adapter(ai.iAdapterIndex, info, sclk, mclk))
        return adapters

    def _levels(self, kind: str, adl_index: int) -> OdnLevels:
        levels = OdnLevels()
        levels.iSize = ctypes.sizeof(OdnLevels)
        levels.iNumberOfPerformanceLevels = MAX_LEVELS
        self._call(f"ADL2_OverdriveN_{kind}Clocks_Get", adl_index, ctypes.byref(levels))
        return levels

    def list_gpus(self) -> list[GpuInfo]:
        return [a.info for a in self._adapters]

    def read_telemetry(self, index: int) -> GpuTelemetry:
        a = self._adapters[index].adl_index
        t = GpuTelemetry(timestamp=time.monotonic())
        status = OdnPerformanceStatus()
        self._call("ADL2_OverdriveN_PerformanceStatus_Get", a, ctypes.byref(status))
        t.core_mhz = status.iCoreClock / 100
        t.mem_mhz = status.iMemoryClock / 100
        t.utilization = status.iGPUActivityPercent
        t.voltage_mv = status.iVDDC or None
        for kind, attr in ((ODN_TEMP_EDGE, "gpu_temp_c"), (ODN_TEMP_MEM, "vram_temp_c"),
                           (ODN_TEMP_HOTSPOT, "hotspot_temp_c")):
            value = c_int()
            try:
                self._call("ADL2_OverdriveN_Temperature_Get", a, kind, ctypes.byref(value))
                setattr(t, attr, value.value / 1000)
            except GpuBackendError:
                pass
        power = c_int()
        try:
            self._call("ADL2_Overdrive6_CurrentPower_Get", a, 0, ctypes.byref(power))
            t.power_w = (power.value >> 8)
        except GpuBackendError:
            pass
        fan = OdnFanControl()
        try:
            self._call("ADL2_OverdriveN_FanControl_Get", a, ctypes.byref(fan))
            if fan.iCurrentFanSpeedMode == 1:  # проценты
                t.fan_percent = fan.iCurrentFanSpeed
        except GpuBackendError:
            pass
        return t

    def apply(self, index: int, settings: OcSettings) -> None:
        adapter = self._adapters[index]
        sclk = OdnLevels.from_buffer_copy(adapter.default_sclk)
        mclk = OdnLevels.from_buffer_copy(adapter.default_mclk)
        sclk.iMode = mclk.iMode = ODN_CONTROL_MANUAL
        n = sclk.iNumberOfPerformanceLevels
        top = sclk.aLevels[n - 1]
        if settings.core_lock_mhz is not None:
            top.iClock = settings.core_lock_mhz * 100
        else:
            top.iClock += settings.core_offset_mhz * 100
        for i in range(n):
            level = sclk.aLevels[i]
            if level.iVddc > 0 and settings.voltage_offset_mv:
                level.iVddc = max(750, level.iVddc + settings.voltage_offset_mv)
        mtop = mclk.aLevels[mclk.iNumberOfPerformanceLevels - 1]
        mtop.iClock += settings.mem_offset_mhz * 100
        self._call("ADL2_OverdriveN_SystemClocks_Set", adapter.adl_index, ctypes.byref(sclk))
        self._call("ADL2_OverdriveN_MemoryClocks_Set", adapter.adl_index, ctypes.byref(mclk))

    def close(self) -> None:
        try:
            self._dll.ADL2_Main_Control_Destroy(self._ctx)
        except Exception:  # noqa: BLE001
            pass
