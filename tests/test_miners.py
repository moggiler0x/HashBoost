import pytest

from hashboost.miners.base import MinerApiError, dig
from hashboost.miners.generic import GenericJsonClient
from hashboost.miners.rigel import RigelClient
from hashboost.miners.srbminer import SrbMinerClient


def test_srbminer_parse():
    payload = {
        "mining_time": 300,
        "algorithms": [{
            "name": "poseidon2",
            "hashrate": {"gpu": {"total": 3e8, "gpu0": 1e8, "gpu1": 2e8}},
            "shares": {"accepted": 7, "gpu0": {"accepted": 3, "rejected": 1, "hw_errors": 2},
                       "gpu1": {"accepted": 4, "rejected": 0}},
        }],
        "gpu_devices": [{"device_id": 1, "hardware_errors": 5}],
    }
    stats = SrbMinerClient("http://x").parse(payload)
    assert stats.algorithm == "poseidon2"
    assert stats.uptime_s == 300
    assert stats.gpus[0].hashrate == 1e8 and stats.gpus[1].hashrate == 2e8
    assert stats.gpus[0].rejected == 1 and stats.gpus[0].invalid == 2
    assert stats.gpus[1].invalid == 5
    assert stats.total_hashrate == 3e8


def test_srbminer_bad_payload():
    with pytest.raises(MinerApiError):
        SrbMinerClient("http://x").parse({"foo": 1})


def test_rigel_parse():
    payload = {"algorithm": "pearlhash", "uptime": 60, "devices": [
        {"id": 0, "selected": True, "hashrate": {"pearlhash": 4e7},
         "shares": {"pearlhash": {"accepted": 10, "rejected": 1, "stale": 2, "invalid": 1}}},
        {"id": 1, "selected": False, "hashrate": {"pearlhash": 0}},
        {"id": 2, "hashrate": 3e7, "shares": {"accepted": 4}},
    ]}
    stats = RigelClient("http://x").parse(payload)
    assert set(stats.gpus) == {0, 2}
    g = stats.gpus[0]
    assert (g.hashrate, g.accepted, g.rejected, g.stale, g.invalid) == (4e7, 10, 1, 2, 1)
    assert stats.gpus[2].hashrate == 3e7 and stats.gpus[2].accepted == 4


def test_generic_parse():
    client = GenericJsonClient("http://x", {"gpus": "data.cards", "index": "n", "hashrate": "speed",
                                            "accepted": "ok", "invalid": "hw", "algorithm": "data.algo"})
    stats = client.parse({"data": {"algo": "x", "cards": [{"n": 3, "speed": "12.5", "ok": 2, "hw": 1}]}})
    assert stats.algorithm == "x"
    assert stats.gpus[3].hashrate == 12.5 and stats.gpus[3].hashrate_avg == 12.5
    assert stats.gpus[3].invalid == 1


def test_dig():
    assert dig({"a": [{"b": 5}]}, "a.0.b") == 5
    assert dig({"a": []}, "a.0.b", "x") == "x"
