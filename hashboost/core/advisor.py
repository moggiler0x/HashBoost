"""Подбор самой выгодной монеты для каждой карты и срок окупаемости.

Для каждой пары «карта × алгоритм» берётся лучший источник данных:
1. свой профиль после калибровки (реальный хешрейт и потребление этой карты);
2. справочник Kryptex (типичные цифры модели), если карту на этом алгоритме ещё не калибровали.
Доход и свет считаются по текущим настройкам калькулятора, поэтому смена тарифа
или доходности монеты сразу меняет рекомендацию.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..config import AppConfig
from ..models import GpuInfo
from .market import find_card
from .profiles import ProfileStore
from .profit import ProfitBreakdown, ProfitEngine, payback_days

SOURCE_TUNED = "калибровка"
SOURCE_KRYPTEX = "Kryptex"


@dataclass
class AlgoEstimate:
    algorithm: str
    coin: str
    hashrate: float
    power_w: float
    source: str
    profit: ProfitBreakdown


@dataclass
class CardAdvice:
    gpu: GpuInfo
    price: float  # в валюте калькулятора; 0 — неизвестна
    estimates: list[AlgoEstimate] = field(default_factory=list)  # по убыванию чистой прибыли

    @property
    def best(self) -> Optional[AlgoEstimate]:
        return self.estimates[0] if self.estimates else None

    @property
    def payback_days(self) -> Optional[float]:
        best = self.best
        if best is None or self.price <= 0:
            return None
        return payback_days(self.price, best.profit.net_per_day)

    def advantage(self) -> float:
        """На сколько лучшая монета выгоднее следующей, в валюте в сутки."""
        if len(self.estimates) < 2:
            return 0.0
        return self.estimates[0].profit.net_per_day - self.estimates[1].profit.net_per_day


def card_price(cfg: AppConfig, gpu: GpuInfo) -> float:
    """Цена карты: введённая пользователем, иначе цена из рейтинга Kryptex по курсу."""
    if gpu.uid in cfg.card_prices:
        return cfg.card_prices[gpu.uid]
    ref = find_card(gpu.name)
    return round(ref.price_usd * cfg.usd_rate) if ref else 0.0


def advise_card(cfg: AppConfig, engine: ProfitEngine, gpu: GpuInfo, profiles: Optional[ProfileStore]) -> CardAdvice:
    ref = find_card(gpu.name)
    advice = CardAdvice(gpu, card_price(cfg, gpu))
    for name, algo in cfg.algorithms.items():
        profile = profiles.get(gpu.uid, name) if profiles else None
        if profile and profile.hashrate > 0:
            hashrate, power, source = profile.hashrate, profile.power_w, SOURCE_TUNED
        elif ref and ref.hashrates.get(name):
            hashrate, power, source = ref.hashrates[name], ref.power_w, SOURCE_KRYPTEX
        else:
            continue
        advice.estimates.append(AlgoEstimate(name, algo.coin or name, hashrate, power, source,
                                             engine.evaluate(name, hashrate, power)))
    advice.estimates.sort(key=lambda e: e.profit.net_per_day, reverse=True)
    return advice


def advise(cfg: AppConfig, engine: ProfitEngine, gpus: Iterable[GpuInfo],
           profiles: Optional[ProfileStore] = None) -> list[CardAdvice]:
    return [advise_card(cfg, engine, gpu, profiles) for gpu in gpus]


def best_rig_algorithm(advice: list[CardAdvice]) -> Optional[tuple[str, float]]:
    """Алгоритм с максимальной суммарной прибылью, если весь риг майнит одну монету.

    Карта, которая алгоритм не тянет, в сумме даёт ноль (её лучше выключить)."""
    totals: dict[str, float] = {}
    for card in advice:
        for est in card.estimates:
            totals[est.algorithm] = totals.get(est.algorithm, 0.0) + max(0.0, est.profit.net_per_day)
    if not totals:
        return None
    name = max(totals, key=totals.get)
    return name, totals[name]
