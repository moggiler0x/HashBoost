"""SRBMiner-MULTI: встроенный HTTP API (запуск майнера с ``--api-enable --api-port 21550``).

Формат ответа у разных версий отличается, поэтому разбор терпим к отсутствию полей.
Ожидаемая структура::

    {
      "mining_time": 1234,
      "algorithms": [{
        "name": "...",
        "hashrate": {"gpu": {"total": 1.0e8, "gpu0": 5.0e7, "gpu1": 5.0e7}},
        "shares": {"accepted": 10, "rejected": 0,
                   "gpu0": {"accepted": 5, "rejected": 0, "hw_errors": 0}}
      }],
      "gpu_devices": [{"device_id": 0, "hardware_errors": 0}]
    }
"""
from __future__ import annotations

import re
from typing import Any

from ..models import GpuMinerStats, MinerStats
from .base import MinerApiError, MinerClient, dig, now, num

_GPU_KEY = re.compile(r"^gpu(\d+)$")


class SrbMinerClient(MinerClient):
    name = "SRBMiner-MULTI"

    def parse(self, payload: Any) -> MinerStats:
        algos = dig(payload, "algorithms")
        if not isinstance(algos, list) or not algos:
            raise MinerApiError("SRBMiner: в ответе нет algorithms")
        algo = algos[0]
        stats = MinerStats(timestamp=now(), algorithm=str(algo.get("name", "")),
                           uptime_s=num(payload.get("mining_time")))

        rates = dig(algo, "hashrate.gpu") or dig(algo, "hashrate") or {}
        avg_rates = dig(algo, "hashrate_avg.gpu") or dig(algo, "hashrate_5min.gpu") or {}
        if isinstance(rates, dict):
            for key, value in rates.items():
                m = _GPU_KEY.match(str(key))
                if m:
                    idx = int(m.group(1))
                    stats.gpus[idx] = GpuMinerStats(hashrate=num(value), hashrate_avg=num(avg_rates.get(key, value)))

        shares = algo.get("shares") or {}
        for idx, gpu in stats.gpus.items():
            per = shares.get(f"gpu{idx}") or {}
            gpu.accepted = int(num(per.get("accepted")))
            gpu.rejected = int(num(per.get("rejected")))
            gpu.invalid = int(num(per.get("hw_errors", per.get("invalid"))))

        for dev in payload.get("gpu_devices") or []:
            idx = int(num(dev.get("device_id", dev.get("id", -1)), -1))
            if idx in stats.gpus and "hardware_errors" in dev:
                stats.gpus[idx].invalid = max(stats.gpus[idx].invalid, int(num(dev["hardware_errors"])))
        return stats
