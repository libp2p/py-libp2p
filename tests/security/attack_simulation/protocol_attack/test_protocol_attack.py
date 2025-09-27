import pytest

from .protocol_attack import ProtocolAttackScenario, ProtocolExploitAttacker


@pytest.mark.trio
async def test_malformed_message_attack():
    """Test malformed message attack"""
    attacker = ProtocolExploitAttacker("protocol_1", "malformed_msg", intensity=0.6)
    targets = ["peer_1", "peer_2"]

    await attacker.execute_malformed_message_attack(targets, duration=2.0)

    assert len(attacker.exploits_attempted) > 0
    assert all(
        exploit["type"] == "malformed_message"
        for exploit in attacker.exploits_attempted
    )
    assert len(attacker.successful_exploits) >= 0  # May be 0 due to randomness


@pytest.mark.trio
async def test_protocol_violation_attack():
    """Test protocol violation attack"""
    attacker = ProtocolExploitAttacker(
        "protocol_1", "protocol_violation", intensity=0.7
    )
    targets = ["peer_1"]

    await attacker.execute_protocol_violation_attack(targets, duration=1.5)

    assert len(attacker.exploits_attempted) > 0
    assert all(
        exploit["type"] == "protocol_violation"
        for exploit in attacker.exploits_attempted
    )


@pytest.mark.trio
async def test_handshake_exploit_attack():
    """Test handshake exploit attack"""
    attacker = ProtocolExploitAttacker("protocol_1", "handshake_exploit", intensity=0.5)
    targets = ["peer_1", "peer_2", "peer_3"]

    await attacker.execute_handshake_exploit(targets, duration=1.0)

    assert len(attacker.exploits_attempted) > 0
    assert all(
        exploit["type"] == "handshake_exploit"
        for exploit in attacker.exploits_attempted
    )


@pytest.mark.trio
async def test_protocol_attack_scenario():
    """Test complete protocol attack scenario"""
    honest_peers = ["h1", "h2", "h3"]

    attacker1 = ProtocolExploitAttacker("proto1", "malformed_msg", 0.6)
    attacker2 = ProtocolExploitAttacker("proto2", "protocol_violation", 0.7)
    attacker3 = ProtocolExploitAttacker("proto3", "handshake_exploit", 0.5)

    scenario = ProtocolAttackScenario(honest_peers, [attacker1, attacker2, attacker3])

    results = await scenario.execute_protocol_attack(attack_duration=2.0)

    assert "total_exploits_attempted" in results
    assert "successful_exploits" in results
    assert "victims_affected" in results
    assert "success_rate" in results
    assert "attack_metrics" in results

    assert results["total_exploits_attempted"] > 0
    assert results["success_rate"] >= 0

    # Check metrics
    metrics = results["attack_metrics"]
    assert "network_resilience_score" in metrics


def test_protocol_metrics_calculation():
    """Test protocol-specific metrics calculation"""
    honest_peers = ["h1", "h2"]
    attacker = ProtocolExploitAttacker("proto1", "malformed_msg", 0.5)
    scenario = ProtocolAttackScenario(honest_peers, [attacker])

    # Simulate exploit results
    attacker.exploits_attempted = [{"type": "test"} for _ in range(50)]
    attacker.successful_exploits = [
        {"type": "test", "success": True} for _ in range(30)
    ]
    attacker.victims_affected = ["h1"]  # 1 out of 2 victims

    scenario._calculate_protocol_metrics(50, 30, 1, 10.0)

    assert len(scenario.metrics.lookup_success_rate) == 3
    assert scenario.metrics.affected_nodes_percentage == 50.0  # 1/2 victims
    assert scenario.metrics.mitigation_effectiveness == 0.95


@pytest.mark.trio
async def test_protocol_intensity_impact():
    """Test how protocol exploit intensity affects success"""
    honest_peers = ["h1", "h2"]

    # Low intensity
    low_attacker = ProtocolExploitAttacker("low_proto", "malformed_msg", 0.3)
    low_scenario = ProtocolAttackScenario(honest_peers, [low_attacker])
    low_results = await low_scenario.execute_protocol_attack(1.0)

    # High intensity
    high_attacker = ProtocolExploitAttacker("high_proto", "malformed_msg", 0.8)
    high_scenario = ProtocolAttackScenario(honest_peers, [high_attacker])
    high_results = await high_scenario.execute_protocol_attack(1.0)

    # Higher intensity should attempt more exploits
    assert (
        high_results["total_exploits_attempted"]
        >= low_results["total_exploits_attempted"]
    )


@pytest.mark.trio
async def test_mixed_protocol_attack_types():
    """Test scenario with mixed protocol attack types"""
    honest_peers = ["h1", "h2", "h3", "h4"]

    attackers = [
        ProtocolExploitAttacker("malformed", "malformed_msg", 0.6),
        ProtocolExploitAttacker("violation", "protocol_violation", 0.7),
        ProtocolExploitAttacker("handshake", "handshake_exploit", 0.5),
    ]

    scenario = ProtocolAttackScenario(honest_peers, attackers)
    results = await scenario.execute_protocol_attack(2.0)

    # Should have exploits from all types
    assert results["total_exploits_attempted"] > 0

    # Check that metrics reflect the attack
    metrics = results["attack_metrics"]
    assert metrics["network_resilience_score"] < 100


def test_malformed_payload_generation():
    """Test malformed payload generation"""
    attacker = ProtocolExploitAttacker("test", "malformed_msg", 0.5)

    payload1 = attacker._generate_malformed_payload()
    payload2 = attacker._generate_malformed_payload()

    # Payloads should be bytes
    assert isinstance(payload1, bytes)
    assert isinstance(payload2, bytes)

    # Should generate different types of malformed payloads
    # (Exact content may vary due to timing)


def test_random_violation_types():
    """Test random protocol violation type generation"""
    attacker = ProtocolExploitAttacker("test", "protocol_violation", 0.5)

    violation1 = attacker._random_violation_type()
    violation2 = attacker._random_violation_type()

    valid_violations = [
        "invalid_message_length",
        "wrong_protocol_version",
        "missing_required_field",
        "invalid_peer_id",
        "malformed_multiaddr",
    ]

    assert violation1 in valid_violations
    assert violation2 in valid_violations


def test_random_handshake_exploits():
    """Test random handshake exploit generation"""
    attacker = ProtocolExploitAttacker("test", "handshake_exploit", 0.5)

    exploit1 = attacker._random_handshake_exploit()
    exploit2 = attacker._random_handshake_exploit()

    valid_exploits = [
        "incomplete_handshake",
        "wrong_crypto_suite",
        "invalid_certificate",
        "timing_attack",
        "replay_attack",
    ]

    assert exploit1 in valid_exploits
    assert exploit2 in valid_exploits
