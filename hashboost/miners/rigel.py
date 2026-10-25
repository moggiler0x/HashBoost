"""Rigel (и совместимые форки, например PeakMiner): HTTP API (``--api-bind 127.0.0.1:5000``).

Ожидаемая структура::

    {
      "algorithm": "...", "uptime": 1234,
      "devices": [{
        "id": 0, "selected": true,
        "hashrate": {"<algo>": 5.0e7},
        "shares": {"<algo>": {"accepted": 5, "rejected": 0, "stale": 0, "invalid": 0}}
      }]
    }
"""
from __future__ import annotations

from typing import Any

from ..models import GpuMinerStats, MinerStats
from .base import MinerApiError, MinerClient, now, num


def _first_value(value: Any, key: str) -> Any:
    """Поле может быть числом или словарём «алгоритм → значение»."""
    if isinstance(value, dict):
        if key in value:
            return value[key]
        return next(iter(value.values()), None)
    return value


class RigelClient(MinerClient):
    name = "Rigel/PeakMiner"

    def parse(self, payload: Any) -> MinerStats:
        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list):
            raise MinerApiError("Rigel: в ответе нет devices")
        algo = str(payload.get("algorithm", ""))
        stats = MinerStats(timestamp=now(), algorithm=algo, uptime_s=num(payload.get("uptime")))
        for pos, dev in enumerate(devices):
            if dev.get("selected") is False:
                continue
            idx = int(num(dev.get("id", pos), pos))
            shares = dev.get("shares") or {}
            if "accepted" not in shares:  # счётчики сгруппированы по алгоритмам
                shares = _first_value(shares, algo) or {}
            stats.gpus[idx] = GpuMinerStats(
                hashrate=num(_first_value(dev.get("hashrate"), algo)),
                hashrate_avg=num(_first_value(dev.get("hashrate_avg", dev.get("hashrate")), algo)),
                accepted=int(num(shares.get("accepted"))),
                rejected=int(num(shares.get("rejected"))),
                stale=int(num(shares.get("stale"))),
                invalid=int(num(shares.get("invalid", shares.get("hw_errors")))),
            )
        return stats
