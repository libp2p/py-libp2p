import pytest

from .replay_attack import ReplayAttacker, ReplayAttackScenario


@pytest.mark.trio
async def test_replay_attacker_capture_and_replay():
    attacker = ReplayAttacker("attacker_1", capture_capacity=5)
    for i in range(5):
        await attacker.capture_message({"from": "peer", "seq": i, "payload": f"x{i}"})
    assert len(attacker.captured_messages) == 5
    honest = ["h1", "h2"]
    await attacker.replay_messages(honest, times=1, delay=0.0)
    assert attacker.replayed_count == 5 * len(honest)


@pytest.mark.trio
async def test_replay_scenario_basic_execution():
    honest = ["h1", "h2", "h3"]
    a1 = ReplayAttacker("attacker_1", capture_capacity=3)
    scenario = ReplayAttackScenario(honest, [a1])
    results = await scenario.execute_replay()
    assert "total_captured" in results
    assert "total_replayed" in results
    assert "attack_metrics" in results
    assert results["total_captured"] >= 0
