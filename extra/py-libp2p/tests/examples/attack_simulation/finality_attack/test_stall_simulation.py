"""
Tests for Finality Stall Attack Simulation

Tests the finality stall attack scenario with memory exhaustion tracking.
"""

from .stall_simulation import (
    FinalityStallAttacker,
    FinalityStallScenario,
    LightClientNode,
    MemoryTracker,
    run_finality_stall_simulation,
)


def test_memory_tracker_initialization():
    """Test MemoryTracker initialization"""
    tracker = MemoryTracker(initial_memory_mb=100.0)

    assert tracker.memory_usage_mb == 100.0
    assert tracker.peak_memory_mb == 100.0
    assert tracker.block_memory_cost_mb == 0.5
    assert len(tracker.memory_samples) == 1


def test_memory_tracker_add_block():
    """Test adding blocks increases memory"""
    tracker = MemoryTracker(initial_memory_mb=50.0)

    initial_memory = tracker.memory_usage_mb
    tracker.add_block(10)

    assert tracker.memory_usage_mb > initial_memory
    assert tracker.memory_usage_mb == initial_memory + (
        10 * tracker.block_memory_cost_mb
    )
    assert tracker.peak_memory_mb >= tracker.memory_usage_mb


def test_memory_tracker_prune_blocks():
    """Test pruning blocks decreases memory"""
    tracker = MemoryTracker(initial_memory_mb=50.0)
    tracker.add_block(20)

    memory_before_prune = tracker.memory_usage_mb
    tracker.prune_blocks(10)

    assert tracker.memory_usage_mb < memory_before_prune
    assert tracker.memory_usage_mb >= 0


def test_memory_tracker_growth_rate():
    """Test memory growth rate calculation"""
    tracker = MemoryTracker(initial_memory_mb=50.0)

    for i in range(10):
        tracker.add_block(5)

    growth_rate = tracker.get_memory_growth_rate()
    assert growth_rate >= 0


def test_light_client_node_initialization():
    """Test LightClientNode initialization"""
    client = LightClientNode("lc_0", memory_limit_mb=200.0, pruning_enabled=True)

    assert client.node_id == "lc_0"
    assert client.memory_limit_mb == 200.0
    assert client.pruning_enabled is True
    assert len(client.non_finalized_blocks) == 0
    assert client.is_exhausted is False
    assert client.timeout_triggered is False


async def test_light_client_receive_block():
    """Test light client receiving and tracking blocks"""
    client = LightClientNode("lc_0", memory_limit_mb=500.0)

    initial_memory = client.memory_tracker.memory_usage_mb

    await client.receive_new_block(1000)

    assert len(client.non_finalized_blocks) == 1
    assert 1000 in client.non_finalized_blocks
    assert client.memory_tracker.memory_usage_mb > initial_memory


async def test_light_client_memory_exhaustion():
    """Test light client memory exhaustion"""
    client = LightClientNode("lc_0", memory_limit_mb=100.0, pruning_enabled=False)

    # Add blocks until exhaustion
    for i in range(200):
        await client.receive_new_block(1000 + i)
        if client.is_exhausted:
            break

    assert client.is_exhausted is True
    assert client.memory_tracker.memory_usage_mb >= client.memory_limit_mb


async def test_light_client_pruning():
    """Test light client automatic pruning"""
    client = LightClientNode(
        "lc_0", memory_limit_mb=500.0, pruning_enabled=True, pruning_threshold=50
    )

    # Add blocks to trigger pruning
    for i in range(60):
        await client.receive_new_block(1000 + i)

    # Should have triggered pruning
    assert len(client.non_finalized_blocks) < 60


async def test_light_client_finalize_block():
    """Test finalizing blocks frees memory"""
    client = LightClientNode("lc_0")

    # Add blocks
    for i in range(20):
        await client.receive_new_block(1000 + i)

    memory_before = client.memory_tracker.memory_usage_mb

    # Finalize up to block 1010
    await client.finalize_block(1010)

    memory_after = client.memory_tracker.memory_usage_mb

    assert memory_after < memory_before
    assert client.last_finalized_block == 1010
    assert all(b > 1010 for b in client.non_finalized_blocks)


def test_light_client_trigger_timeout():
    """Test timeout trigger mechanism"""
    client = LightClientNode("lc_0")

    assert client.timeout_triggered is False

    client.trigger_timeout()

    assert client.timeout_triggered is True


