from hashboost.core.autotune import AutoTuner, PHASES, TunerCallbacks
from hashboost.core.profit import ProfitEngine
from hashboost.models import OcSettings


def make_tuner(rig, miner, cfg, clock, logs=None):
    client, controller = miner
    cb = TunerCallbacks(on_log=(logs.append if logs is not None else (lambda m: None)))
    return AutoTuner(rig, client, controller, ProfitEngine(cfg), cfg.tuning, cfg.watchdog,
                     "poseidon2", clock, cb)


def test_autotune_improves_profit_and_finds_undervolt(rig, miner, cfg, clock, sim):
    logs = []
    tuner = make_tuner(rig, miner, cfg, clock, logs)
    result = tuner.run(0)
    assert result.final.stable
    assert result.final.net_per_day > result.baseline.net_per_day
    assert result.final.settings.voltage_offset_mv < 0
    assert result.final.settings.core_lock_mhz is not None
    assert rig[0].settings == result.final.settings
    # итоговые настройки не дают ошибок
    spec = sim.gpus[0].spec
    op = sim._operating(sim.gpus[0])
    assert op.errors_per_min == 0 and not op.crash
    assert {s.phase for s in result.samples} >= {PHASES[0], PHASES[3], PHASES[4]}


def test_safety_margin_applied(rig, miner, cfg, clock, sim):
    tuner = make_tuner(rig, miner, cfg, clock)
    result = tuner.run(1)
    uv_samples = [s for s in result.samples if s.phase == PHASES[3]]
    stable = [s.settings.voltage_offset_mv for s in uv_samples if s.stable]
    threshold = min(stable)
    assert result.final.settings.voltage_offset_mv == min(0, threshold + cfg.tuning.safety_margin_mv)


def test_crash_recovers_and_restarts_miner(rig, miner, cfg, clock, sim):
    tuner = make_tuner(rig, miner, cfg, clock)
    # Глубокий андервольт сразу роняет карту
    sample = tuner.measure(2, OcSettings(core_lock_mhz=1830, voltage_offset_mv=-200), "test")
    assert not sample.stable
    assert rig[2].settings == OcSettings()
    assert not sim.gpus[2].crashed  # майнер перезапущен, карта снова работает
    ok = tuner.measure(2, OcSettings(), "test")
    assert ok.stable and ok.hashrate > 0


def test_cancel(rig, miner, cfg, clock):
    tuner = make_tuner(rig, miner, cfg, clock)
    tuner.cancel()
    import pytest
    from hashboost.core.autotune import TuneCancelled
    with pytest.raises(TuneCancelled):
        tuner.run(0)
    assert rig[0].settings == OcSettings()
