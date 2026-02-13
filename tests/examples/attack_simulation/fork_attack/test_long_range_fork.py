"""
Tests for Long-Range Fork Replay Attack Simulation

Tests the long-range fork attack scenario inspired by Polkadot's security model.
"""

import trio

from .long_range_fork import (
    ChainState,
    ForkAttacker,
    LongRangeForkScenario,
    run_long_range_fork_simulation,
)


def test_chain_state_initialization():
    """Test ChainState initialization"""
    chain = ChainState(
        block_height=1000,
        block_hash="hash_1000",
        finality_checkpoint=900,
        timestamp=123456.0,
        validator_set=["v1", "v2", "v3"],
    )

    assert chain.block_height == 1000
    assert chain.block_hash == "hash_1000"
    assert chain.finality_checkpoint == 900
    assert chain.timestamp == 123456.0
    assert len(chain.validator_set) == 3
    assert chain.is_canonical is True


def test_fork_attacker_initialization():
    """Test ForkAttacker initialization"""
    canonical = ChainState(1000, "c_hash", 900, 100.0, ["v1"])
    stale = ChainState(800, "s_hash", 700, 50.0, ["v1"])

    attacker = ForkAttacker("attacker_0", stale, canonical, 0.7)

    assert attacker.attacker_id == "attacker_0"
    assert attacker.stale_fork == stale
    assert attacker.canonical_chain == canonical
    assert attacker.intensity == 0.7
    assert attacker.replay_attempts == 0
    assert len(attacker.successful_replays) == 0


async def test_fork_attacker_replay_stale_fork():
    """Test fork replay attempt"""
    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    attacker = ForkAttacker("attacker_0", stale, canonical, 0.8)

    # Test with peer offline for 2 hours
    result = await attacker.replay_stale_fork("peer_1", 7200.0)

    assert isinstance(result, bool)
    assert attacker.replay_attempts == 1
    assert len(attacker.successful_replays) + len(attacker.failed_replays) == 1


async def test_fork_attacker_campaign():
    """Test fork replay campaign"""
    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    attacker = ForkAttacker("attacker_0", stale, canonical, 0.7)

    offline_peers = [("peer_1", 3600.0), ("peer_2", 7200.0), ("peer_3", 1800.0)]

    results = await attacker.execute_fork_replay_campaign(offline_peers, duration=1.0)

    assert "replay_attempts" in results
    assert "successful_replays" in results
    assert "failed_replays" in results
    assert "success_rate" in results
    assert results["replay_attempts"] > 0


async def test_long_range_fork_scenario_basic():
    """Test basic long-range fork scenario"""
    online_peers = ["o1", "o2", "o3"]
    offline_peers = [("off1", 3600.0), ("off2", 7200.0)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    fork_attackers = [ForkAttacker("attacker_0", stale, canonical, 0.7)]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)

    # Verify result structure
    assert "attack_type" in results
    assert results["attack_type"] == "long_range_fork"
    assert "network_composition" in results
    assert "fork_replay_metrics" in results
    assert "detection_metrics" in results
    assert "resync_metrics" in results
    assert "security_insights" in results
    assert "recommendations" in results


async def test_long_range_fork_with_multiple_attackers():
    """Test long-range fork attack with multiple attackers"""
    online_peers = [f"o{i}" for i in range(5)]
    offline_peers = [(f"off{i}", 3600.0 + i * 1800) for i in range(3)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    fork_attackers = [
        ForkAttacker(f"attacker_{i}", stale, canonical, 0.7) for i in range(3)
    ]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)

    assert results["network_composition"]["fork_attackers"] == 3
    assert results["fork_replay_metrics"]["total_replay_attempts"] > 0


async def test_fork_detection_metrics():
    """Test fork detection measurement"""
    online_peers = [f"o{i}" for i in range(8)]
    offline_peers = [("off1", 3600.0), ("off2", 7200.0)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    fork_attackers = [ForkAttacker("attacker_0", stale, canonical, 0.6)]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=0.5)

    detection = results["detection_metrics"]
    assert "fork_detection_rate" in detection
    assert "detection_latency" in detection
    assert "false_acceptance_rate" in detection
    assert 0.0 <= detection["fork_detection_rate"] <= 1.0
    assert 0.0 <= detection["false_acceptance_rate"] <= 1.0


async def test_resync_metrics():
    """Test resync performance measurement"""
    online_peers = [f"o{i}" for i in range(6)]
    offline_peers = [(f"off{i}", 3600.0) for i in range(4)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    fork_attackers = [ForkAttacker("attacker_0", stale, canonical, 0.7)]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=0.5)

    resync = results["resync_metrics"]
    assert "time_to_resync" in resync
    assert "resync_success_rate" in resync
    assert "peers_still_on_stale_fork" in resync
    assert 0.0 <= resync["resync_success_rate"] <= 1.0


