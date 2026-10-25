"""Интеграция с майнерами: клиенты API и управление процессом."""
from __future__ import annotations

from ..config import MinerConfig
from .base import MinerApiError, MinerClient
from .generic import GenericJsonClient
from .process import ExternalMiner, MinerController, MinerProcess
from .rigel import RigelClient
from .srbminer import SrbMinerClient

MINER_KINDS = {
    "srbminer": "SRBMiner-MULTI",
    "rigel": "Rigel / PeakMiner",
    "generic": "Другой (JSON API)",
}


def create_miner(cfg: MinerConfig, sim_rig=None) -> tuple[MinerClient, MinerController]:
    if sim_rig is not None:
        from .simulated import SimulatedMinerClient, SimulatedMinerController

        return SimulatedMinerClient(sim_rig), SimulatedMinerController(sim_rig)
    if cfg.kind == "rigel":
        client: MinerClient = RigelClient(cfg.api_url)
    elif cfg.kind == "generic":
        client = GenericJsonClient(cfg.api_url, cfg.json_map)
    else:
        client = SrbMinerClient(cfg.api_url)
    args = cfg.algo_args.get(cfg.algorithm) or cfg.args
    controller = MinerProcess(cfg.executable, args) if cfg.executable else ExternalMiner()
    return client, controller


__all__ = ["MINER_KINDS", "MinerApiError", "MinerClient", "MinerController", "create_miner"]
