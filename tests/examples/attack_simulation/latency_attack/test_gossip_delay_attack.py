import pytest

from .gossip_delay_attack import GossipDelayAttacker, GossipDelayScenario


@pytest.mark.trio
async def test_gossip_delay_attacker_generates_messages():
    attacker = GossipDelayAttacker(
        topics=["blocks", "attestations"],
        delayed_topics=["blocks"],
        max_delay_ms=300.0,
        intensity=1.0,
    )

    msgs = await attacker.generate_messages(20)
    assert len(msgs) == 20
    assert all("topic" in m for m in msgs)
    assert any(m["delayed"] for m in msgs)


@pytest.mark.trio
async def test_gossip_delay_marks_delayed_flag_consistently():
    attacker = GossipDelayAttacker(
        topics=["blocks"],
        delayed_topics=["blocks"],
        max_delay_ms=200.0,
        intensity=1.0,
    )

    msgs = await attacker.generate_messages(10)
    for m in msgs:
        assert (m["delay_ms"] > 0.0) == m["delayed"]


@pytest.mark.trio
async def test_gossip_delay_scenario_execution():
    attacker = GossipDelayAttacker(
        topics=["blocks", "sync"],
        delayed_topics=["sync"],
        max_delay_ms=250.0,
        intensity=1.0,
    )

    scenario = GossipDelayScenario(attacker)
    result = await scenario.run(count=30)

    assert "messages" in result
    assert "attack_metrics" in result
    report = result["attack_metrics"]
    assert "delayed_ratio" in report
    assert "max_latency_spike_ms" in report


@pytest.mark.trio
async def test_gossip_delay_resilience_decreases_with_delay():
    attacker = GossipDelayAttacker(
        topics=["blocks"],
        delayed_topics=["blocks"],
        max_delay_ms=500.0,
        intensity=2.0,
    )

    scenario = GossipDelayScenario(attacker)
    result = await scenario.run(count=40)
    report = result["attack_metrics"]

    resilience = report["resilience_score"]
    assert resilience <= 1.0
    assert resilience < 0.8  # heavy delays should reduce resilience


@pytest.mark.trio
async def test_gossip_delay_metrics_fields_present():
    attacker = GossipDelayAttacker(
        topics=["blocks", "attestations"],
        delayed_topics=["blocks"],
        max_delay_ms=300.0,
        intensity=1.0,
    )

    scenario = GossipDelayScenario(attacker)
    result = await scenario.run(count=25)
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
async def test_gossip_delay_ratio_between_zero_and_one():
    attacker = GossipDelayAttacker(
        topics=["blocks", "sync"],
        delayed_topics=["blocks"],
        max_delay_ms=250.0,
        intensity=1.0,
    )

    scenario = GossipDelayScenario(attacker)
    result = await scenario.run(count=30)
    report = result["attack_metrics"]

    ratio = report["delayed_ratio"]
    assert 0.0 <= ratio <= 1.0


@pytest.mark.trio
async def test_gossip_delay_spike_non_negative():
    attacker = GossipDelayAttacker(
        topics=["blocks", "sync"],
        delayed_topics=["sync"],
        max_delay_ms=250.0,
        intensity=1.0,
    )

    scenario = GossipDelayScenario(attacker)
    result = await scenario.run(count=30)
    report = result["attack_metrics"]

    assert report["max_latency_spike_ms"] >= 0.0
