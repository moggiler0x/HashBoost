"""Майнер-симулятор поверх SimulatedRig."""
from __future__ import annotations

from typing import Any

from ..hardware.simulator import SimulatedRig
from ..models import MinerStats
from .base import MinerApiError, MinerClient
from .process import MinerController


class SimulatedMinerClient(MinerClient):
    name = "Симулятор майнера"

    def __init__(self, rig: SimulatedRig):
        super().__init__("sim://")
        self.rig = rig

    def fetch(self) -> MinerStats:
        if not self.rig.miner_running:
            raise MinerApiError("Симулятор: майнер остановлен")
        return self.parse(None)

    def parse(self, payload: Any) -> MinerStats:
        now = self.rig.clock.now()
        return MinerStats(timestamp=now, algorithm=self.rig.algorithm,
                          uptime_s=now - self.rig.miner_started_at, gpus=self.rig.miner_snapshot())


class SimulatedMinerController(MinerController):
    def __init__(self, rig: SimulatedRig):
        self.rig = rig

    def start(self) -> None:
        self.rig.restart_miner()

    def stop(self) -> None:
        self.rig.stop_miner()

    def restart(self) -> None:
        self.rig.restart_miner()

    def is_running(self) -> bool:
        return self.rig.miner_running
