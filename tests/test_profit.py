import pytest

from hashboost.config import AppConfig, AlgorithmConfig
from hashboost.core.profit import ProfitEngine
from hashboost.models import BenchmarkSample, OcSettings


def engine():
    cfg = AppConfig(tariff_per_kwh=5.0, psu_efficiency=1.0, rig_base_power_w=0)
    cfg.algorithms = {"a": AlgorithmConfig("a", unit="MH/s", revenue_per_unit_day=0.1, pool_fee_pct=0)}
    return ProfitEngine(cfg)


def test_evaluate():
    p = engine().evaluate("a", 300e6, 100)
    assert p.revenue_per_day == pytest.approx(30.0)
    assert p.cost_per_day == pytest.approx(100 * 24 / 1000 * 5)  # 12
    assert p.net_per_day == pytest.approx(18.0)
    assert p.net_per_month == pytest.approx(540.0)


def test_psu_and_base_power():
    e = engine()
    e.cfg.psu_efficiency = 0.8
    e.cfg.rig_base_power_w = 40
    total = e.rig_total([("a", 100e6, 80)])
    assert total.wall_power_w == pytest.approx(100 + 50)
    assert total.cost_per_day == pytest.approx(150 * 24 / 1000 * 5)


def test_best_prefers_net_profit_not_hashrate():
    e = engine()
    fast = e.score("a", BenchmarkSample("x", OcSettings(), 300e6, 160, True))  # 30 - 19.2 = 10.8
    lean = e.score("a", BenchmarkSample("x", OcSettings(core_lock_mhz=1500), 270e6, 100, True))  # 27 - 12 = 15
    broken = e.score("a", BenchmarkSample("x", OcSettings(voltage_offset_mv=-200), 280e6, 80, False))
    assert ProfitEngine.best([fast, lean, broken]) is lean


def test_best_tie_prefers_lower_power():
    e = engine()
    a = BenchmarkSample("x", OcSettings(), 0, 100, True, revenue_per_day=20, cost_per_day=10)
    b = BenchmarkSample("x", OcSettings(), 0, 90, True, revenue_per_day=19.98, cost_per_day=10)
    a.hashrate = b.hashrate = 1
    assert ProfitEngine.best([a, b]) is b


def test_dual_tariff_effective_price():
    cfg = AppConfig(tariff_mode="dual", tariff_day=10.64, tariff_night=4.85, psu_efficiency=1.0)
    assert cfg.night_hours == 8
    assert cfg.effective_tariff() == pytest.approx((10.64 * 16 + 4.85 * 8) / 24)
    e = ProfitEngine(cfg)
    assert e.cost_per_day(100) == pytest.approx(2.4 * cfg.effective_tariff())
    cfg.tariff_mode = "single"
    cfg.tariff_per_kwh = 8.9
    assert e.cost_per_day(100) == pytest.approx(2.4 * 8.9)


def test_night_only():
    cfg = AppConfig(tariff_mode="dual", tariff_day=10, tariff_night=4, psu_efficiency=1.0, rig_base_power_w=0)
    cfg.algorithms = {"a": AlgorithmConfig("a", unit="MH/s", revenue_per_unit_day=0.1, pool_fee_pct=0)}
    e = ProfitEngine(cfg)
    total = e.rig_total([("a", 300e6, 500)])  # доход 30, свет 12 кВт·ч * 8 = 96
    night = e.night_only(total)
    assert night.revenue_per_day == pytest.approx(10.0)
    assert night.cost_per_day == pytest.approx(0.5 * 8 * 4)
    assert night.net_per_day > total.net_per_day


def test_payback():
    from hashboost.core.profit import payback_days
    assert payback_days(10000, 100) == pytest.approx(100)
    assert payback_days(10000, -5) is None
    assert payback_days(0, 10) == 0.0
