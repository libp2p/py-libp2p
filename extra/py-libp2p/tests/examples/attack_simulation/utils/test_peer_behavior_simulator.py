import pytest

from .peer_behavior_simulator import simulate_peer_behavior


@pytest.mark.trio
async def test_peer_simulation():
    events = await simulate_peer_behavior("peer1", 5)
    assert len(events) == 5
    assert events[0] == "peer1_msg_0"