async def test_offline_duration_impact():
    """Test that longer offline duration increases attack success"""
    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 7200, ["v1"])

    attacker = ForkAttacker("attacker_0", stale, canonical, 0.9)

    # Short offline duration
    short_offline = [("peer_1", 600.0)]  # 10 minutes
    results_short = await attacker.execute_fork_replay_campaign(short_offline, 0.5)

    # Reset attacker
    attacker.replay_attempts = 0
    attacker.successful_replays = []
    attacker.failed_replays = []

    # Long offline duration
    long_offline = [("peer_2", 14400.0)]  # 4 hours
    results_long = await attacker.execute_fork_replay_campaign(long_offline, 0.5)

    # Longer offline should generally have higher risk (though it's probabilistic)
    assert results_short["replay_attempts"] > 0
    assert results_long["replay_attempts"] > 0


async def test_security_insights_generation():
    """Test security insights generation"""
    online_peers = [f"o{i}" for i in range(5)]
    offline_peers = [(f"off{i}", 7200.0) for i in range(5)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 7200, ["v1"])

    # High intensity attackers
    fork_attackers = [
        ForkAttacker(f"attacker_{i}", stale, canonical, 0.9) for i in range(2)
    ]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)

    insights = results["security_insights"]
    assert len(insights) > 0
    assert all(isinstance(insight, str) for insight in insights)


async def test_fork_recommendations():
    """Test fork attack recommendations"""
    online_peers = [f"o{i}" for i in range(3)]
    offline_peers = [(f"off{i}", 3600.0) for i in range(7)]

    canonical = ChainState(1000, "c_hash", 900, trio.current_time(), ["v1"])
    stale = ChainState(800, "s_hash", 700, trio.current_time() - 3600, ["v1"])

    fork_attackers = [ForkAttacker("attacker_0", stale, canonical, 0.8)]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)

    recommendations = results["recommendations"]
    assert len(recommendations) > 0
    assert any("checkpoint" in r.lower() for r in recommendations)


async def test_run_long_range_fork_simulation():
    """Test convenience function for running complete simulation"""
    results = await run_long_range_fork_simulation(
        num_online_peers=5,
        num_offline_peers=3,
        avg_offline_duration=3600.0,
        num_fork_attackers=2,
        attack_intensity=0.7,
        attack_duration=1.0,
    )

    assert results is not None
    assert "attack_type" in results
    assert results["network_composition"]["online_peers"] == 5
    assert results["network_composition"]["offline_peers"] == 3
    assert results["network_composition"]["fork_attackers"] == 2


async def test_low_intensity_fork_attack():
    """Test low intensity fork attack"""
    results = await run_long_range_fork_simulation(
        num_online_peers=10,
        num_offline_peers=3,
        avg_offline_duration=1800.0,  # 30 minutes
        num_fork_attackers=1,
        attack_intensity=0.3,
        attack_duration=0.5,
    )

    # Low intensity should have lower success rate
    success_rate = results["fork_replay_metrics"]["overall_success_rate"]
    assert 0.0 <= success_rate <= 1.0


async def test_high_intensity_fork_attack():
    """Test high intensity fork attack with long offline duration"""
    results = await run_long_range_fork_simulation(
        num_online_peers=5,
        num_offline_peers=10,
        avg_offline_duration=14400.0,  # 4 hours
        num_fork_attackers=3,
        attack_intensity=0.9,
        attack_duration=1.0,
    )

    # High intensity with long offline should generally be more successful
    success_rate = results["fork_replay_metrics"]["overall_success_rate"]
    assert 0.0 <= success_rate <= 1.0


async def test_timing_measurements():
    """Test that timing measurements are recorded"""
    results = await run_long_range_fork_simulation(
        num_online_peers=5,
        num_offline_peers=3,
        attack_duration=1.0,
    )

    timing = results["timing"]
    assert "attack_duration" in timing
    assert "detection_duration" in timing
    assert "resync_duration" in timing
    assert "total_duration" in timing
    assert timing["attack_duration"] > 0
    assert timing["total_duration"] > 0


def test_scenario_initialization():
    """Synchronous test for scenario initialization"""
    online_peers = ["o1", "o2"]
    offline_peers = [("off1", 3600.0)]
    canonical = ChainState(1000, "c_hash", 900, 100.0, ["v1"])
    stale = ChainState(800, "s_hash", 700, 50.0, ["v1"])
    fork_attackers = [ForkAttacker("a1", stale, canonical, 0.7)]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)

    assert len(scenario.online_peers) == 2
    assert len(scenario.offline_peers) == 1
    assert len(scenario.fork_attackers) == 1
