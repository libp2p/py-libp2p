"""
Test WebSocket transport closure handling to verify fixes for issue #1212.

This test verifies that:
- WebSocket read() raises ConnectionClosedError when connection is closed by peer
- read_exactly() detects closure immediately instead of retrying 100 times
- Close codes and reasons are available as structured attributes on the exception
- Reading from an already-closed connection raises plain IOException
"""

import pytest

from libp2p.io.exceptions import ConnectionClosedError, IOException
from libp2p.io.utils import read_exactly
from libp2p.transport.websocket.connection import P2PWebSocketConnection

# ---------------------------------------------------------------------------
# Helpers — mock trio_websocket's ConnectionClosed exception
# ---------------------------------------------------------------------------


class _MockConnectionClosed(Exception):
    """Simulate trio_websocket's ConnectionClosed with code/reason attrs."""

    def __init__(self, code: int, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(f"Connection closed: {reason}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_websocket_read_raises_on_closed_connection():
    """
    Test that WebSocket read() raises ConnectionClosedError (not b"") when
    the connection is closed by the peer, and that the structured close_code
    attribute is set correctly.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False
            self.messages = [b"test"]
            self.read_count = 0

        async def get_message(self):
            self.read_count += 1
            if self.read_count > 1:
                raise _MockConnectionClosed(code=1000, reason="Peer closed connection")
            if self.messages:
                return self.messages.pop(0)
            return b""

        async def send_message(self, data):
            if self.closed:
                raise Exception("Connection closed")

        async def aclose(self):
            self.closed = True

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Read initial data (should work)
    data1 = await ws_conn.read(4)
    assert data1 == b"test"

    # Next read should raise ConnectionClosedError (connection closed by peer)
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 2)

    exc = exc_info.value
    assert exc.close_code == 1000
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_message_boundary_handling():
    """
    Test that WebSocket properly handles message boundaries when yamux
    needs to read exact byte counts, and raises ConnectionClosedError
    on closure.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.messages = [
                b"\x00\x00\x00\x00\x00\x00",
                b"\x00\x00\x00\x00\x00\x00",
            ]
            self.read_count = 0

        async def get_message(self):
            if self.read_count < len(self.messages):
                msg = self.messages[self.read_count]
                self.read_count += 1
                return msg
            raise _MockConnectionClosed(code=1000, reason="Connection closed")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Should successfully read 12 bytes across 2 WebSocket messages
    header = await read_exactly(ws_conn, 12)
    assert len(header) == 12

    # Next read should detect connection closure with typed exception
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 2)

    exc = exc_info.value
    assert exc.close_code == 1000
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_websocket_close_code_and_reason_in_error():
    """
    Test that WebSocket close code and reason are available as structured
    attributes on ConnectionClosedError, not just buried in the message.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False

        async def get_message(self):
            self.closed = True
            raise _MockConnectionClosed(code=1001, reason="Going away")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    with pytest.raises(ConnectionClosedError) as exc_info:
        await ws_conn.read(10)

    exc = exc_info.value
    # Structured attributes — no string parsing needed
    assert exc.close_code == 1001
    assert exc.close_reason == "Going away"
    assert exc.transport == "websocket"
    # The message still contains human-readable context
    assert "1001" in str(exc)


@pytest.mark.trio
async def test_websocket_read_on_already_closed_connection():
    """
    Test that reading from an already-closed connection raises plain
    IOException immediately (local state check, not a peer closure).
    """

    class MockWebSocketConnection:
        async def get_message(self):
            return b"data"

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Manually set closed state
    ws_conn._closed = True

    # Should raise IOException immediately, not return b""
    # This is a local state check — NOT a ConnectionClosedError
    with pytest.raises(IOException, match="Connection is closed"):
        await ws_conn.read(10)


@pytest.mark.trio
async def test_read_exactly_detects_closure_immediately():
    """
    Test that read_exactly() gets an immediate ConnectionClosedError from the
    WebSocket connection instead of retrying 100 times on b"".
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False

        async def get_message(self):
            self.closed = True
            raise _MockConnectionClosed(code=1000, reason="Peer closed")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # read_exactly should raise on the first call, not after 100 retries
    with pytest.raises(ConnectionClosedError) as exc_info:
        await read_exactly(ws_conn, 12)

    exc = exc_info.value
    assert exc.close_code == 1000
    assert exc.transport == "websocket"


@pytest.mark.trio
async def test_connection_closed_error_is_subclass_of_ioexception():
    """
    Verify that ConnectionClosedError is a subclass of IOException so that
    existing ``except IOException`` handlers still catch it.
    """

    class MockWebSocketConnection:
        async def get_message(self):
            raise _MockConnectionClosed(code=1000, reason="Normal closure")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Should be catchable as IOException (backward compatibility)
    with pytest.raises(IOException):
        await ws_conn.read(10)

    # Reset connection for second test
    mock_ws2 = MockWebSocketConnection()
    ws_conn2 = P2PWebSocketConnection(mock_ws2)

    # Should also be catchable as ConnectionClosedError (new typed handler)
    with pytest.raises(ConnectionClosedError):
        await ws_conn2.read(10)
