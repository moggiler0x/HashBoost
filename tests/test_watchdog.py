from hashboost.config import WatchdogConfig
from hashboost.core.watchdog import HealthMonitor, Severity, Watchdog
from hashboost.models import GpuMinerStats, GpuTelemetry, OcSettings


def test_temps():
    m = HealthMonitor(WatchdogConfig(max_gpu_temp_c=80))
    assert m.check_temps(0, GpuTelemetry(0, gpu_temp_c=70)) == []
    assert m.check_temps(0, GpuTelemetry(0, gpu_temp_c=77))[0].severity == Severity.WARN
    assert m.check_temps(0, GpuTelemetry(0, gpu_temp_c=81))[0].severity == Severity.CRITICAL


def test_invalid_shares_unstable():
    m = HealthMonitor(WatchdogConfig(max_invalid_per_minute=1))
    issues = m.check_mining(0, GpuMinerStats(1, invalid=0), GpuMinerStats(1, invalid=2), 60, True)
    assert issues[0].severity == Severity.UNSTABLE
    zero = m.check_mining(0, None, GpuMinerStats(0), 0, True)
    assert zero[0].severity == Severity.CRITICAL


def test_watchdog_rolls_back_unstable_card(rig, miner, clock, sim):
    client, controller = miner
    events = []
    wd = Watchdog(rig, client, controller, WatchdogConfig(), clock, events.append)
    stable = OcSettings(core_lock_mhz=2160, voltage_offset_mv=-90)
    rig.apply(0, stable)
    wd.mark_stable(0, stable)
    wd.check()
    rig.apply(0, OcSettings(core_lock_mhz=2160, voltage_offset_mv=-125))  # ниже порога: ошибки
    clock.sleep(120)
    report = wd.check()
    assert report.worst(0) >= Severity.UNSTABLE
    assert rig[0].settings == stable
    assert any("откат" in e for e in events)


def test_watchdog_restarts_after_crash(rig, miner, clock, sim):
    client, controller = miner
    events = []
    wd = Watchdog(rig, client, controller, WatchdogConfig(), clock, events.append)
    wd.check()
    rig.apply(1, OcSettings(core_lock_mhz=1785, voltage_offset_mv=-200))
    clock.sleep(10)
    wd.check()
    assert rig[1].settings == OcSettings()
    assert "Перезапуск майнера" in events
    assert not sim.gpus[1].crashed


def test_watchdog_cools_down_hot_card(rig, miner, clock):
    client, controller = miner
    events = []
    wd = Watchdog(rig, client, controller, WatchdogConfig(max_gpu_temp_c=50), clock, events.append)
    wd.check()
    assert rig[0].settings.power_limit_w is not None
    assert rig[0].settings.power_limit_w < rig[0].info.stock_power_limit_w
