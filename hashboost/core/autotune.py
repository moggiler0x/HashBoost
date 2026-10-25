"""Smart Auto-Tune: цикл калибровки одной карты.

Фазы:
1. Базовый замер на стоковых настройках.
2. Поиск частоты ядра: фиксация частоты (curve lock) с шагом вниз и вверх от стока,
   пока чистая прибыль растёт. Грубый шаг, затем уточнение вокруг лучшей точки.
3. Поиск частоты памяти: смещение вверх; если прибыль не растёт — вниз
   (для алгоритмов, зависящих от ядра, сниженная память экономит ватты).
4. Андервольтинг: при зафиксированной частоте напряжение снижается до порога
   нестабильности, затем возвращается на запас безопасности (+15..25 мВ).
5. Проверка: длинный замер итоговых настроек.

На каждом шаге настройки применяются, первые ``warmup_s`` секунд отбрасываются,
затем ``stabilization_s`` секунд снимается хешрейт и потребление. Шаг считается
нестабильным при аппаратных ошибках, отвале карты, перегреве или проседании хешрейта.
"""
from __future__ import annotations

import logging
import statistics
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clock import Clock
from ..config import TuningConfig, WatchdogConfig
from ..hardware import GpuBackendError, Rig
from ..miners import MinerApiError, MinerClient, MinerController
from ..models import BenchmarkSample, OcSettings, format_hashrate
from .profit import ProfitEngine
from .watchdog import HealthMonitor, Severity

log = logging.getLogger(__name__)

PHASES = ["Базовый замер", "Частота ядра", "Частота памяти", "Андервольтинг", "Проверка"]
COARSE_FACTOR = 4  # грубый шаг частоты ядра = core_step_mhz * 4
VERIFY_ATTEMPTS = 3


class TuneCancelled(Exception):
    pass


class TuneFailed(Exception):
    pass


@dataclass
class TuneResult:
    gpu_index: int
    algorithm: str
    baseline: BenchmarkSample
    final: BenchmarkSample
    samples: list[BenchmarkSample] = field(default_factory=list)

    @property
    def gain_per_day(self) -> float:
        return self.final.net_per_day - self.baseline.net_per_day


@dataclass
class TunerCallbacks:
    on_log: Callable[[str], None] = lambda msg: None
    on_sample: Callable[[BenchmarkSample], None] = lambda s: None
    on_phase: Callable[[int, str], None] = lambda idx, name: None


