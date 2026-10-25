"""Profit-per-Watt Engine: считает чистую прибыль с учётом цены розетки."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional

from ..config import AlgorithmConfig, AppConfig
from ..miners.base import dig, num
from ..models import BenchmarkSample

HOURS_PER_DAY = 24
DAYS_PER_MONTH = 30


@dataclass
class ProfitBreakdown:
    revenue_per_day: float
    cost_per_day: float
    wall_power_w: float

    @property
    def net_per_day(self) -> float:
        return self.revenue_per_day - self.cost_per_day

    @property
    def net_per_month(self) -> float:
        return self.net_per_day * DAYS_PER_MONTH

    @property
    def revenue_per_month(self) -> float:
        return self.revenue_per_day * DAYS_PER_MONTH

    @property
    def cost_per_month(self) -> float:
        return self.cost_per_day * DAYS_PER_MONTH

    def __add__(self, other: "ProfitBreakdown") -> "ProfitBreakdown":
        return ProfitBreakdown(self.revenue_per_day + other.revenue_per_day,
                               self.cost_per_day + other.cost_per_day,
                               self.wall_power_w + other.wall_power_w)


class ProfitEngine:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def wall_power(self, gpu_power_w: float) -> float:
        """Потребление из розетки с учётом КПД блока питания."""
        return gpu_power_w / max(self.cfg.psu_efficiency, 0.01)

    def cost_per_day(self, gpu_power_w: float) -> float:
        """Свет за сутки круглосуточной работы; при двухтарифном счётчике — по средней цене дня и ночи."""
        return self.wall_power(gpu_power_w) * HOURS_PER_DAY / 1000 * self.cfg.effective_tariff()

    def revenue_per_day(self, algorithm: str, hashrate: float) -> float:
        algo = self.cfg.algorithm(algorithm)
        units = hashrate / algo.unit_multiplier
        return units * algo.revenue_per_unit_day * (1 - algo.pool_fee_pct / 100)

    def evaluate(self, algorithm: str, hashrate: float, gpu_power_w: float) -> ProfitBreakdown:
        return ProfitBreakdown(self.revenue_per_day(algorithm, hashrate), self.cost_per_day(gpu_power_w),
                               self.wall_power(gpu_power_w))

    def night_only(self, total: ProfitBreakdown) -> ProfitBreakdown:
        """Тот же риг, но работающий только в ночную зону двухтарифного счётчика."""
        hours = self.cfg.night_hours
        return ProfitBreakdown(total.revenue_per_day * hours / HOURS_PER_DAY,
                               total.wall_power_w * hours / 1000 * self.cfg.tariff_night, total.wall_power_w)

    def rig_total(self, items: Iterable[tuple[str, float, float]]) -> ProfitBreakdown:
        """Итог по ригу: сумма по картам плюс потребление платформы."""
        total = ProfitBreakdown(0.0, 0.0, 0.0)
        for algorithm, hashrate, power in items:
            total = total + self.evaluate(algorithm, hashrate, power)
        base = self.cfg.rig_base_power_w
        return total + ProfitBreakdown(0.0, self.cost_per_day(base), self.wall_power(base))

    def score(self, algorithm: str, sample: BenchmarkSample) -> BenchmarkSample:
        """Дописывает в замер доход и расходы."""
        p = self.evaluate(algorithm, sample.hashrate, sample.power_w)
        sample.revenue_per_day = p.revenue_per_day
        sample.cost_per_day = p.cost_per_day
        return sample

    @staticmethod
    def best(samples: Iterable[BenchmarkSample]) -> Optional[BenchmarkSample]:
        """Точка максимальной чистой прибыли среди стабильных замеров.

        При почти равной прибыли (в пределах 0,5 %) берётся более экономичная точка:
        меньше нагрев и износ при той же выгоде.
        """
        stable = [s for s in samples if s.stable and s.hashrate > 0]
        if not stable:
            return None
        top = max(s.net_per_day for s in stable)
        tolerance = abs(top) * 0.005
        near = [s for s in stable if s.net_per_day >= top - tolerance]
        return min(near, key=lambda s: s.power_w)


def payback_days(price: float, net_per_day: float) -> Optional[float]:
    """Сколько дней карта отбивает свою цену чистой прибылью. ``None`` — не окупится."""
    if price <= 0:
        return 0.0
    if net_per_day <= 0:
        return None
    return price / net_per_day


def fetch_revenue(algo: AlgorithmConfig, timeout: float = 10.0) -> float:
    """Подтягивает доходность (валюта за единицу хешрейта в сутки) по URL из настроек."""
    if not algo.price_api_url:
        raise ValueError("для алгоритма не задан URL доходности")
    req = urllib.request.Request(algo.price_api_url, headers={"User-Agent": "HashBoost"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    value = dig(payload, algo.price_json_path)
    if value is None:
        raise ValueError(f"в ответе нет поля '{algo.price_json_path}'")
    return num(value)