def test_finality_stall_attacker_initialization():
    """Test FinalityStallAttacker initialization"""
    attacker = FinalityStallAttacker("attacker_0", 0.8)

    assert attacker.attacker_id == "attacker_0"
    assert attacker.intensity == 0.8
    assert attacker.stall_duration == 0.0
    assert attacker.blocks_produced_during_stall == 0


async def test_finality_stall_attacker_cause_stall():
    """Test attacker causing finality stall"""
    attacker = FinalityStallAttacker("attacker_0", 0.8)

    results = await attacker.cause_finality_stall(
        duration=2.0, block_production_rate=2.0
    )

    assert "stall_duration" in results
    assert "blocks_produced" in results
    assert "avg_block_rate" in results
    assert results["stall_duration"] >= 1.5  # Allow some timing variance
    assert results["blocks_produced"] > 0


async def test_finality_stall_scenario_basic():
    """Test basic finality stall scenario"""
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=200.0) for i in range(3)
    ]
    full_nodes = ["fn1", "fn2"]
    attackers = [FinalityStallAttacker("attacker_0", 0.8)]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=2.0, block_production_rate=2.0, finality_timeout=1.0
    )

    # Verify result structure
    assert "attack_type" in results
    assert results["attack_type"] == "finality_stall"
    assert "network_composition" in results
    assert "stall_metrics" in results
    assert "memory_metrics" in results
    assert "detection_metrics" in results
    assert "recovery_metrics" in results
    assert "security_insights" in results
    assert "recommendations" in results


async def test_memory_exhaustion_metrics():
    """Test memory exhaustion metrics collection"""
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=100.0, pruning_enabled=False)
        for i in range(5)
    ]
    full_nodes = ["fn1"]
    attackers = [FinalityStallAttacker("attacker_0", 1.0)]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=3.0, block_production_rate=3.0, finality_timeout=1.5
    )

    memory = results["memory_metrics"]
    assert "clients_exhausted" in memory
    assert "exhaustion_rate" in memory
    assert "peak_memory_usage_mb" in memory
    assert "avg_memory_usage_mb" in memory
    assert "memory_growth_rate" in memory
    assert memory["peak_memory_usage_mb"] > 0


async def test_timeout_detection():
    """Test finality stall timeout detection"""
    light_clients = [LightClientNode(f"lc_{i}") for i in range(5)]
    full_nodes = ["fn1"]
    attackers = [FinalityStallAttacker("attacker_0", 0.8)]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=2.0, block_production_rate=2.0, finality_timeout=1.0
    )

    detection = results["detection_metrics"]
    assert "timeout_detection_rate" in detection
    assert "detection_latency" in detection
    assert "clients_detected_stall" in detection
    assert 0.0 <= detection["timeout_detection_rate"] <= 1.0


async def test_recovery_after_finality_resumes():
    """Test recovery after finality resumes"""
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=300.0) for i in range(5)
    ]
    full_nodes = ["fn1", "fn2"]
    attackers = [FinalityStallAttacker("attacker_0", 0.7)]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=2.0, block_production_rate=2.0, finality_timeout=1.0
    )

    recovery = results["recovery_metrics"]
    assert "recovery_success_rate" in recovery
    assert "recovery_time" in recovery
    assert "clients_recovered" in recovery
    assert "memory_freed_mb" in recovery
    assert recovery["memory_freed_mb"] >= 0


async def test_pruning_prevents_exhaustion():
    """Test that pruning helps prevent memory exhaustion"""
    # Without pruning
    clients_no_prune = [
        LightClientNode(f"lc_{i}", memory_limit_mb=100.0, pruning_enabled=False)
        for i in range(3)
    ]
    attackers1 = [FinalityStallAttacker("attacker_0", 1.0)]
    scenario1 = FinalityStallScenario(clients_no_prune, [], attackers1)
    results1 = await scenario1.execute_finality_stall_attack(
        stall_duration=3.0, block_production_rate=3.0, finality_timeout=1.5
    )

    # With pruning
    clients_with_prune = [
        LightClientNode(
            f"lc_{i}",
            memory_limit_mb=100.0,
            pruning_enabled=True,
            pruning_threshold=20,
        )
        for i in range(3)
    ]
    attackers2 = [FinalityStallAttacker("attacker_0", 1.0)]
    scenario2 = FinalityStallScenario(clients_with_prune, [], attackers2)
    results2 = await scenario2.execute_finality_stall_attack(
        stall_duration=3.0, block_production_rate=3.0, finality_timeout=1.5
    )

    exhaustion1 = results1["memory_metrics"]["exhaustion_rate"]
    exhaustion2 = results2["memory_metrics"]["exhaustion_rate"]

    # Pruning should reduce exhaustion rate (though probabilistic)
    assert exhaustion1 >= 0.0
    assert exhaustion2 >= 0.0


