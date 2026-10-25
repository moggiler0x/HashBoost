import os
import tempfile

import pytest

from hashboost.clock import ManualClock
from hashboost.config import AppConfig
from hashboost.hardware import Rig
from hashboost.hardware.simulator import SimulatedBackend, SimulatedRig
from hashboost.miners.simulated import SimulatedMinerClient, SimulatedMinerController

os.environ.setdefault("HASHBOOST_HOME", tempfile.mkdtemp(prefix="hashboost-test-"))


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def sim(clock):
    return SimulatedRig(clock=clock)


@pytest.fixture
def rig(sim):
    return Rig([SimulatedBackend(sim)])


@pytest.fixture
def miner(sim):
    return SimulatedMinerClient(sim), SimulatedMinerController(sim)


@pytest.fixture
def cfg():
    return AppConfig(simulate=True)
