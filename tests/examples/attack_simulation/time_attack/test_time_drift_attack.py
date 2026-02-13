import pytest

from .time_drift_attack import TimeDriftAttacker, TimeDriftScenario


@pytest.mark.trio
async def test_time_drift_attacker_basic():
    nodes = [f"n{i}" for i in range(5)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.4,
        max_drift_ms=50.0,
        intensity=1.0,
    )

    drifted_nodes, clocks = await attacker.apply_drift(rounds=3)
    assert len(drifted_nodes) > 0
    assert len(clocks) == 5
    assert all(isinstance(v, float) for v in clocks.values())


@pytest.mark.trio
async def test_time_drift_scenario_execution():
    nodes = [f"n{i}" for i in range(6)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.5,
        max_drift_ms=80.0,
        intensity=1.0,
    )

    scenario = TimeDriftScenario(nodes, attacker)
    result = await scenario.run()
    assert "drifted_nodes" in result
    assert "clock_values" in result
    assert "clock_difference_ms" in result
    assert "attack_metrics" in result
    assert result["clock_difference_ms"] >= 0


@pytest.mark.trio
async def test_time_drift_at_least_one_node_drifted():
    nodes = [f"n{i}" for i in range(4)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.0,  # even 0 should still drift at least 1 node
        max_drift_ms=100.0,
        intensity=1.0,
    )

    drifted_nodes, _ = await attacker.apply_drift(rounds=1)
    assert len(drifted_nodes) >= 1
    assert drifted_nodes[0] in nodes


@pytest.mark.trio
async def test_time_drift_clock_skew_occurs():
    nodes = [f"n{i}" for i in range(5)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.5,
        max_drift_ms=50.0,
        intensity=1.0,
    )

    _, clocks = await attacker.apply_drift(rounds=5)
    times = list(clocks.values())

    assert max(times) != min(times), "Clock skew should exist if drift was applied"


@pytest.mark.trio
async def test_time_drift_resilience_decreases_with_drift():
    nodes = [f"n{i}" for i in range(6)]

    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=1.0,
        max_drift_ms=200.0,
        intensity=2.0,
    )

    scenario = TimeDriftScenario(nodes, attacker)
    result = await scenario.run()

    report = result["attack_metrics"]
    resilience = report["resilience_score"]

    assert resilience <= 1.0
    assert resilience < 0.8  # heavy drift should reduce resilience


@pytest.mark.trio
async def test_time_drift_metrics_fields_present():
    nodes = [f"n{i}" for i in range(5)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.4,
        max_drift_ms=60.0,
        intensity=1.0,
    )

    scenario = TimeDriftScenario(nodes, attacker)
    result = await scenario.run()
    report = result["attack_metrics"]

    required_fields = [
        "lookup_success_degradation",
        "routing_incorrect_rate",
        "lookup_failure_rate",
        "avg_lookup_latency",
        "resilience_score",
        "network_connectivity",
        "peer_table_contamination",
    ]

    for field in required_fields:
        assert field in report, f"Missing metric field: {field}"


@pytest.mark.trio
async def test_time_drift_values_not_identical():
    nodes = [f"n{i}" for i in range(8)]
    attacker = TimeDriftAttacker(
        node_ids=nodes,
        drift_fraction=0.6,
        max_drift_ms=40.0,
        intensity=1.0,
    )

    _, clocks = await attacker.apply_drift(rounds=3)
    unique_values = len(set(clocks.values()))

    assert unique_values > 1, "At least one node must differ in clock value"
