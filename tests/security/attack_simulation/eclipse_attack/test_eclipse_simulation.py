import pytest
import trio
from .malicious_peer import MaliciousPeer
from .network_builder import AttackNetworkBuilder
from .attack_scenarios import EclipseScenario
from .metrics_collector import AttackMetrics

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
    honest, malicious = await builder.create_eclipse_test_network(5,2)
    assert len(honest) == 5
    assert len(malicious) == 2

@pytest.mark.trio
async def test_eclipse_scenario_execution():
    builder = AttackNetworkBuilder()
    honest, malicious = await builder.create_eclipse_test_network(3,2)
    scenario = EclipseScenario(honest, malicious)
    metrics = await scenario.execute()
    assert isinstance(metrics, AttackMetrics)
    assert metrics.lookup_success_rate == [1.0,0.5,0.9]
