import pytest

from .attack_scenarios import EclipseScenario
from .malicious_peer import MaliciousPeer
from .metrics_collector import AttackMetrics
from .network_builder import AttackNetworkBuilder


@pytest.mark.trio
async def test_malicious_peer_behavior():
    mp = MaliciousPeer("mal_1", "eclipse", 0.5)
    victim_table = []
    await mp.poison_dht_entries("honest_1")
    assert "honest_1" in mp.poisoned_entries
    await mp.flood_peer_table(victim_table)
    assert len(victim_table) > 0


@pytest.mark.trio
async def test_network_builder():
    builder = AttackNetworkBuilder()
    honest, malicious = await builder.create_eclipse_test_network(5, 2)
    assert len(honest) == 5
    assert len(malicious) == 2


@pytest.mark.trio
async def test_eclipse_scenario_execution():
    builder = AttackNetworkBuilder()
    honest, malicious = await builder.create_eclipse_test_network(3, 2)
    scenario = EclipseScenario(honest, malicious)
    metrics = await scenario.execute()
    assert isinstance(metrics, AttackMetrics)
    # Check that metrics are calculated realistically
    assert len(metrics.lookup_success_rate) == 3
    assert all(0 <= rate <= 1 for rate in metrics.lookup_success_rate)
    assert len(metrics.peer_table_contamination) == 3
    assert len(metrics.network_connectivity) == 3
    assert metrics.recovery_time > 0
