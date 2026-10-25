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
    # Комиссия пула. Цифры Kryptex уже за вычетом комиссии, поэтому по умолчанию 0
    pool_fee_pct: float = 0.0
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
    # Аргументы командной строки для каждого алгоритма: нужны, чтобы мульти-калибровка
    # могла сама перезапускать майнер на другой монете. Пусто — используется ``args``.
    algo_args: dict[str, str] = field(default_factory=dict)
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


# Доходность по умолчанию посчитана по реальным выплатам Kryptex 5.10.7 на ригах автора (25.10.2026):
# * qtc (Poseidon2): GTX 1660 SUPER 138.02 MH/s → 1269.87 ₽/мес, 137.80 MH/s → 1267.83 ₽/мес,
#   GTX 1650 102.32 MH/s → 941.39 ₽/мес. Все три дают 9.20 ₽/мес = 0.3067 ₽/сут за 1 MH/s.
# * prl (PearlHash): RTX 4060 61.56 TH/s → 3719.92 ₽/мес = 2.0142 ₽/сут за 1 TH/s.
# Это грязный доход (до вычета электричества). Цифры меняются вместе с курсом и сложностью сети.
QTC_RUB_PER_MH_DAY = 0.3067
PRL_RUB_PER_TH_DAY = 2.0142

# Тарифы Москвы с 01.10.2026 (₽/кВт·ч), городские квартиры с газовой плитой.
# Ночь 23:00–07:00, день 07:00–23:00.
TARIFF_PRESETS: dict[str, tuple[float, float, float]] = {
    # название: (однотарифный, день, ночь)
    "Москва, квартира с газовой плитой": (8.90, 10.64, 4.85),
    "Москва, квартира с электроплитой": (8.46, 10.11, 4.61),
    "Москва, сельские н.п. и СНТ": (8.28, 9.90, 4.51),
}
DEFAULT_TARIFF = TARIFF_PRESETS["Москва, квартира с газовой плитой"]

# Курс ЦБ РФ на 24.10.2026: нужен, чтобы перевести цены карт из рейтинга Kryptex (в $) в рубли
USD_RATE = 80.5381


def default_algorithms() -> dict[str, "AlgorithmConfig"]:
    return {
        "poseidon2": AlgorithmConfig("poseidon2", coin="Quantus (QTC)", unit="MH/s",
                                     revenue_per_unit_day=QTC_RUB_PER_MH_DAY),
        "pearlhash": AlgorithmConfig("pearlhash", coin="Pearl (PRL)", unit="TH/s",
                                     revenue_per_unit_day=PRL_RUB_PER_TH_DAY),
    }


@dataclass
class AppConfig:
    # Режим тарифа: "single" — однотарифный счётчик, "dual" — двухтарифный (день/ночь)
    tariff_mode: str = "single"
    tariff_per_kwh: float = DEFAULT_TARIFF[0]
    tariff_day: float = DEFAULT_TARIFF[1]
    tariff_night: float = DEFAULT_TARIFF[2]
    night_start_hour: int = 23
    night_end_hour: int = 7
    currency: str = "₽"
    usd_rate: float = USD_RATE
    # Цена каждой карты (по uid) для расчёта окупаемости; нет записи — цена из рейтинга Kryptex
    card_prices: dict[str, float] = field(default_factory=dict)
    psu_efficiency: float = 0.9  # КПД блока питания: потребление из розетки = GPU / КПД
    rig_base_power_w: float = 60.0  # платформа: CPU, материнская плата, райзеры
    poll_interval_s: float = 2.0
    simulate: bool = False
    miner: MinerConfig = field(default_factory=MinerConfig)
    tuning: TuningConfig = field(default_factory=TuningConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    algorithms: dict[str, AlgorithmConfig] = field(default_factory=default_algorithms)

    @property
    def night_hours(self) -> int:
        return (self.night_end_hour - self.night_start_hour) % 24

    def effective_tariff(self) -> float:
        """Средняя цена кВт·ч при круглосуточной работе рига."""
        if self.tariff_mode != "dual":
            return self.tariff_per_kwh
        night = self.night_hours
        return (self.tariff_day * (24 - night) + self.tariff_night * night) / 24

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
                value = {k: _upgrade_algo(_load_dc(AlgorithmConfig, v)) for k, v in value.items()}
            setattr(cfg, f.name, value)
        if "tariff_mode" not in data and data.get("tariff_per_kwh") == 6.0:
            cfg.tariff_per_kwh = DEFAULT_TARIFF[0]  # заглушка первой версии → реальный тариф
        return cfg


# Доходности-заглушки из первой версии: в сохранённых настройках заменяем их реальными
_LEGACY_ALGOS = {("poseidon2", "MH/s", 0.1), ("pearlhash", "MH/s", 0.7)}


def _upgrade_algo(algo: AlgorithmConfig) -> AlgorithmConfig:
    if (algo.name, algo.unit, algo.revenue_per_unit_day) in _LEGACY_ALGOS:
        fresh = default_algorithms()[algo.name]
        fresh.price_api_url, fresh.price_json_path = algo.price_api_url, algo.price_json_path
        return fresh
    return algo


def _load_dc(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def data_dir() -> Path:
    override = os.environ.get("HASHBOOST_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home())) / "HashBoost"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "HashBoost"
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
