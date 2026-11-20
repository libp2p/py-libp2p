"""Transport ownership must end with the WebSocket or its abandoned dial."""

from types import SimpleNamespace
from typing import Any

import pytest
from multiaddr import Multiaddr
import trio
from trio.testing import wait_all_tasks_blocked
from trio_websocket import CloseReason, ConnectionClosed

from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.websocket.connection import P2PWebSocketConnection
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr
from libp2p.transport.websocket.transport import WebsocketConfig, WebsocketTransport


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