class AutoTuner:
    def __init__(self, rig: Rig, miner: MinerClient, controller: MinerController, profit: ProfitEngine,
                 tuning: TuningConfig, watchdog_cfg: WatchdogConfig, algorithm: str,
                 clock: Clock | None = None, callbacks: TunerCallbacks | None = None):
        self.rig = rig
        self.miner = miner
        self.controller = controller
        self.profit = profit
        self.cfg = tuning
        self.health = HealthMonitor(watchdog_cfg)
        self.algorithm = algorithm
        self.clock = clock or Clock()
        self.cb = callbacks or TunerCallbacks()
        self.stop_event = threading.Event()
        self.samples: list[BenchmarkSample] = []
        self._last_stable = OcSettings()

    def cancel(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------ helpers
    def _log(self, msg: str) -> None:
        log.info(msg)
        self.cb.on_log(msg)

    def _sleep(self, seconds: float) -> None:
        if not self.clock.sleep(seconds, self.stop_event):
            raise TuneCancelled()

    def _fetch(self):
        try:
            return self.miner.fetch()
        except MinerApiError:
            return None

    def measure(self, gpu: int, settings: OcSettings, phase: str, duration: float | None = None,
                reference_hashrate: float | None = None) -> BenchmarkSample:
        """Применяет настройки, ждёт стабилизации и снимает усреднённый замер."""
        if self.stop_event.is_set():
            raise TuneCancelled()
        duration = duration or self.cfg.stabilization_s
        try:
            self.rig.apply(gpu, settings)
        except GpuBackendError as exc:
            sample = self._record(BenchmarkSample(phase, settings, 0.0, 0.0, False, note=f"драйвер: {exc}"))
            self._recover(gpu, sample.note)
            return sample

        self._sleep(self.cfg.warmup_s)
        start_stats = self._fetch()
        start_gpu = start_stats.gpus.get(gpu) if start_stats else None
        hashrates: list[float] = []
        powers: list[float] = []
        reason = ""
        elapsed = 0.0
        prev_stats, prev_gpu = start_stats, start_gpu
        while elapsed < duration:
            self._sleep(self.cfg.sample_interval_s)
            elapsed += self.cfg.sample_interval_s
            try:
                telemetry = self.rig.read(gpu)
            except GpuBackendError as exc:
                reason = f"драйвер: {exc}"
                break
            temp_issues = [i for i in self.health.check_temps(gpu, telemetry) if i.severity >= Severity.CRITICAL]
            if temp_issues:
                reason = temp_issues[0].message
                break
            stats = self._fetch()
            if stats is None:
                reason = "майнер не отвечает"
                break
            cur = stats.gpus.get(gpu)
            dt = stats.timestamp - prev_stats.timestamp if prev_stats else 0.0
            issues = self.health.check_mining(gpu, prev_gpu, cur, dt, True)
            crash = [i for i in issues if i.severity >= Severity.CRITICAL]
            if crash:
                reason = crash[0].message
                break
            if cur is not None and start_gpu is not None and cur.invalid - start_gpu.invalid > self.cfg.max_invalid_per_step:
                reason = f"аппаратные ошибки: +{cur.invalid - start_gpu.invalid}"
                break
            if cur is not None:
                hashrates.append(cur.hashrate)
            if telemetry.power_w is not None:
                powers.append(telemetry.power_w)
            prev_stats, prev_gpu = stats, cur

        if not reason and start_gpu is not None and prev_gpu is not None:
            rejected = prev_gpu.rejected - start_gpu.rejected + prev_gpu.stale - start_gpu.stale
            total = rejected + prev_gpu.accepted - start_gpu.accepted
            if rejected >= 2 and total and rejected / total > self.cfg.max_reject_ratio:
                reason = f"много отклонённых шар: {rejected}/{total}"

        hashrate = statistics.fmean(hashrates) if hashrates else 0.0
        power = statistics.fmean(powers) if powers else 0.0
        if not reason and reference_hashrate and hashrate < reference_hashrate * (1 - self.cfg.max_hashrate_drop_pct / 100):
            reason = f"хешрейт просел до {format_hashrate(hashrate)} (эталон {format_hashrate(reference_hashrate)})"
        if not reason and hashrate <= 0:
            reason = "нет хешрейта"

        sample = BenchmarkSample(phase, settings, hashrate, power, stable=not reason, note=reason)
        self.profit.score(self.algorithm, sample)
        self._record(sample)
        if sample.stable:
            self._last_stable = settings
        else:
            self._recover(gpu, reason)
        return sample

    def _record(self, sample: BenchmarkSample) -> BenchmarkSample:
        self.samples.append(sample)
        if sample.stable:
            self._log(f"[{sample.phase}] {sample.settings.describe()}: {format_hashrate(sample.hashrate)}, "
                      f"{sample.power_w:.0f} Вт, чистыми {sample.net_per_day:.2f}/сут")
        else:
            self._log(f"[{sample.phase}] {sample.settings.describe()}: НЕСТАБИЛЬНО — {sample.note}")
        self.cb.on_sample(sample)
        return sample

    def _recover(self, gpu: int, reason: str) -> None:
        """Откат на последний стабильный шаг; при отвале — перезапуск майнера."""
        self._log(f"Откат на «{self._last_stable.describe()}» ({reason})")
        try:
            self.rig.apply(gpu, self._last_stable)
        except GpuBackendError as exc:
            self._log(f"Откат не удался: {exc}")
        stats = self._fetch()
        cur = stats.gpus.get(gpu) if stats else None
        if stats is None or cur is None or cur.hashrate <= 0 or "драйвер" in reason:
            self._log("Перезапуск майнера")
            try:
                self.controller.restart()
            except Exception as exc:  # noqa: BLE001
                self._log(f"Не удалось перезапустить майнер: {exc}")
        self._sleep(self.cfg.warmup_s)

    def _phase(self, idx: int) -> None:
        self.cb.on_phase(idx, PHASES[idx])
        self._log(f"=== {PHASES[idx]} ===")

    # ------------------------------------------------------------------ phases
    def run(self, gpu: int) -> TuneResult:
        handle = self.rig[gpu]
        info = handle.info
        original = handle.settings
        caps = handle.backend.capabilities
        self.samples = []
        self._last_stable = OcSettings()
        self._log(f"Калибровка {handle.label} на алгоритме {self.algorithm}")
        try:
            self._phase(0)
            baseline = self.measure(gpu, OcSettings(), PHASES[0])
            if not baseline.stable:
                raise TuneFailed(f"карта нестабильна даже на стоке: {baseline.note}")
            best = baseline

            if caps.core_lock:
                self._phase(1)
                best = self._core_search(gpu, info.stock_core_mhz, best)

            if caps.mem_offset:
                self._phase(2)
                best = self._mem_search(gpu, best)

            if caps.voltage and caps.core_lock:
                self._phase(3)
                best = self._undervolt(gpu, best, info.stock_core_mhz)

            self._phase(4)
            final = self._verify(gpu, best)
            self.rig.apply(gpu, final.settings)
            result = TuneResult(gpu, self.algorithm, baseline, final, list(self.samples))
            self._log(f"Готово: {final.settings.describe()} — {format_hashrate(final.hashrate)}, "
                      f"{final.power_w:.0f} Вт, {format_hashrate(final.efficiency, 'H/Вт')}, "
                      f"чистыми {final.net_per_day:.2f}/сут ({result.gain_per_day:+.2f} к стоку)")
            if final.net_per_day < 0:
                self._log("Внимание: даже на лучших настройках карта убыточна при текущем тарифе")
            return result
        except (TuneCancelled, TuneFailed):
            try:
                self.rig.apply(gpu, original)
            except GpuBackendError:
                pass
            raise

    def _better(self, a: BenchmarkSample, b: BenchmarkSample) -> bool:
        """``a`` лучше ``b``, если прирост прибыли больше шума замера."""
        margin = abs(b.net_per_day) * self.cfg.min_gain_pct / 100
        return a.stable and a.net_per_day > b.net_per_day + margin

    def _core_search(self, gpu: int, stock: int, best: BenchmarkSample) -> BenchmarkSample:
        coarse = self.cfg.core_step_mhz * COARSE_FACTOR
        budget = self.cfg.max_core_steps

        def lock(f: int) -> OcSettings:
            # Выше стока частота достижима только со смещением кривой
            return best.settings.replace(core_lock_mhz=f, core_offset_mhz=max(0, f - stock))

        # Сток как точка «зафиксированной частоты» для честного сравнения
        for direction in (-1, +1):
            declines = 0
            f = stock
            local_best = best
            while budget > 0:
                f += direction * coarse
                if f < stock * 0.5:
                    break
                budget -= 1
                s = self.measure(gpu, lock(f), PHASES[1])
                if not s.stable:
                    break
                if self._better(s, local_best):
                    local_best, declines = s, 0
                else:
                    declines += 1
                    if declines >= self.cfg.profit_decline_patience:
                        break
            if self._better(local_best, best):
                best = local_best
            if direction == -1 and best.settings.core_lock_mhz is not None:
                break  # снижение частоты дало выигрыш — разгон вверх не проверяем

        # Уточнение вокруг лучшей точки мелким шагом
        center = best.settings.core_lock_mhz or stock
        for f in (center - self.cfg.core_step_mhz * 2, center + self.cfg.core_step_mhz * 2):
            if f == stock and best.settings.core_lock_mhz is None:
                continue
            s = self.measure(gpu, lock(f), PHASES[1])
            if self._better(s, best):
                best = s
        self.rig.apply(gpu, best.settings)
        return best

    def _mem_search(self, gpu: int, best: BenchmarkSample) -> BenchmarkSample:
        step = self.cfg.mem_step_mhz
        start = best
        for direction in (+1, -1):
            declines = 0
            offset = start.settings.mem_offset_mhz
            for _ in range(self.cfg.max_mem_steps if direction > 0 else max(2, self.cfg.max_mem_steps // 2)):
                offset += direction * step
                s = self.measure(gpu, best.settings.replace(mem_offset_mhz=offset), PHASES[2])
                if not s.stable:
                    break
                if self._better(s, best):
                    best, declines = s, 0
                else:
                    declines += 1
                    if declines >= self.cfg.profit_decline_patience:
                        break
            if best is not start:
                break  # нашли выигрыш в эту сторону
        self.rig.apply(gpu, best.settings)
        return best

    def _undervolt(self, gpu: int, best: BenchmarkSample, stock_core: int) -> BenchmarkSample:
        if best.settings.core_lock_mhz is None:
            # Андервольт делается при зафиксированной частоте (curve lock)
            best = BenchmarkSample(best.phase, best.settings.replace(core_lock_mhz=stock_core),
                                   best.hashrate, best.power_w, True)
        fine = self.cfg.voltage_step_mv
        coarse = fine * 3
        ref = best.hashrate
        stable_offset = best.settings.voltage_offset_mv
        last_good = best
        failed_at: Optional[int] = None

        offset = stable_offset
        while offset - coarse >= self.cfg.min_voltage_offset_mv:
            offset -= coarse
            s = self.measure(gpu, best.settings.replace(voltage_offset_mv=offset), PHASES[3], reference_hashrate=ref)
            if not s.stable:
                failed_at = offset
                break
            stable_offset, last_good = offset, s
        if failed_at is not None:
            offset = stable_offset
            while offset - fine > failed_at:
                offset -= fine
                s = self.measure(gpu, best.settings.replace(voltage_offset_mv=offset), PHASES[3], reference_hashrate=ref)
                if not s.stable:
                    break
                stable_offset, last_good = offset, s
        self._log(f"Порог стабильности: {stable_offset:+d} мВ, запас {self.cfg.safety_margin_mv} мВ")
        safe = min(0, stable_offset + self.cfg.safety_margin_mv) if stable_offset < 0 else stable_offset
        return BenchmarkSample(PHASES[3], best.settings.replace(voltage_offset_mv=safe),
                               last_good.hashrate, last_good.power_w, True, note="кандидат")

    def _verify(self, gpu: int, candidate: BenchmarkSample) -> BenchmarkSample:
        settings = candidate.settings
        for _ in range(VERIFY_ATTEMPTS):
            s = self.measure(gpu, settings, PHASES[4], duration=self.cfg.stabilization_s * 2,
                             reference_hashrate=candidate.hashrate if candidate.hashrate else None)
            if s.stable:
                return s
            if settings.voltage_offset_mv >= 0:
                break
            settings = settings.replace(voltage_offset_mv=min(0, settings.voltage_offset_mv + self.cfg.safety_margin_mv))
            self._log(f"Проверка не пройдена, добавляю запас: {settings.voltage_offset_mv:+d} мВ")
        fallback = ProfitEngine.best(s for s in self.samples if s.phase != PHASES[4]) or self.samples[0]
        self._log("Проверка не пройдена — беру лучший стабильный замер")
        return fallback
