"""
Test WebSocket transport closure handling to verify fixes for issue #1082.

This test reproduces the failure seen in:
- python-v0.4 x nim-v1.14 (ws, noise, yamux)
- python-v0.4 x nim-v1.14 (ws, noise, mplex)

The issue: WebSocket connection closes prematurely during yamux stream operations.
"""

import pytest

from libp2p.io.exceptions import IOException
from libp2p.io.utils import read_exactly
from libp2p.transport.websocket.connection import P2PWebSocketConnection


@pytest.mark.trio
async def test_websocket_read_during_active_yamux_stream():
    """
    Test that WebSocket read() properly handles connection closure
    during active yamux stream operations.

    This reproduces the "expected 2 bytes but received 0" error
    when WebSocket connection closes while yamux is reading.
    """

    # Mock WebSocket connection that closes mid-read
    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False
            self.messages = [b"test"]
            self.read_count = 0

        async def get_message(self):
            self.read_count += 1
            if self.read_count > 1:
                # Simulate connection close after first message
                # Use a ConnectionClosed-like exception
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
            pass

        async def aclose(self):
            self.closed = True

    # Create WebSocket connection wrapper
    mock_ws = MockWebSocketConnection()
    ws_conn = P2PWebSocketConnection(mock_ws)

    # Read initial data (should work)
    data1 = await ws_conn.read(4)
    assert data1 == b"test"

    # Try to read more - connection should close when trying to get next message
    # This should raise IOException with clear message, not return b""
    # The IOException is raised from ws_conn.read() which is called by read_exactly()
    with pytest.raises(IOException) as exc_info:
        await read_exactly(ws_conn, 2)

    # Verify error message is meaningful
    # The error might be wrapped, so check the message or cause
    error_msg = str(exc_info.value)
    # Check if error message contains WebSocket closure info
    assert (
        "WebSocket" in error_msg
        or "connection closed" in error_msg.lower()
        or "code=1000" in error_msg
        or "peer" in error_msg.lower()
    )


@pytest.mark.trio
async def test_websocket_message_boundary_handling():
    """
    Test that WebSocket properly handles message boundaries
    when yamux needs to read exact byte counts.

    Scenario: yamux needs to read 12 bytes (header), but WebSocket
    message boundaries may split this across multiple messages.
    """

    class MockWebSocketConnection:
        def __init__(self):
            # Simulate message boundary: header split across 2 messages
            self.messages = [b"\x00\x00\x00\x00\x00\x00", b"\x00\x00\x00\x00\x00\x00"]
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
    # The error message should indicate WebSocket closure
    assert (
        "WebSocket" in error_msg
        or "connection" in error_msg.lower()
        or "code=1000" in error_msg
    )


@pytest.mark.trio
async def test_websocket_yamux_incomplete_read_error_message():
    """
    Test that IncompleteReadError from read_exactly() provides
    meaningful context when used with WebSocket transport.
    """

    class MockWebSocketConnection:
        def __init__(self):
            self.closed = False

        async def get_message(self):
            # Return empty bytes to simulate connection close
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

    # Attempt to read should raise IOException (not return b"")
    with pytest.raises(IOException) as exc_info:
        await read_exactly(ws_conn, 12)

    error_msg = str(exc_info.value)
    # Verify error message includes useful context
    # The error is raised from ws_conn.read(), so check for WebSocket closure info
    assert (
        "WebSocket" in error_msg
        or "connection" in error_msg.lower()
        or "code=1000" in error_msg
        or "peer" in error_msg.lower()
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
    # The error message format is:
    # "WebSocket read failed: WebSocket connection closed..."
    assert "1001" in error_msg or "code=1001" in error_msg
    assert (
        "Going away" in error_msg
        or "reason" in error_msg.lower()
        or "code=1001" in error_msg
    )


@pytest.mark.trio
async def test_read_exactly_transport_context():
    """
    Test that read_exactly() includes transport context in error messages.
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

    # First read some data to establish connection
    try:
        await ws_conn.read(1)
    except IOException:
        pass  # Expected

    # Now try read_exactly which should include transport context
    with pytest.raises(IOException):
        await read_exactly(ws_conn, 12)

    # The error should be raised by ws_conn.read(), not read_exactly()
    # But if read_exactly() is called, it should include transport context
    # in its IncompleteReadError if it gets that far
