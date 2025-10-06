"""
Tests for NetStream ERROR state implementation.
"""

from unittest.mock import MagicMock

import pytest

from libp2p.abc import IMuxedStream
from libp2p.network.stream.exceptions import StreamError
from libp2p.network.stream.net_stream import NetStream, StreamState


class MockMuxedStream(IMuxedStream):
    """Mock muxed stream for testing."""

    def __init__(self):
        self.muxed_conn = MagicMock()
        self._should_fail = False
        self._fail_on_read = False
        self._fail_on_write = False
        self._fail_on_reset = False

    def set_fail_on_read(self, should_fail: bool = True):
        """Configure to fail on read operations."""
        self._fail_on_read = should_fail

    def set_fail_on_write(self, should_fail: bool = True):
        """Configure to fail on write operations."""
        self._fail_on_write = should_fail

    def set_fail_on_reset(self, should_fail: bool = True):
        """Configure to fail on reset operations."""
        self._fail_on_reset = should_fail

    async def read(self, n: int | None = None) -> bytes:
        """Mock read that can be configured to fail."""
        if self._fail_on_read:
            raise Exception("Simulated read error")
        return b"test data"

    async def write(self, data: bytes) -> None:
        """Mock write that can be configured to fail."""
        if self._fail_on_write:
            raise Exception("Simulated write error")

    async def close(self) -> None:
        """Mock close."""
        pass

    async def reset(self) -> None:
        """Mock reset that can be configured to fail."""
        if self._fail_on_reset:
            raise Exception("Simulated reset error")

    def get_remote_address(self) -> tuple[str, int] | None:
        """Mock remote address."""
        return ("127.0.0.1", 8080)

    def set_deadline(self, ttl: int) -> bool:
        """Mock set_deadline."""
        return True

    async def __aenter__(self) -> "IMuxedStream":
        """Mock async context manager entry."""
        return self


@pytest.fixture
def mock_stream():
    """Create a mock stream for testing."""
    muxed_stream = MockMuxedStream()
    return NetStream(muxed_stream, None)


@pytest.mark.trio
async def test_error_state_prevents_read(mock_stream):
    """Test that ERROR state prevents read operations."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Attempting to read should raise StreamError
    with pytest.raises(
        StreamError, match="Cannot read from stream; stream is in error state"
    ):
        await mock_stream.read()


@pytest.mark.trio
async def test_error_state_prevents_write(mock_stream):
    """Test that ERROR state prevents write operations."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Attempting to write should raise StreamError
    with pytest.raises(
        StreamError, match="Cannot write to stream; stream is in error state"
    ):
        await mock_stream.write(b"test data")


@pytest.mark.trio
async def test_error_state_prevents_close_read(mock_stream):
    """Test that ERROR state prevents close_read operations."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Attempting to close read should raise StreamError
    with pytest.raises(
        StreamError, match="Cannot close read on stream; stream is in error state"
    ):
        await mock_stream.close_read()


@pytest.mark.trio
async def test_error_state_prevents_close_write(mock_stream):
    """Test that ERROR state prevents close_write operations."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Attempting to close write should raise StreamError
    with pytest.raises(
        StreamError, match="Cannot close write on stream; stream is in error state"
    ):
        await mock_stream.close_write()


@pytest.mark.trio
async def test_error_state_allows_reset_for_cleanup(mock_stream):
    """Test that ERROR state allows reset operations for cleanup."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Reset should be allowed from ERROR state for cleanup purposes
    await mock_stream.reset()

    # Stream should be in RESET state after reset
    assert await mock_stream.state == StreamState.RESET


@pytest.mark.trio
async def test_read_error_triggers_error_state(mock_stream):
    """Test that read errors trigger ERROR state."""
    # Configure mock to fail on read
    mock_stream.muxed_stream.set_fail_on_read(True)

    # Attempting to read should set ERROR state and raise StreamError
    with pytest.raises(StreamError, match="Read operation failed"):
        await mock_stream.read()

    # Stream should be in ERROR state
    assert await mock_stream.state == StreamState.ERROR


@pytest.mark.trio
async def test_write_error_triggers_error_state(mock_stream):
    """Test that write errors trigger ERROR state."""
    # Configure mock to fail on write
    mock_stream.muxed_stream.set_fail_on_write(True)

    # Attempting to write should set ERROR state and raise StreamError
    with pytest.raises(StreamError, match="Write operation failed"):
        await mock_stream.write(b"test data")

    # Stream should be in ERROR state
    assert await mock_stream.state == StreamState.ERROR


@pytest.mark.trio
async def test_is_operational_with_error_state(mock_stream):
    """Test is_operational method with ERROR state."""
    # Set stream to ERROR state
    await mock_stream.set_state(StreamState.ERROR)

    # Stream should not be operational
    assert not await mock_stream.is_operational()


@pytest.mark.trio
async def test_is_operational_with_open_state(mock_stream):
    """Test is_operational method with OPEN state."""
    # Set stream to OPEN state
    await mock_stream.set_state(StreamState.OPEN)

    # Stream should be operational
    assert await mock_stream.is_operational()


@pytest.mark.trio
async def test_error_state_lifecycle():
    """Test complete ERROR state lifecycle."""
    muxed_stream = MockMuxedStream()
    stream = NetStream(muxed_stream, None)

    # Start in INIT state
    assert await stream.state == StreamState.INIT

    # Transition to OPEN
    await stream.set_state(StreamState.OPEN)
    assert await stream.state == StreamState.OPEN
    assert await stream.is_operational()

    # Simulate error by configuring mock to fail
    muxed_stream.set_fail_on_read(True)

    # Attempt read should trigger ERROR state
    with pytest.raises(StreamError):
        await stream.read()

    assert await stream.state == StreamState.ERROR
    assert not await stream.is_operational()

    # Attempt operations should fail
    with pytest.raises(StreamError):
        await stream.read()

    with pytest.raises(StreamError):
        await stream.write(b"data")

    # ERROR state is terminal - no recovery possible
    # Stream should remain in ERROR state
    assert await stream.state == StreamState.ERROR
    assert not await stream.is_operational()
