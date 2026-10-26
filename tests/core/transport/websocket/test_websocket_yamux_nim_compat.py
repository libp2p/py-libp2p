"""
Test WebSocket transport with yamux to reproduce and verify Nim interoperability fix.

This test reproduces the failure seen in:
- python-v0.4 x nim-v1.14 (ws, noise, yamux)
- python-v0.4 x nim-v1.14 (ws, noise, mplex)

The issue: WebSocket connection closes prematurely during yamux stream operations.
The fix: WebSocket read() now raises IOException instead of returning b"" when
connection closes.
"""

import logging

import pytest
from trio_websocket import CloseReason, ConnectionClosed

from libp2p.io.exceptions import ConnectionClosedError, IOException
from libp2p.io.utils import read_exactly
from libp2p.transport.websocket.connection import P2PWebSocketConnection

logger = logging.getLogger(__name__)


class MockWebSocketConnection:
    """Mock WebSocket connection for testing."""

    def __init__(self, messages: list[bytes] | None = None, close_after: int = 0):
        """
        Initialize mock WebSocket connection.

        Args:
            messages: List of messages to return before closing
            close_after: Number of messages to return before closing connection

        """
        self.closed = False
        self.messages = messages or []
        self.read_count = 0
        self.close_after = close_after
        self.close_code = 1000
        self.close_reason = "Peer closed connection"

    async def get_message(self) -> bytes:
        """Get next message or raise ConnectionClosed."""
        self.read_count += 1
        if self.close_after > 0 and self.read_count > self.close_after:
            # Simulate connection close after specified number of messages
            self.closed = True
            close_reason = CloseReason(code=self.close_code, reason=self.close_reason)
            raise ConnectionClosed(close_reason)
        if self.messages:
            return self.messages.pop(0)
        # If no messages and not closing, simulate connection close
        self.closed = True
        close_reason = CloseReason(code=self.close_code, reason=self.close_reason)
        raise ConnectionClosed(close_reason)

    async def send_message(self, data: bytes) -> None:
        """Send message (mock implementation)."""
        if self.closed:
            close_reason = CloseReason(code=self.close_code, reason=self.close_reason)
            raise ConnectionClosed(close_reason)

    async def aclose(self) -> None:
        """Close connection (mock implementation)."""
        self.closed = True


@pytest.mark.trio
async def test_websocket_read_during_active_yamux_stream():
    """
    Test that WebSocket read() properly handles connection closure
    during active yamux stream operations.

    This reproduces the "expected 2 bytes but received 0" error
    when WebSocket connection closes while yamux is reading.
    """
    # Mock WebSocket connection that closes after first message
    # First message provides partial data, then connection closes
    mock_ws = MockWebSocketConnection(messages=[b"te"], close_after=1)

    # Create WebSocket connection wrapper
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Read partial data (should work)
    data1 = await ws_conn.read(2)
    assert data1 == b"te"

    # Try to read more - connection should close
    # read() should raise IOException immediately (not return b"")
    # This is the key fix: immediate detection instead of retrying 100 times
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 2)

    # Verify structured attributes instead of fragile string matching
    exc = exc_info.value
    assert isinstance(exc, ConnectionClosedError)
    assert exc.close_code == 1000
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_message_boundary_handling():
    """
    Test that WebSocket properly handles message boundaries
    when yamux needs to read exact byte counts.

    Scenario: yamux needs to read 12 bytes (header), but WebSocket
    message boundaries may split this across multiple messages.
    """
    # Simulate message boundary: header split across 2 messages
    mock_ws = MockWebSocketConnection(
        messages=[b"\x00\x00\x00\x00\x00\x00", b"\x00\x00\x00\x00\x00\x00"],
        close_after=3,
    )

    ws_conn = P2PWebSocketConnection(mock_ws)

    # Should successfully read 12 bytes across 2 WebSocket messages
    header = await read_exactly(ws_conn, 12)
    assert len(header) == 12

    # Next read should detect connection closure with typed exception
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 2)

    exc = exc_info.value
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_yamux_incomplete_read_error_message():
    """
    Test that IncompleteReadError from read_exactly() provides
    meaningful context when used with WebSocket transport.
    """
    mock_ws = MockWebSocketConnection(messages=[], close_after=0)

    ws_conn = P2PWebSocketConnection(mock_ws)

    # Attempt to read should raise ConnectionClosedError (not return b"")
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 12)

    exc = exc_info.value
    assert exc.transport == "websocket"
    assert exc.close_code is not None


@pytest.mark.trio
async def test_websocket_connection_close_detection():
    """
    Test that connection closure is detected immediately and raises
    appropriate exception.
    """
    # Connection closes immediately
    mock_ws = MockWebSocketConnection(messages=[], close_after=0)
    mock_ws.close_code = 1000
    mock_ws.close_reason = "Connection closed by peer"

    ws_conn = P2PWebSocketConnection(mock_ws)

    # Should raise ConnectionClosedError immediately, not return b""
    with pytest.raises(ConnectionClosedError) as exc_info:
        await ws_conn.read(1)

    exc = exc_info.value
    assert isinstance(exc, ConnectionClosedError)
    assert exc.close_code == 1000
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_close_code_and_reason():
    """
    Test that WebSocket close codes and reasons are properly extracted
    and included in error messages.
    """
    mock_ws = MockWebSocketConnection(messages=[], close_after=0)
    mock_ws.close_code = 1001
    mock_ws.close_reason = "Going away"

    ws_conn = P2PWebSocketConnection(mock_ws)

    with pytest.raises(ConnectionClosedError) as exc_info:
        await ws_conn.read(1)

    exc = exc_info.value
    # Verify close code and reason via structured attributes
    assert exc.close_code == 1001
    assert exc.close_reason == "Going away"
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_read_none_on_close():
    """
    Test that read(n=None) also raises IOException when connection closes.
    """
    mock_ws = MockWebSocketConnection(messages=[], close_after=0)

    ws_conn = P2PWebSocketConnection(mock_ws)

    # read(n=None) should also raise ConnectionClosedError, not return b""
    with pytest.raises(ConnectionClosedError) as exc_info:
        await ws_conn.read(None)

    exc = exc_info.value
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_read_exactly_with_transport_context():
    """
    Test that read_exactly() includes transport context in error messages.
    """
    mock_ws = MockWebSocketConnection(messages=[b"partial"], close_after=1)

    ws_conn = P2PWebSocketConnection(mock_ws)

    # Read partial data
    await ws_conn.read(4)

    # Try to read more - should get IOException with transport context
    with pytest.raises(IOException):
        await read_exactly(ws_conn, 10)

    # Verify conn_state() method exists and works
    state = ws_conn.conn_state()
    assert isinstance(state, dict)
    assert state.get("transport") == "websocket"
    assert "connection_duration" in state
