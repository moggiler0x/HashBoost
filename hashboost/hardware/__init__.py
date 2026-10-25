"""Драйверный слой: NVML (NVIDIA), ADL (AMD) и симулятор."""
from .base import Capabilities, GpuBackend, GpuBackendError
from .manager import GpuHandle, Rig, detect_backends

__all__ = ["Capabilities", "GpuBackend", "GpuBackendError", "GpuHandle", "Rig", "detect_backends"]
