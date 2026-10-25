"""Источник времени. Позволяет ускорять калибровку в режиме симуляции и тестах."""
from __future__ import annotations

import threading
import time


class Clock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float, stop: threading.Event | None = None) -> bool:
        """Спит ``seconds``. Возвращает ``False``, если ожидание прервано через ``stop``."""
        if stop is None:
            time.sleep(seconds)
            return True
        return not stop.wait(seconds)


class ScaledClock(Clock):
    """Виртуальное время, идущее в ``scale`` раз быстрее реального."""

    def __init__(self, scale: float = 30.0):
        self.scale = scale
        self._origin_real = time.monotonic()

    def now(self) -> float:
        return (time.monotonic() - self._origin_real) * self.scale

    def sleep(self, seconds: float, stop: threading.Event | None = None) -> bool:
        return super().sleep(seconds / self.scale, stop)


class ManualClock(Clock):
    """Полностью ручное время для юнит-тестов: ``sleep`` мгновенно двигает часы."""

    def __init__(self, start: float = 0.0):
        self._t = start
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._t

    def sleep(self, seconds: float, stop: threading.Event | None = None) -> bool:
        if stop is not None and stop.is_set():
            return False
        with self._lock:
            self._t += seconds
        return True
