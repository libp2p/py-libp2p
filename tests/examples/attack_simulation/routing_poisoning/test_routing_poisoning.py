import pytest

from .routing_poisoning_attack import RoutingPoisoner, RoutingPoisoningScenario


@pytest.mark.trio
async def test_routing_poisoner_creation():
    p = RoutingPoisoner("attacker_1", fake_rate=2.0, intensity=0.5)
    entries = await p.create_fake_entries(3)
    assert len(entries) == 3
    assert all("attacker_1_rpoison_" in e["peer_id"] for e in entries)
    assert len(p.advertised_entries) == 3


@pytest.mark.trio
async def test_advertise_to_targets_and_basic_scenario():
    honest = ["h1", "h2", "h3"]
    poisoner = RoutingPoisoner("attacker_1", fake_rate=3.0, intensity=0.7)
    # run short advertise loop
    await poisoner.advertise_to_targets(honest, duration=0.2)
    assert len(poisoner.advertised_entries) > 0

    scenario = RoutingPoisoningScenario(honest, [poisoner])
    results = await scenario.execute_poisoning()
    assert "total_fake_entries" in results
    assert "attack_metrics" in results
    assert results["total_fake_entries"] >= len(poisoner.advertised_entries)
