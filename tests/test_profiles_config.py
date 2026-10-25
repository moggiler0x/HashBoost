from hashboost.config import AppConfig, load_config, save_config
from hashboost.core.profiles import Profile, ProfileStore
from hashboost.models import OcSettings


def test_profiles_roundtrip(tmp_path):
    path = tmp_path / "profiles.json"
    store = ProfileStore(path)
    store.put(Profile("uid-1", "RTX 4060", "poseidon2", OcSettings(core_lock_mhz=2160, voltage_offset_mv=-90), 2.7e8, 78, 14.6))
    store.put(Profile("uid-1", "RTX 4060", "pearlhash", OcSettings(mem_offset_mhz=500), 4e7, 70, 15))
    again = ProfileStore(path)
    p = again.get("uid-1", "poseidon2")
    assert p.settings == OcSettings(core_lock_mhz=2160, voltage_offset_mv=-90)
    assert again.algorithms() == ["pearlhash", "poseidon2"]
    again.delete("uid-1", "pearlhash")
    assert ProfileStore(path).get("uid-1", "pearlhash") is None


def test_config_roundtrip(tmp_path):
    cfg = AppConfig(tariff_per_kwh=4.5)
    cfg.tuning.safety_margin_mv = 25
    cfg.algorithm("newalgo").revenue_per_unit_day = 3
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.tariff_per_kwh == 4.5
    assert loaded.tuning.safety_margin_mv == 25
    assert loaded.algorithms["newalgo"].revenue_per_unit_day == 3


def test_parse_algo_args():
    pytest = __import__("pytest")
    try:
        from hashboost.gui.settings_view import parse_algo_args
    except ImportError as exc:
        pytest.skip(f"Qt недоступен: {exc}")
    text = "poseidon2: --algorithm poseidon2 --pool stratum+tcp://a:1\n\nбез двоеточия\npearlhash:  -a pearl "
    assert parse_algo_args(text) == {"poseidon2": "--algorithm poseidon2 --pool stratum+tcp://a:1",
                                     "pearlhash": "-a pearl"}
