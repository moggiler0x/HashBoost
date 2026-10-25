"""Универсальный клиент: любой майнер с JSON API через карту путей к полям.

Пример ``json_map`` в config.json::

    {"gpus": "devices", "index": "id", "hashrate": "speed", "hashrate_avg": "avg",
     "accepted": "shares.ok", "rejected": "shares.bad", "invalid": "hw", "algorithm": "algo"}
"""
from __future__ import annotations

from typing import Any

from ..models import GpuMinerStats, MinerStats
from .base import MinerApiError, MinerClient, dig, now, num


class GenericJsonClient(MinerClient):
    name = "JSON API"

    def __init__(self, api_url: str, json_map: dict[str, str], timeout: float = 3.0):
        super().__init__(api_url, timeout)
        self.map = {"gpus": "gpus", "index": "", "hashrate": "hashrate", **json_map}

    def parse(self, payload: Any) -> MinerStats:
        gpus = dig(payload, self.map["gpus"])
        if not isinstance(gpus, list):
            raise MinerApiError(f"JSON API: по пути '{self.map['gpus']}' нет списка карт")
        stats = MinerStats(timestamp=now())
        if self.map.get("algorithm"):
            stats.algorithm = str(dig(payload, self.map["algorithm"], "") or "")
        if self.map.get("uptime"):
            stats.uptime_s = num(dig(payload, self.map["uptime"]))
        for pos, item in enumerate(gpus):
            idx = int(num(dig(item, self.map["index"]), pos)) if self.map["index"] else pos
            field = lambda key: num(dig(item, self.map[key])) if self.map.get(key) else 0.0  # noqa: E731
            hashrate = field("hashrate")
            stats.gpus[idx] = GpuMinerStats(
                hashrate=hashrate,
                hashrate_avg=field("hashrate_avg") or hashrate,
                accepted=int(field("accepted")),
                rejected=int(field("rejected")),
                stale=int(field("stale")),
                invalid=int(field("invalid")),
            )
        return stats
