"""Мульти-калибровка: одна карта последовательно калибруется на нескольких алгоритмах,
после чего выбирается монета с максимальной чистой прибылью.

Зачем: «кремниевая лотерея» и архитектура решают, что выгоднее. Например, RTX 4060
на PearlHash (тензорные ядра) зарабатывает заметно больше, чем на Poseidon2, а GTX 1660 SUPER
без тензорных ядер — наоборот.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clock import Clock
from .autotune import AutoTuner, TuneCancelled, TuneFailed, TunerCallbacks, TuneResult
from .market import find_card


@dataclass
class MultiTuneResult:
    gpu_index: int
    results: dict[str, TuneResult] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def ranking(self) -> list[TuneResult]:
        return sorted(self.results.values(), key=lambda r: r.final.net_per_day, reverse=True)

    @property
    def best(self) -> Optional[TuneResult]:
        ranking = self.ranking
        return ranking[0] if ranking else None


class MultiAlgoTuner:
    """Прогоняет :class:`AutoTuner` по списку алгоритмов.

    ``make_tuner(algorithm)`` создаёт калибровщик на нужный алгоритм,
    ``switch_algorithm(algorithm)`` перезапускает майнер на нужной монете.
    """

    def __init__(self, algorithms: list[str], make_tuner: Callable[[str], AutoTuner],
                 switch_algorithm: Callable[[str], None], clock: Clock | None = None,
                 callbacks: TunerCallbacks | None = None, settle_s: float = 0.0,
                 on_algorithm: Callable[[int, str], None] = lambda idx, name: None):
        if not algorithms:
            raise ValueError("не выбран ни один алгоритм")
        self.algorithms = list(algorithms)
        self.make_tuner = make_tuner
        self.switch_algorithm = switch_algorithm
        self.clock = clock or Clock()
        self.cb = callbacks or TunerCallbacks()
        self.settle_s = settle_s
        self.on_algorithm = on_algorithm
        self.stop_event = threading.Event()
        self.current: Optional[AutoTuner] = None

    def cancel(self) -> None:
        self.stop_event.set()
        if self.current:
            self.current.cancel()

    def run(self, gpu: int) -> MultiTuneResult:
        result = MultiTuneResult(gpu)
        for idx, algorithm in enumerate(self.algorithms):
            if self.stop_event.is_set():
                raise TuneCancelled()
            self.on_algorithm(idx, algorithm)
            self.cb.on_log(f"### Алгоритм {idx + 1}/{len(self.algorithms)}: {algorithm}")
            tuner = self.make_tuner(algorithm)
            ref = find_card(tuner.rig[gpu].info.name)
            if ref is not None and algorithm not in ref.hashrates:
                result.failures[algorithm] = "карта не майнит этот алгоритм (по данным Kryptex)"
                self.cb.on_log(f"{algorithm}: пропуск — {result.failures[algorithm]}")
                continue
            try:
                self.switch_algorithm(algorithm)
            except Exception as exc:  # noqa: BLE001 - ошибка запуска майнера не должна ронять остальные монеты
                result.failures[algorithm] = f"не удалось переключить майнер: {exc}"
                self.cb.on_log(result.failures[algorithm])
                continue
            if self.settle_s and not self.clock.sleep(self.settle_s, self.stop_event):
                raise TuneCancelled()
            self.current = tuner
            if self.stop_event.is_set():
                self.current.cancel()
            try:
                result.results[algorithm] = self.current.run(gpu)
            except TuneFailed as exc:
                result.failures[algorithm] = str(exc)
                self.cb.on_log(f"{algorithm}: калибровка не удалась — {exc}")
        self.cb.on_log(self.summary(result))
        return result

    @staticmethod
    def summary(result: MultiTuneResult) -> str:
        lines = ["Сравнение монет:"]
        for i, r in enumerate(result.ranking):
            mark = "★" if i == 0 else " "
            lines.append(f" {mark} {r.algorithm}: чистыми {r.final.net_per_day:.2f}/сут "
                         f"(доход {r.final.revenue_per_day:.2f}, свет {r.final.cost_per_day:.2f}, "
                         f"{r.final.power_w:.0f} Вт)")
        for algorithm, reason in result.failures.items():
            lines.append(f"   {algorithm}: нет результата — {reason}")
        if result.best is None:
            lines.append("Ни на одном алгоритме калибровка не удалась")
        elif result.best.final.net_per_day < 0:
            lines.append("Карта убыточна на всех монетах при текущем тарифе — выгоднее её выключить")
        return "\n".join(lines)
