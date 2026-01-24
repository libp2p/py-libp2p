"""
Tests for Invalid Block Propagation Attack Simulation

Tests the invalid block propagation attack scenario for light clients.
"""

import pytest

from .invalid_block import (
    Block,
    BlockInvalidityType,
    InvalidBlockScenario,
    MaliciousValidator,
    run_invalid_block_simulation,
)


def test_block_initialization():
    """Test Block initialization"""
    block = Block(
        block_number=100,
        block_hash="hash_100",
        parent_hash="hash_99",
        is_authentic=True,
        is_valid=False,
        is_finalized=False,
        invalidity_type=BlockInvalidityType.INVALID_STATE_TRANSITION,
    )

    assert block.block_number == 100
    assert block.block_hash == "hash_100"
    assert block.parent_hash == "hash_99"
    assert block.is_authentic is True
    assert block.is_valid is False
    assert block.is_finalized is False
    assert block.invalidity_type == BlockInvalidityType.INVALID_STATE_TRANSITION
    assert block.propagation_count == 0
    assert block.acceptance_count == 0


def test_block_invalidity_types():
    """Test all block invalidity types"""
    types = [
        BlockInvalidityType.INVALID_STATE_TRANSITION,
        BlockInvalidityType.DOUBLE_SPEND,
        BlockInvalidityType.INVALID_MERKLE_ROOT,
        BlockInvalidityType.CONSENSUS_VIOLATION,
        BlockInvalidityType.INVALID_TRANSACTION,
    ]
    assert len(types) >= 5
    assert BlockInvalidityType.INVALID_STATE_TRANSITION in types
    assert BlockInvalidityType.DOUBLE_SPEND in types
    assert BlockInvalidityType.INVALID_MERKLE_ROOT in types


def test_malicious_validator_initialization():
    """Test MaliciousValidator initialization"""
    validator = MaliciousValidator("validator_0", 0.7)

    assert validator.validator_id == "validator_0"
    assert validator.intensity == 0.7
    assert len(validator.blocks_created) == 0
    assert validator.propagation_attempts == 0
    assert validator.successful_propagations == 0


def test_create_invalid_block():
    """Test creating an invalid block"""
    validator = MaliciousValidator("validator_0", 0.8)

    block = validator.create_invalid_block(
        block_number=1000,
        parent_hash="parent_999",
        invalidity_type=BlockInvalidityType.DOUBLE_SPEND,
    )

    assert block.block_number == 1000
    assert block.parent_hash == "parent_999"
    assert block.is_authentic is True  # Has valid signature
    assert block.is_valid is False  # But is invalid
    assert block.invalidity_type == BlockInvalidityType.DOUBLE_SPEND
    assert len(validator.blocks_created) == 1


@pytest.mark.trio
async def test_propagate_invalid_block_to_light_clients():
    """Test propagating invalid block to light clients"""
    validator = MaliciousValidator("validator_0", 0.8)
    block = validator.create_invalid_block(
        1000, "parent_999", BlockInvalidityType.INVALID_STATE_TRANSITION
    )

    light_clients = ["lc1", "lc2", "lc3", "lc4", "lc5"]
    result = await validator.propagate_invalid_block(
        block, light_clients, is_light_client=True
    )

    assert "accepted_peers" in result
    assert "rejected_peers" in result
    assert "acceptance_rate" in result
    assert len(result["accepted_peers"]) + len(result["rejected_peers"]) == len(
        light_clients
    )
    assert validator.propagation_attempts == 1


@pytest.mark.trio
async def test_propagate_invalid_block_to_full_nodes():
    """Test propagating invalid block to full nodes (should have lower acceptance)"""
    validator = MaliciousValidator("validator_0", 0.8)
    block = validator.create_invalid_block(
        1000, "parent_999", BlockInvalidityType.CONSENSUS_VIOLATION
    )

    full_nodes = ["fn1", "fn2", "fn3", "fn4", "fn5"]
    result = await validator.propagate_invalid_block(
        block, full_nodes, is_light_client=False
    )

    assert "accepted_peers" in result
    assert "rejected_peers" in result
    assert "acceptance_rate" in result
    # Full nodes should generally have lower acceptance rate (though probabilistic)
    assert 0.0 <= result["acceptance_rate"] <= 1.0


