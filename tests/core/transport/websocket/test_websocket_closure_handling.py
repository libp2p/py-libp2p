"""
Test WebSocket transport closure handling to verify fixes for issue #1212.

This test verifies that:
- WebSocket read() raises ConnectionClosedError when connection is closed by peer
- read_exactly() detects closure immediately instead of retrying 100 times
- Close codes and reasons are available as structured attributes on the exception
- Reading from an already-closed connection raises plain IOException
"""

from types import SimpleNamespace
from typing import Any

import pytest
from multiaddr import Multiaddr
import trio
from trio.testing import wait_all_tasks_blocked
from trio_websocket import CloseReason, ConnectionClosed

from libp2p.io.exceptions import ConnectionClosedError, IOException
from libp2p.io.utils import read_exactly
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.websocket.connection import P2PWebSocketConnection
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr
from libp2p.transport.websocket.transport import WebsocketConfig, WebsocketTransport

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
                raise ConnectionClosed(CloseReason(1000, "Peer closed connection"))
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
            raise ConnectionClosed(CloseReason(1000, "Connection closed"))

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
            raise ConnectionClosed(CloseReason(1001, "Going away"))

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
            raise ConnectionClosed(CloseReason(1000, "Peer closed"))

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
            raise ConnectionClosed(CloseReason(1000, "Normal closure"))

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


@pytest.mark.trio
@pytest.mark.parametrize("mode", ["local", "remote", "cancel"])
async def test_closed_websockets_release_tracking_and_capacity(mode):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader, WebsocketConfig(max_connections=1))

    async def close():
        if mode == "cancel":
            await trio.sleep_forever()

    for _ in range(100):
        conn = P2PWebSocketConnection(SimpleNamespace(aclose=close))
        await transport._track_connection(conn)
        if mode == "remote":
            conn._handle_connection_closed_exception(
                ConnectionClosed(CloseReason(1000, "done"))
            )
        with trio.move_on_after(0.001 if mode == "cancel" else 5):
            await conn.close()
        assert not transport._connections
        assert transport._current_connections == 0


@pytest.mark.trio
async def test_cancelled_dial_closes_its_background_socket(monkeypatch):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader)

    class Socket:
        closed = False

        async def aclose(self):
            self.closed = True

    socket = Socket()

    async def open_socket(*args, **kwargs):
        return socket

    async def handshake(*args, **kwargs):
        await trio.sleep_forever()

    monkeypatch.setattr(trio, "open_tcp_stream", open_socket)
    monkeypatch.setattr("trio_websocket.wrap_client_stream", handshake)
    proto = parse_websocket_multiaddr(Multiaddr("/ip4/127.0.0.1/tcp/4001/ws"))
    async with trio.open_nursery() as nursery:
        transport.set_background_nursery(nursery)
        with trio.move_on_after(0.01) as scope:
            await transport._create_direct_connection(proto, None)
        assert scope.cancelled_caught
        await wait_all_tasks_blocked()
        assert socket.closed
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_closed_before_registration_is_rejected():
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader)

    async def close():
        pass

    conn = P2PWebSocketConnection(SimpleNamespace(aclose=close))
    await conn.close()
    with pytest.raises(OpenConnectionError, match="before registration"):
        await transport._track_connection(conn)
    assert not transport._connections


@pytest.mark.trio
async def test_cancelled_registration_closes_the_connected_socket(monkeypatch):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader)
    closed = []

    async def close():
        closed.append(True)

    conn = P2PWebSocketConnection(SimpleNamespace(aclose=close))

    async def connect(*args, **kwargs):
        return conn

    async def register(*args):
        await trio.sleep_forever()

    monkeypatch.setattr(transport, "_create_direct_connection", connect)
    monkeypatch.setattr(transport, "_track_connection", register)
    monkeypatch.setattr(
        "libp2p.transport.websocket.proxy_env.get_proxy_from_environment",
        lambda url: None,
    )
    proto = parse_websocket_multiaddr(Multiaddr("/ip4/127.0.0.1/tcp/4001/ws"))
    with trio.move_on_after(0.01) as scope:
        await transport._create_connection(proto)
    assert scope.cancelled_caught
    assert closed == [True]


@pytest.mark.trio
async def test_cancelled_close_stops_private_reader_and_socket(
    monkeypatch, autojump_clock
):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader)

    class Socket:
        closed = False

        async def aclose(self):
            self.closed = True

    class WebSocket:
        closed = None

        async def aclose(self):
            await trio.sleep_forever()

    socket = Socket()

    async def open_socket(*args, **kwargs):
        return socket

    async def handshake(*args, **kwargs):
        return WebSocket()

    monkeypatch.setattr(trio, "open_tcp_stream", open_socket)
    monkeypatch.setattr("trio_websocket.wrap_client_stream", handshake)
    proto = parse_websocket_multiaddr(Multiaddr("/ip4/127.0.0.1/tcp/4001/ws"))
    async with trio.open_nursery() as nursery:
        transport.set_background_nursery(nursery)
        conn = await transport._create_direct_connection(proto, None)
        with trio.move_on_after(0.001):
            await conn.close()
        await trio.sleep(1.1)
        assert socket.closed
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_unresponsive_close_releases_tracking_without_caller_timeout(
    autojump_clock,
):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader, WebsocketConfig(max_connections=1))

    async def close():
        await trio.sleep_forever()

    conn = P2PWebSocketConnection(SimpleNamespace(aclose=close))
    await transport._track_connection(conn)
    with trio.move_on_after(10) as guard:
        await conn.close()
    assert not guard.cancelled_caught, "close has no internal deadline"
    assert not transport._connections
    assert transport._current_connections == 0


@pytest.mark.trio
async def test_local_close_keeps_reader_until_handshake_finishes(
    monkeypatch, autojump_clock
):
    upgrader: Any = SimpleNamespace()
    transport = WebsocketTransport(upgrader)
    requested = trio.Event()
    acknowledged = trio.Event()

    class Socket:
        async def aclose(self):
            pass

    class WebSocket:
        closed: CloseReason | None = None

        async def aclose(self):
            self.closed = CloseReason(1000, "local close")
            requested.set()
            await acknowledged.wait()

    ws = WebSocket()

    async def reader():
        await requested.wait()
        await trio.sleep(2)
        acknowledged.set()
        await trio.sleep_forever()

    async def open_socket(*args, **kwargs):
        return Socket()

    async def handshake(nursery, *args, **kwargs):
        nursery.start_soon(reader)
        return ws

    monkeypatch.setattr(trio, "open_tcp_stream", open_socket)
    monkeypatch.setattr("trio_websocket.wrap_client_stream", handshake)
    proto = parse_websocket_multiaddr(Multiaddr("/ip4/127.0.0.1/tcp/4001/ws"))
    async with trio.open_nursery() as nursery:
        transport.set_background_nursery(nursery)
        conn = await transport._create_direct_connection(proto, None)
        await transport._track_connection(conn)
        with trio.move_on_after(10) as guard:
            await conn.close()
        assert not guard.cancelled_caught
        assert acknowledged.is_set(), "reader cancelled before close acknowledgement"
        assert not transport._connections
        nursery.cancel_scope.cancel()
