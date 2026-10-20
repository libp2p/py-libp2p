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

    def set_deadline(self, ttl: int) -> None:
        pass

    async def __aenter__(self) -> "IMuxedStream":
        return self


@pytest.fixture
def mock_stream():
    """Create a mock stream for testing."""
    muxed_stream = MockMuxedStream()
    return NetStream(muxed_stream, None, None)


@pytest.mark.trio
async def test_state_transition_logging(mock_stream):
    """Test that state transitions are logged."""
    # This test verifies that set_state method exists and works
    # The actual logging behavior would be tested in integration tests
    await mock_stream.set_state(StreamState.OPEN)
    assert await mock_stream.state == StreamState.OPEN


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


class HalfCloseMuxedStream(MockMuxedStream):
    """Muxed stream exposing a dedicated write half-close (like QUICStream)."""

    def __init__(self):
        super().__init__()
        self.close_calls = 0
        self.close_write_calls = 0

    async def close(self) -> None:
        self.close_calls += 1

    async def close_write(self) -> None:
        self.close_write_calls += 1


class FullCloseOnlyMuxedStream(MockMuxedStream):
    """Muxed stream whose close() is already a half-close (Yamux/Mplex)."""

    def __init__(self):
        super().__init__()
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.trio
async def test_close_write_prefers_muxed_close_write():
    """
    close_write() must not close the read side when the muxer can half-close.

    QUICStream.close() closes both directions; calling it for a write
    half-close makes the next read return EOF immediately (perf download
    received 0 bytes).
    """
    muxed = HalfCloseMuxedStream()
    stream = NetStream(muxed, None, None)
    await stream.set_state(StreamState.OPEN)

    await stream.close_write()

    assert muxed.close_write_calls == 1
    assert muxed.close_calls == 0
    assert await stream.state == StreamState.CLOSE_WRITE


@pytest.mark.trio
async def test_close_write_falls_back_to_close():
    """Yamux/Mplex only expose close(), which is already a write half-close."""
    muxed = FullCloseOnlyMuxedStream()
    stream = NetStream(muxed, None, None)
    await stream.set_state(StreamState.OPEN)

    await stream.close_write()

    assert muxed.close_calls == 1
    assert await stream.state == StreamState.CLOSE_WRITE
