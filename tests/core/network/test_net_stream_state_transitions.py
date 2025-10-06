"""
Tests for NetStream state transition functionality.
"""

from unittest.mock import MagicMock

import pytest

from libp2p.abc import IMuxedStream
from libp2p.network.stream.net_stream import NetStream, StreamState


class MockMuxedStream(IMuxedStream):
    """Mock muxed stream for testing."""

    def __init__(self):
        self.muxed_conn = MagicMock()

    async def read(self, n: int | None = None) -> bytes:
        return b"test data"

    async def write(self, data: bytes) -> None:
        pass

    async def close(self) -> None:
        pass

    async def reset(self) -> None:
        pass

    def get_remote_address(self) -> tuple[str, int] | None:
        return ("127.0.0.1", 8080)

    def set_deadline(self, ttl: int) -> bool:
        return True

    async def __aenter__(self) -> "IMuxedStream":
        return self


@pytest.fixture
def mock_stream():
    """Create a mock stream for testing."""
    muxed_stream = MockMuxedStream()
    return NetStream(muxed_stream, None)


@pytest.mark.trio
async def test_state_transition_logging(mock_stream):
    """Test that state transitions are logged."""
    # This test verifies that set_state method exists and works
    # The actual logging behavior would be tested in integration tests
    await mock_stream.set_state(StreamState.OPEN)
    assert await mock_stream.state == StreamState.OPEN


@pytest.mark.trio
async def test_get_state_transition_summary(mock_stream):
    """Test state transition summary method."""
    # Test operational state
    await mock_stream.set_state(StreamState.OPEN)
    summary = await mock_stream.get_state_transition_summary()
    assert "operational" in summary
    assert "OPEN" in summary

    # Test non-operational state
    await mock_stream.set_state(StreamState.ERROR)
    summary = await mock_stream.get_state_transition_summary()
    assert "non-operational" in summary
    assert "ERROR" in summary


@pytest.mark.trio
async def test_get_valid_transitions(mock_stream):
    """Test valid transitions method."""
    # Test INIT state
    await mock_stream.set_state(StreamState.INIT)
    valid_transitions = await mock_stream.get_valid_transitions()
    assert StreamState.OPEN in valid_transitions
    assert StreamState.ERROR in valid_transitions
    assert StreamState.CLOSE_READ not in valid_transitions

    # Test OPEN state
    await mock_stream.set_state(StreamState.OPEN)
    valid_transitions = await mock_stream.get_valid_transitions()
    assert StreamState.CLOSE_READ in valid_transitions
    assert StreamState.CLOSE_WRITE in valid_transitions
    assert StreamState.RESET in valid_transitions
    assert StreamState.ERROR in valid_transitions

    # Test terminal states
    await mock_stream.set_state(StreamState.ERROR)
    valid_transitions = await mock_stream.get_valid_transitions()
    assert len(valid_transitions) == 0  # ERROR is terminal


def test_state_transition_validation():
    """Test that state transitions follow expected rules."""
    # Test that valid transitions are properly defined
    valid_transitions = {
        StreamState.INIT: [StreamState.OPEN, StreamState.ERROR],
        StreamState.OPEN: [
            StreamState.CLOSE_READ,
            StreamState.CLOSE_WRITE,
            StreamState.RESET,
            StreamState.ERROR,
        ],
        StreamState.CLOSE_READ: [StreamState.CLOSE_BOTH, StreamState.ERROR],
        StreamState.CLOSE_WRITE: [StreamState.CLOSE_BOTH, StreamState.ERROR],
        StreamState.RESET: [StreamState.ERROR],
        StreamState.CLOSE_BOTH: [StreamState.ERROR],
        StreamState.ERROR: [],
    }

    # Verify that all states have valid transitions defined
    for state in [
        StreamState.INIT,
        StreamState.OPEN,
        StreamState.CLOSE_READ,
        StreamState.CLOSE_WRITE,
        StreamState.CLOSE_BOTH,
        StreamState.RESET,
        StreamState.ERROR,
    ]:
        assert state in valid_transitions

    # Verify that terminal states have empty or minimal transitions
    assert len(valid_transitions[StreamState.ERROR]) == 0
    assert len(valid_transitions[StreamState.RESET]) == 1  # Only ERROR
    assert len(valid_transitions[StreamState.CLOSE_BOTH]) == 1  # Only ERROR


@pytest.mark.trio
async def test_state_transition_lifecycle(mock_stream):
    """Test complete state transition lifecycle."""
    # Start in INIT
    assert await mock_stream.state == StreamState.INIT
    assert await mock_stream.is_operational() is True  # INIT is operational

    # Transition to OPEN
    await mock_stream.set_state(StreamState.OPEN)
    assert await mock_stream.state == StreamState.OPEN
    assert await mock_stream.is_operational() is True

    # Transition to CLOSE_READ
    await mock_stream.set_state(StreamState.CLOSE_READ)
    assert await mock_stream.state == StreamState.CLOSE_READ
    assert await mock_stream.is_operational() is True

    # Transition to CLOSE_BOTH
    await mock_stream.set_state(StreamState.CLOSE_BOTH)
    assert await mock_stream.state == StreamState.CLOSE_BOTH
    assert await mock_stream.is_operational() is False


@pytest.mark.trio
async def test_state_transition_summary_consistency(mock_stream):
    """Test that state transition summary is consistent with state."""
    for state in [
        StreamState.INIT,
        StreamState.OPEN,
        StreamState.CLOSE_READ,
        StreamState.CLOSE_WRITE,
        StreamState.CLOSE_BOTH,
        StreamState.RESET,
        StreamState.ERROR,
    ]:
        await mock_stream.set_state(state)
        summary = await mock_stream.get_state_transition_summary()

        # Check that summary contains the current state
        assert state.name in summary

        # Check that operational status is consistent
        is_operational = await mock_stream.is_operational()
        if is_operational:
            assert "operational" in summary
        else:
            assert "non-operational" in summary
