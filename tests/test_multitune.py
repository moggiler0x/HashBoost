from hashboost.config import AppConfig
from hashboost.core.autotune import TunerCallbacks
from hashboost.core.runtime import Runtime


def fast(cfg):
    cfg.tuning.stabilization_s = 30
    cfg.tuning.warmup_s = 5
    return cfg


def test_multi_calibration_picks_pearl_for_4060_and_quantus_for_1660s(clock):
    from hashboost.clock import ManualClock

    runtime = Runtime(fast(AppConfig(simulate=True)))
    runtime.clock = ManualClock()
    runtime.sim.clock = runtime.clock
    runtime.sim.restart_miner()
    logs = []
    try:
        cb = TunerCallbacks(on_log=logs.append)
        algos = ["poseidon2", "pearlhash"]
        r4060 = runtime.make_multi_tuner(algos, cb).run(0)
        assert set(r4060.results) == set(algos)
        assert r4060.best.algorithm == "pearlhash"
        r1660 = runtime.make_multi_tuner(algos, cb).run(2)
        assert r1660.best.algorithm == "poseidon2"
        rx570 = runtime.make_multi_tuner(algos, cb).run(4)
        assert rx570.best.algorithm == "poseidon2"
        assert "не майнит" in rx570.failures["pearlhash"]  # Polaris не майнит PearlHash
        assert any("Сравнение монет" in m for m in logs)

        for res in (r4060, r1660):
            for tr in res.results.values():
                runtime.save_tune_result(tr)
        advice = {a.gpu.index: a for a in runtime.advice()}
        assert advice[0].best.algorithm == "pearlhash" and advice[0].best.source == "калибровка"
        assert advice[2].best.algorithm == "poseidon2"
        assert advice[0].payback_days is not None
    finally:
        runtime.shutdown()


def test_switch_algorithm_requires_args_for_real_miner():
    import pytest

    cfg = AppConfig(simulate=True)
    runtime = Runtime(cfg)
    try:
        runtime.switch_algorithm("pearlhash")
        assert runtime.sim.algorithm == "pearlhash" and runtime.algorithm == "pearlhash"
        runtime.sim = None  # как будто реальный майнер, которым HashBoost не управляет
        assert not runtime.can_switch_algorithm("poseidon2")
        with pytest.raises(RuntimeError):
            runtime.switch_algorithm("poseidon2")
    finally:
        runtime.shutdown()