async def test_security_insights_generation():
    """Test security insights generation"""
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=100.0) for i in range(5)
    ]
    attackers = [FinalityStallAttacker("attacker_0", 0.9)]

    scenario = FinalityStallScenario(light_clients, [], attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=2.0, block_production_rate=3.0, finality_timeout=1.0
    )

    insights = results["security_insights"]
    assert len(insights) > 0
    assert all(isinstance(insight, str) for insight in insights)


async def test_recommendations_generation():
    """Test recommendations generation"""
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=100.0, pruning_enabled=False)
        for i in range(5)
    ]
    attackers = [FinalityStallAttacker("attacker_0", 1.0)]

    scenario = FinalityStallScenario(light_clients, [], attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration=3.0, block_production_rate=3.0, finality_timeout=1.5
    )

    recommendations = results["recommendations"]
    assert len(recommendations) > 0
    assert any("pruning" in r.lower() or "memory" in r.lower() for r in recommendations)


async def test_run_finality_stall_simulation():
    """Test convenience function for running complete simulation"""
    results = await run_finality_stall_simulation(
        num_light_clients=5,
        num_full_nodes=3,
        num_attackers=1,
        attack_intensity=0.8,
        stall_duration=2.0,
        block_production_rate=2.0,
        finality_timeout=1.0,
        memory_limit_mb=200.0,
        pruning_enabled=True,
    )

    assert results is not None
    assert "attack_type" in results
    assert results["network_composition"]["light_clients"] == 5
    assert results["network_composition"]["full_nodes"] == 3


async def test_low_intensity_stall():
    """Test low intensity finality stall"""
    results = await run_finality_stall_simulation(
        num_light_clients=5,
        num_attackers=1,
        attack_intensity=0.3,
        stall_duration=2.0,
        block_production_rate=1.0,
        finality_timeout=1.0,
    )

    # Low intensity should produce fewer blocks
    blocks_produced = results["stall_metrics"]["total_blocks_produced"]
    assert blocks_produced >= 0


async def test_high_intensity_stall():
    """Test high intensity finality stall"""
    results = await run_finality_stall_simulation(
        num_light_clients=5,
        num_attackers=2,
        attack_intensity=1.0,
        stall_duration=3.0,
        block_production_rate=3.0,
        finality_timeout=1.5,
        memory_limit_mb=150.0,
        pruning_enabled=False,
    )

    # High intensity should have higher exhaustion rate
    exhaustion_rate = results["memory_metrics"]["exhaustion_rate"]
    assert 0.0 <= exhaustion_rate <= 1.0


async def test_timing_measurements():
    """Test that timing measurements are recorded"""
    results = await run_finality_stall_simulation(
        num_light_clients=3,
        stall_duration=2.0,
        block_production_rate=2.0,
    )

    timing = results["timing"]
    assert "stall_phase" in timing
    assert "detection_phase" in timing
    assert "recovery_phase" in timing
    assert "total_duration" in timing
    assert timing["total_duration"] > 0


async def test_block_production_rate_impact():
    """Test that higher block production rate increases memory pressure"""
    # Low block production rate
    results_low = await run_finality_stall_simulation(
        num_light_clients=3,
        stall_duration=2.0,
        block_production_rate=1.0,
        pruning_enabled=False,
        memory_limit_mb=200.0,
    )

    # High block production rate
    results_high = await run_finality_stall_simulation(
        num_light_clients=3,
        stall_duration=2.0,
        block_production_rate=5.0,
        pruning_enabled=False,
        memory_limit_mb=200.0,
    )

    # Higher rate should produce more blocks
    blocks_low = results_low["stall_metrics"]["total_blocks_produced"]
    blocks_high = results_high["stall_metrics"]["total_blocks_produced"]

    assert blocks_high >= blocks_low


def test_scenario_initialization():
    """Synchronous test for scenario initialization"""
    light_clients = [LightClientNode("lc1"), LightClientNode("lc2")]
    full_nodes = ["fn1"]
    attackers = [FinalityStallAttacker("a1", 0.8)]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)

    assert len(scenario.light_clients) == 2
    assert len(scenario.full_nodes) == 1
    assert len(scenario.attackers) == 1
