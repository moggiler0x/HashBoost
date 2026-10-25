"""Управление процессом майнера: запуск, остановка, перезапуск."""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


class MinerController:
    """Интерфейс управления майнером (реальный процесс или симулятор)."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def restart(self) -> None:
        self.stop()
        self.start()

    def is_running(self) -> bool:
        return True


class ExternalMiner(MinerController):
    """Майнер, которым управляет пользователь сам: HashBoost только читает его API."""


class MinerProcess(MinerController):
    def __init__(self, executable: str, args: str = ""):
        self.executable = executable
        self.args = args
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.is_running():
            return
        exe = Path(self.executable)
        if not exe.exists():
            raise FileNotFoundError(f"Майнер не найден: {exe}")
        cmd = [str(exe), *shlex.split(self.args, posix=sys.platform != "win32")]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform == "win32" else 0
        log.info("Запуск майнера: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, cwd=str(exe.parent), creationflags=flags)

    def stop(self) -> None:
        if not self._proc:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
