"""Справочник видеокарт: хешрейт, потребление, цена и окупаемость по данным Kryptex.

Источник — рейтинг «Лучшие видеокарты для майнинга» и страницы карт на kryptex.com
(обновлено 23.10.2026). Цены и прибыль Kryptex указаны в долларах; окупаемость — в днях
при майнинге самой выгодной монеты. Хешрейты — в H/s.

Справочник нужен там, где своих замеров ещё нет: до калибровки программа оценивает
доходность карты на каждой монете по этим цифрам, после калибровки — по своим замерам.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

SOURCE = "Kryptex, рейтинг видеокарт от 23.10.2026"

MH = 1e6
TH = 1e12


@dataclass(frozen=True)
class CardReference:
    name: str
    price_usd: float
    power_w: float
    profit_usd_month: float  # прибыль по Kryptex на лучшей монете
    payback_days: int  # окупаемость по Kryptex
    hashrates: dict[str, float] = field(default_factory=dict)  # алгоритм → H/s

    @property
    def key(self) -> str:
        return normalize_name(self.name)


def _card(name: str, price: float, power: float, profit: float, payback: int,
          qtc_mh: float, prl_th: Optional[float]) -> CardReference:
    rates = {"poseidon2": qtc_mh * MH}
    if prl_th:
        rates["pearlhash"] = prl_th * TH
    return CardReference(name, price, power, profit, payback, rates)


# Потребление указано для карт, у которых Kryptex его публикует на странице карты;
# для остальных — типичная мощность платы (TGP/TBP) производителя.
CARDS: list[CardReference] = [
    _card("RTX 5070", 850, 250, 104.47, 252, 570, 124),
    _card("RTX 5060 Ti", 700, 180, 76.88, 282, 426, 91),
    _card("RTX 5060", 450, 145, 64.17, 217, 347, 76),
    _card("RTX 4070", 550, 200, 95.17, 178, 514, 113),
    _card("RTX 4060 Ti", 380, 160, 72.54, 162, 381, 86),
    _card("RTX 4060", 299, 115, 54.87, 169, 278, 65),
    _card("RTX 3080", 350, 320, 88.66, 122, 488, 105),
    _card("RTX 3070", 280, 220, 61.69, 141, 344, 73),
    _card("RTX 3060 Ti", 220, 200, 51.46, 132, 283, 61),
    _card("RTX 3060", 150, 170, 39.68, 117, 221, 47),
    _card("GTX 1660 Ti", 115, 120, 22.63, 157, 178, 1.1),
    _card("GTX 1660 SUPER", 100, 75, 20.77, 148, 164, 1.0),
    _card("GTX 1650", 80, 70, 13.02, 189, 103, 0.65),
    _card("CMP 30HX", 60, 125, 20.46, 90, 161, 1.0),
    _card("RX 7600", 270, 165, 17.67, 472, 139, 17.5),
    _card("RX 6600", 150, 132, 16.12, 287, 127, 8.8),
    _card("RX 580", 75, 185, 10.54, 219, 83, None),
    _card("RX 570", 70, 130, 8.99, 243, 70, None),  # PearlHash на Polaris не поддерживается
]

_NOISE = re.compile(r"\b(nvidia|geforce|amd|radeon|series|graphics|laptop gpu)\b")


def normalize_name(name: str) -> str:
    """«NVIDIA GeForce GTX 1660 SUPER» → «gtx 1660 super», «Radeon RX 570 Series» → «rx 570»."""
    text = _NOISE.sub(" ", name.lower())
    text = re.sub(r"\b(\d+)\s*gb\b", " ", text)
    return " ".join(text.split())


_BY_KEY = {c.key: c for c in CARDS}


def find_card(gpu_name: str) -> Optional[CardReference]:
    """Ищет карту в справочнике по имени из драйвера. Точное совпадение модели:
    «RTX 4060» не должна найтись как «RTX 4060 Ti» и наоборот."""
    return _BY_KEY.get(normalize_name(gpu_name))