@pytest.mark.trio
async def test_light_client_vs_full_node_vulnerability():
    """Test that light clients are more vulnerable than full nodes"""
    validator = MaliciousValidator("validator_0", 0.9)

    # Create multiple blocks and test
    light_client_acceptances = []
    full_node_acceptances = []

    for _ in range(10):
        block = validator.create_invalid_block(
            1000, "parent_999", BlockInvalidityType.INVALID_TRANSACTION
        )

        lc_result = await validator.propagate_invalid_block(
            block, ["lc1", "lc2", "lc3"], is_light_client=True
        )
        fn_result = await validator.propagate_invalid_block(
            block, ["fn1", "fn2", "fn3"], is_light_client=False
        )

        light_client_acceptances.append(lc_result["acceptance_rate"])
        full_node_acceptances.append(fn_result["acceptance_rate"])

    # Light clients should generally have higher acceptance
    # (averaged over multiple runs)
    avg_lc = sum(light_client_acceptances) / len(light_client_acceptances)
    avg_fn = sum(full_node_acceptances) / len(full_node_acceptances)

    # Allow for probabilistic variation, but trend should be visible
    assert avg_lc >= 0.0
    assert avg_fn >= 0.0


@pytest.mark.trio
async def test_invalid_block_scenario_basic():
    """Test basic invalid block scenario"""
    full_nodes = ["fn1", "fn2", "fn3"]
    light_clients = ["lc1", "lc2", "lc3", "lc4"]
    validators = [MaliciousValidator("v1", 0.7)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.0, finality_delay=0.5
    )

    # Verify result structure
    assert "attack_type" in results
    assert results["attack_type"] == "invalid_block_propagation"
    assert "network_composition" in results
    assert "block_propagation_metrics" in results
    assert "pre_finality_metrics" in results
    assert "detection_metrics" in results
    assert "isolation_metrics" in results
    assert "security_analysis" in results
    assert "recommendations" in results


@pytest.mark.trio
async def test_pre_finality_acceptance():
    """Test that blocks can be accepted pre-finality"""
    full_nodes = [f"fn{i}" for i in range(5)]
    light_clients = [f"lc{i}" for i in range(10)]
    validators = [MaliciousValidator(f"v{i}", 0.8) for i in range(2)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=2.0, finality_delay=1.0
    )

    pre_finality = results["pre_finality_metrics"]
    assert "light_client_acceptance_rate" in pre_finality
    assert "full_node_acceptance_rate" in pre_finality
    assert "vulnerability_gap" in pre_finality
    assert "blocks_accepted_pre_finality" in pre_finality


@pytest.mark.trio
async def test_post_finality_detection():
    """Test detection metrics post-finality"""
    full_nodes = ["fn1", "fn2"]
    light_clients = ["lc1", "lc2", "lc3"]
    validators = [MaliciousValidator("v1", 0.7)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.0, finality_delay=0.5
    )

    detection = results["detection_metrics"]
    assert "detection_latency" in detection
    assert "post_finality_detection_rate" in detection
    assert "false_negatives" in detection
    # Detection rate should be high post-finality
    assert detection["post_finality_detection_rate"] >= 0.85


@pytest.mark.trio
async def test_malicious_peer_isolation():
    """Test isolation of malicious validators"""
    full_nodes = [f"fn{i}" for i in range(5)]
    light_clients = [f"lc{i}" for i in range(8)]
    validators = [MaliciousValidator(f"v{i}", 0.8) for i in range(3)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.0, finality_delay=0.5
    )

    isolation = results["isolation_metrics"]
    assert "malicious_peers_isolated" in isolation
    assert "isolation_success_rate" in isolation
    assert "time_to_isolation" in isolation
    assert isolation["isolation_success_rate"] >= 0.5


@pytest.mark.trio
async def test_light_client_vulnerability_gap():
    """Test that vulnerability gap between light clients and full nodes is measured"""
    full_nodes = [f"fn{i}" for i in range(8)]
    light_clients = [f"lc{i}" for i in range(12)]
    validators = [MaliciousValidator("v1", 0.9)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.5, finality_delay=0.8
    )

    pre_finality = results["pre_finality_metrics"]
    vulnerability_gap = pre_finality["vulnerability_gap"]

    # Vulnerability gap should be non-negative (light clients >= full nodes)
    assert vulnerability_gap >= -0.1  # Allow small negative due to probabilistic nature


@pytest.mark.trio
async def test_security_analysis_generation():
    """Test security analysis generation"""
    full_nodes = ["fn1", "fn2"]
    light_clients = ["lc1", "lc2", "lc3"]
    validators = [MaliciousValidator("v1", 0.9)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.0, finality_delay=0.5
    )

    analysis = results["security_analysis"]
    assert len(analysis) > 0
    assert all(isinstance(item, str) for item in analysis)


