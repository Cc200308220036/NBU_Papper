import socket

import pytest

from semantic_pallet_planner.jev_select.candidates import CandidateProvider, PublicBusinessGuard
from semantic_pallet_planner.jev_select.config import generator_config, load_config
from semantic_pallet_planner.jev_select.context import ContextBuilder
from semantic_pallet_planner.jev_select.experiment import constructed_cases


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Automated tests must never access the network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


@pytest.fixture
def pipeline():
    case = constructed_cases()[0]
    config = load_config()
    guard = PublicBusinessGuard()
    policy = guard.resolve(case["observation"])
    bundle = CandidateProvider().build(case["state"], case["observation"], generator_config())
    bundle = guard.filter(case["observation"], policy, bundle, config)
    context = ContextBuilder(config).build(case["observation"], bundle, policy)
    return case, config, policy, bundle, context
