"""
Test WebSocket transport closure handling to verify fixes for issue #1212.

This test verifies that:
- WebSocket read() raises IOException when connection is closed (not b"")
- read_exactly() detects closure immediately instead of retrying 100 times
- Close codes and reasons are included in error messages
"""

import pytest

from libp2p.io.exceptions import IOException
from libp2p.io.utils import read_exactly
from libp2p.transport.websocket.connection import P2PWebSocketConnection


@pytest.mark.trio
async def test_websocket_read_raises_on_closed_connection():
    """
    Test that WebSocket read() properly raises IOException when the
    connection is closed by the peer, instead of returning b"".

    This is the core fix: read_exactly() will immediately detect closure
    instead of retrying up to 100 times on empty bytes.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False
            self.messages = [b"test"]
            self.read_count = 0

        async def get_message(self):
            self.read_count += 1
            if self.read_count > 1:
                # Simulate connection close after first message
                class ConnectionClosed(Exception):
                    def __init__(self, code, reason):
                        self.code = code
                        self.reason = reason
                        super().__init__(f"Connection closed: {reason}")

                raise ConnectionClosed(code=1000, reason="Peer closed connection")
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

    # Next read should raise IOException (connection closed by peer)
    with pytest.raises(IOException) as exc_info:
        await read_exactly(ws_conn, 2)

    error_msg = str(exc_info.value)
    assert (
        "WebSocket" in error_msg
        or "connection closed" in error_msg.lower()
        or "code=1000" in error_msg
        or "peer" in error_msg.lower()
    )


@pytest.mark.trio
async def test_websocket_message_boundary_handling():
    """
    Test that WebSocket properly handles message boundaries when yamux
    needs to read exact byte counts, and raises IOException on closure.
    """

    class MockWebSocketConnection:
        def __init__(self):
            # Simulate message boundary: header split across 2 messages
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

            # After messages exhausted, simulate connection close
            class ConnectionClosed(Exception):
                def __init__(self, code, reason):
                    self.code = code
                    self.reason = reason
                    super().__init__(f"Connection closed: {reason}")

            raise ConnectionClosed(code=1000, reason="Connection closed")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Should successfully read 12 bytes across 2 WebSocket messages
    header = await read_exactly(ws_conn, 12)
    assert len(header) == 12

    # Next read should detect connection closure with clear error
    with pytest.raises(IOException) as exc_info:
        await read_exactly(ws_conn, 2)

    error_msg = str(exc_info.value)
    assert (
        "WebSocket" in error_msg
        or "connection" in error_msg.lower()
        or "code=1000" in error_msg
    )


@pytest.mark.trio
async def test_websocket_close_code_and_reason_in_error():
    """
    Test that WebSocket close code and reason are included in error messages.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False

        async def get_message(self):
            self.closed = True

            class ConnectionClosed(Exception):
                def __init__(self, code, reason):
                    self.code = code
                    self.reason = reason
                    super().__init__(f"Connection closed: {reason}")

            raise ConnectionClosed(code=1001, reason="Going away")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    with pytest.raises(IOException) as exc_info:
        await ws_conn.read(10)

    error_msg = str(exc_info.value)
    # Verify close code and reason are in the error message
    assert "1001" in error_msg or "code=1001" in error_msg
    assert (
        "Going away" in error_msg
        or "reason" in error_msg.lower()
        or "code=1001" in error_msg
    )


@pytest.mark.trio
async def test_websocket_read_on_already_closed_connection():
    """
    Test that reading from an already-closed connection raises IOException
    immediately (the core fix — not returning b"").
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
    with pytest.raises(IOException, match="Connection is closed"):
        await ws_conn.read(10)


@pytest.mark.trio
async def test_read_exactly_detects_closure_immediately():
    """
    Test that read_exactly() gets an immediate IOException from the WebSocket
    connection instead of retrying 100 times on b"".
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False

        async def get_message(self):
            self.closed = True

            class ConnectionClosed(Exception):
                def __init__(self, code, reason):
                    self.code = code
                    self.reason = reason
                    super().__init__(f"Connection closed: {reason}")

            raise ConnectionClosed(code=1000, reason="Peer closed")

        async def send_message(self, data):
            pass

        async def aclose(self):
            pass

    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # read_exactly should raise IOException on the first call, not after 100 retries
    with pytest.raises(IOException) as exc_info:
        await read_exactly(ws_conn, 12)

    error_msg = str(exc_info.value)
    assert (
        "WebSocket" in error_msg
        or "connection" in error_msg.lower()
        or "code=1000" in error_msg
        or "peer" in error_msg.lower()
    )
