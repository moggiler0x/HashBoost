"""Настройки приложения и их хранение в JSON."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

UNIT_MULTIPLIERS = {"H/s": 1.0, "KH/s": 1e3, "MH/s": 1e6, "GH/s": 1e9, "TH/s": 1e12}


@dataclass
class AlgorithmConfig:
    """Алгоритм/монета и её текущая доходность."""

    name: str
    coin: str = ""
    # Доход в валюте за сутки с одной единицы хешрейта (например, ₽ за 1 MH/s в сутки)
    revenue_per_unit_day: float = 0.0
    unit: str = "MH/s"
    pool_fee_pct: float = 1.0
    # Опциональный источник доходности: URL, отдающий JSON, и путь к числу (a.b.0.c)
    price_api_url: str = ""
    price_json_path: str = ""

    @property
    def unit_multiplier(self) -> float:
        return UNIT_MULTIPLIERS.get(self.unit, 1.0)


@dataclass
class MinerConfig:
    kind: str = "srbminer"  # srbminer | rigel | generic | sim
    api_url: str = "http://127.0.0.1:21550"
    executable: str = ""
    args: str = ""
    algorithm: str = "poseidon2"
    # Для generic-клиента: пути к полям в JSON (см. miners/generic.py)
    json_map: dict[str, str] = field(default_factory=dict)


@dataclass
class TuningConfig:
    stabilization_s: float = 90.0  # ожидание стабилизации хешрейта на каждом шаге
    sample_interval_s: float = 5.0
    warmup_s: float = 20.0  # первые секунды после применения настроек не учитываются
    core_step_mhz: int = 15
    max_core_steps: int = 8
    mem_step_mhz: int = 50
    max_mem_steps: int = 10
    voltage_step_mv: int = 10
    min_voltage_offset_mv: int = -250
    safety_margin_mv: int = 20  # запас после найденного порога (+15..25 мВ)
    nvidia_mhz_per_mv: float = 1.2  # перевод мВ в смещение V/F-кривой для NVIDIA
    max_reject_ratio: float = 0.02
    max_invalid_per_step: int = 0
    max_hashrate_drop_pct: float = 8.0  # падение хешрейта = признак нестабильности
    profit_decline_patience: int = 2  # сколько шагов подряд терпим снижение профита
    min_gain_pct: float = 0.5  # меньший прирост прибыли считается шумом замера


@dataclass
class WatchdogConfig:
    enabled: bool = True
    max_gpu_temp_c: float = 83.0
    max_hotspot_temp_c: float = 100.0
    max_vram_temp_c: float = 100.0
    miner_timeout_s: float = 60.0
    max_invalid_per_minute: int = 1
    max_restarts_per_hour: int = 6


@dataclass
class AppConfig:
    tariff_per_kwh: float = 6.0
    currency: str = "₽"
    psu_efficiency: float = 0.9  # КПД блока питания: потребление из розетки = GPU / КПД
    rig_base_power_w: float = 60.0  # платформа: CPU, материнская плата, райзеры
    poll_interval_s: float = 2.0
    simulate: bool = False
    miner: MinerConfig = field(default_factory=MinerConfig)
    tuning: TuningConfig = field(default_factory=TuningConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    algorithms: dict[str, AlgorithmConfig] = field(
        default_factory=lambda: {
            "poseidon2": AlgorithmConfig("poseidon2", coin="Quantus", unit="MH/s", revenue_per_unit_day=0.1),
            "pearlhash": AlgorithmConfig("pearlhash", coin="Pearl", unit="MH/s", revenue_per_unit_day=0.7),
        }
    )

    def algorithm(self, name: str) -> AlgorithmConfig:
        if name not in self.algorithms:
            self.algorithms[name] = AlgorithmConfig(name)
        return self.algorithms[name]

    # --- сериализация ---
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name == "miner":
                value = _load_dc(MinerConfig, value)
            elif f.name == "tuning":
                value = _load_dc(TuningConfig, value)
            elif f.name == "watchdog":
                value = _load_dc(WatchdogConfig, value)
            elif f.name == "algorithms":
                value = {k: _load_dc(AlgorithmConfig, v) for k, v in value.items()}
            setattr(cfg, f.name, value)
        return cfg


def _load_dc(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def data_dir() -> Path:
    override = os.environ.get("HASHBOOST_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home())) / "HashBoost"
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hashboost"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        return AppConfig()
    with path.open(encoding="utf-8") as fh:
        return AppConfig.from_dict(json.load(fh))


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, ensure_ascii=False, indent=2)
    tmp.replace(path)