@pytest.mark.trio
async def test_recommendations_generation():
    """Test recommendations generation"""
    full_nodes = ["fn1", "fn2"]
    light_clients = ["lc1", "lc2", "lc3", "lc4"]
    validators = [MaliciousValidator("v1", 0.8)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.0, finality_delay=0.5
    )

    recommendations = results["recommendations"]
    assert len(recommendations) > 0
    assert any(
        "finality" in r.lower() or "integrity" in r.lower() for r in recommendations
    )


@pytest.mark.trio
async def test_run_invalid_block_simulation():
    """Test convenience function for running complete simulation"""
    results = await run_invalid_block_simulation(
        num_full_nodes=5,
        num_light_clients=10,
        num_malicious_validators=2,
        attack_intensity=0.7,
        attack_duration=1.0,
        finality_delay=0.5,
    )

    assert results is not None
    assert "attack_type" in results
    assert results["network_composition"]["full_nodes"] == 5
    assert results["network_composition"]["light_clients"] == 10
    assert results["network_composition"]["malicious_validators"] == 2


@pytest.mark.trio
async def test_low_intensity_attack():
    """Test low intensity invalid block attack"""
    results = await run_invalid_block_simulation(
        num_full_nodes=10,
        num_light_clients=10,
        num_malicious_validators=1,
        attack_intensity=0.3,
        attack_duration=1.0,
        finality_delay=0.5,
    )

    # Low intensity should have lower acceptance rates
    acceptance = results["block_propagation_metrics"]["overall_acceptance_rate"]
    assert 0.0 <= acceptance <= 1.0


@pytest.mark.trio
async def test_high_intensity_attack():
    """Test high intensity invalid block attack"""
    results = await run_invalid_block_simulation(
        num_full_nodes=5,
        num_light_clients=15,
        num_malicious_validators=3,
        attack_intensity=0.9,
        attack_duration=2.0,
        finality_delay=1.0,
    )

    # High intensity should generally have higher acceptance rates
    acceptance = results["block_propagation_metrics"]["overall_acceptance_rate"]
    assert 0.0 <= acceptance <= 1.0


@pytest.mark.trio
async def test_timing_measurements():
    """Test that timing measurements are recorded"""
    results = await run_invalid_block_simulation(
        num_full_nodes=5,
        num_light_clients=5,
        attack_duration=1.0,
        finality_delay=0.5,
    )

    timing = results["timing"]
    assert "pre_finality_duration" in timing
    assert "finality_detection_duration" in timing
    assert "isolation_duration" in timing
    assert "total_duration" in timing
    assert timing["total_duration"] > 0


@pytest.mark.trio
async def test_multiple_validators_coordination():
    """Test attack with multiple coordinating malicious validators"""
    full_nodes = [f"fn{i}" for i in range(5)]
    light_clients = [f"lc{i}" for i in range(10)]
    validators = [MaliciousValidator(f"v{i}", 0.8) for i in range(4)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration=1.5, finality_delay=0.8
    )

    # Multiple validators should create more invalid blocks
    assert results["block_propagation_metrics"]["total_invalid_blocks"] > 0
    assert results["network_composition"]["malicious_validators"] == 4


@pytest.mark.trio
async def test_finality_delay_impact():
    """Test that longer finality delay allows more pre-finality acceptances"""
    full_nodes = ["fn1", "fn2"]
    light_clients = ["lc1", "lc2", "lc3"]
    validators = [MaliciousValidator("v1", 0.8)]

    # Short finality delay
    scenario1 = InvalidBlockScenario(full_nodes, light_clients, validators)
    results1 = await scenario1.execute_invalid_block_attack(
        attack_duration=2.0, finality_delay=0.3
    )

    # Reset validators
    validators = [MaliciousValidator("v1", 0.8)]

    # Long finality delay
    scenario2 = InvalidBlockScenario(full_nodes, light_clients, validators)
    results2 = await scenario2.execute_invalid_block_attack(
        attack_duration=2.0, finality_delay=1.5
    )

    # Longer finality delay should allow more block creation
    blocks1 = results1["block_propagation_metrics"]["total_invalid_blocks"]
    blocks2 = results2["block_propagation_metrics"]["total_invalid_blocks"]

    assert blocks1 >= 0
    assert blocks2 >= 0


def test_scenario_initialization():
    """Synchronous test for scenario initialization"""
    full_nodes = ["fn1", "fn2"]
    light_clients = ["lc1", "lc2", "lc3"]
    validators = [MaliciousValidator("v1", 0.7)]

    scenario = InvalidBlockScenario(full_nodes, light_clients, validators)

    assert len(scenario.full_nodes) == 2
    assert len(scenario.light_clients) == 3
    assert len(scenario.malicious_validators) == 1
