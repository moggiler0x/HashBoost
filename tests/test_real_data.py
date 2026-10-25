"""Справочные цифры и симулятор сверены с реальными данными Kryptex."""
import pytest

from hashboost.config import AppConfig, PRL_RUB_PER_TH_DAY, QTC_RUB_PER_MH_DAY
from hashboost.core.advisor import SOURCE_KRYPTEX, advise_card, best_rig_algorithm
from hashboost.core.market import find_card, normalize_name
from hashboost.core.profit import ProfitEngine
from hashboost.models import GpuInfo, OcSettings, Vendor

# Скрины Kryptex 5.10.7 с ригов автора (25.10.2026): карта, монета, хешрейт, ₽/мес
OBSERVED = [
    ("NVIDIA GeForce RTX 4060", "pearlhash", 61.56e12, 3719.92),
    ("NVIDIA GeForce GTX 1650", "poseidon2", 102.32e6, 941.39),
    ("NVIDIA GeForce GTX 1660 SUPER", "poseidon2", 138.02e6, 1269.87),
    ("NVIDIA GeForce GTX 1660 SUPER", "poseidon2", 137.80e6, 1267.83),
]


def gpu(name, uid="x"):
    return GpuInfo(0, uid, name, Vendor.NVIDIA, 0, 0, 100, 50, 120)


@pytest.mark.parametrize("name,algo,hashrate,per_month", OBSERVED)
def test_default_revenue_matches_kryptex_payouts(name, algo, hashrate, per_month):
    cfg = AppConfig()
    revenue = ProfitEngine(cfg).revenue_per_day(algo, hashrate)
    assert revenue * 30 == pytest.approx(per_month, rel=0.005)


def test_default_tariff_is_moscow_october_2026():
    cfg = AppConfig()
    assert cfg.tariff_per_kwh == 8.90
    assert (cfg.tariff_day, cfg.tariff_night) == (10.64, 4.85)


def test_name_matching():
    assert normalize_name("NVIDIA GeForce GTX 1660 SUPER") == "gtx 1660 super"
    assert find_card("NVIDIA GeForce RTX 4060").name == "RTX 4060"
    assert find_card("NVIDIA GeForce RTX 4060 Ti").name == "RTX 4060 Ti"
    assert find_card("Radeon RX 570 Series").name == "RX 570"
    assert find_card("NVIDIA GeForce RTX 2080") is None


def test_rtx4060_earns_more_on_pearl_and_1660s_on_quantus():
    cfg = AppConfig()
    engine = ProfitEngine(cfg)
    a4060 = advise_card(cfg, engine, gpu("NVIDIA GeForce RTX 4060"), None)
    a1660 = advise_card(cfg, engine, gpu("NVIDIA GeForce GTX 1660 SUPER"), None)
    assert a4060.best.algorithm == "pearlhash" and a4060.best.source == SOURCE_KRYPTEX
    assert a1660.best.algorithm == "poseidon2"
    assert a4060.advantage() > 0
    # окупаемость: цена Kryptex ($299) по курсу ЦБ, делённая на чистую прибыль
    expected = round(299 * cfg.usd_rate) / a4060.best.profit.net_per_day
    assert a4060.payback_days == pytest.approx(expected)
    assert 150 < a4060.payback_days < 400


def test_rx570_has_no_pearl_and_rig_total():
    cfg = AppConfig()
    engine = ProfitEngine(cfg)
    rx = advise_card(cfg, engine, gpu("AMD Radeon RX 570"), None)
    assert [e.algorithm for e in rx.estimates] == ["poseidon2"]
    rig = [advise_card(cfg, engine, gpu(n, str(i)), None) for i, n in enumerate(
        ["NVIDIA GeForce GTX 1660 SUPER", "NVIDIA GeForce GTX 1660 SUPER", "AMD Radeon RX 570"])]
    assert best_rig_algorithm(rig)[0] == "poseidon2"


def test_unprofitable_card_never_pays_back():
    cfg = AppConfig(tariff_per_kwh=100.0)
    advice = advise_card(cfg, ProfitEngine(cfg), gpu("AMD Radeon RX 570"), None)
    assert advice.payback_days is None


def test_user_price_overrides_reference():
    cfg = AppConfig(card_prices={"x": 15000.0})
    advice = advise_card(cfg, ProfitEngine(cfg), gpu("NVIDIA GeForce RTX 4060"), None)
    assert advice.price == 15000.0


def test_simulator_matches_real_1660_super(sim):
    """PeakMiner 2.20.0, 1500/6801 МГц: 138 MH/s при 66–72 Вт."""
    g = sim.gpus[2]
    assert "1660 SUPER" in g.spec.name
    g.settings = OcSettings(core_lock_mhz=1500, mem_offset_mhz=-200, voltage_offset_mv=-50)
    op = sim._operating(g)
    assert sim._hashrate(g, op) == pytest.approx(138.0e6, rel=0.03)
    assert 64 <= op.power <= 76
    assert op.errors_per_min == 0


def test_simulator_stock_matches_reference(sim):
    for algo in ("poseidon2", "pearlhash"):
        sim.algorithm = algo
        for g in sim.gpus:
            ref = find_card(g.spec.name)
            hr = sim._hashrate(g, sim._operating(g))
            assert hr == pytest.approx(ref.hashrates.get(algo, 0.0), rel=0.01)


def test_legacy_config_upgraded():
    old = {"tariff_per_kwh": 6.0, "algorithms": {
        "poseidon2": {"name": "poseidon2", "coin": "Quantus", "revenue_per_unit_day": 0.1, "unit": "MH/s"},
        "pearlhash": {"name": "pearlhash", "coin": "Pearl", "revenue_per_unit_day": 0.7, "unit": "MH/s"}}}
    cfg = AppConfig.from_dict(old)
    assert cfg.tariff_per_kwh == 8.90
    assert cfg.algorithms["pearlhash"].unit == "TH/s"
    assert cfg.algorithms["pearlhash"].revenue_per_unit_day == PRL_RUB_PER_TH_DAY
    assert cfg.algorithms["poseidon2"].revenue_per_unit_day == QTC_RUB_PER_MH_DAY
    custom = AppConfig.from_dict({"tariff_per_kwh": 5.5, "algorithms": {
        "poseidon2": {"name": "poseidon2", "revenue_per_unit_day": 0.4, "unit": "MH/s"}}})
    assert custom.tariff_per_kwh == 5.5 and custom.algorithms["poseidon2"].revenue_per_unit_day == 0.4
