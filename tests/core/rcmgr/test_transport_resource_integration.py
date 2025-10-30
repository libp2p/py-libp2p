"""
Tests ensuring TCP and WebSocket transports integrate with ResourceManager.
"""


import pytest
from multiaddr import Multiaddr

from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport


class MockRM:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_resource_available(self, resource_type: str, amount: int) -> bool:
        return self._available


def make_mock_rm(available: bool) -> MockRM:
    return MockRM(available)


@pytest.mark.trio
async def test_tcp_dial_respects_rm_limits(monkeypatch):
    tcp = TCP()
    tcp.set_resource_manager(make_mock_rm(False))

    # Use a valid-looking multiaddr; dial should fail fast before network call.
    maddr = Multiaddr("/ip4/127.0.0.1/tcp/6553")

    # If open_tcp_stream is called, we want to know, so fail the test.
    called = {"value": False}

    async def fake_open_tcp_stream(host: str, port: int):  # pragma: no cover
        called["value"] = True
        raise AssertionError("open_tcp_stream should not be called when RM denies")

    monkeypatch.setattr("trio.open_tcp_stream", fake_open_tcp_stream)

    with pytest.raises(OpenConnectionError):
        await tcp.dial(maddr)

    assert called["value"] is False


def test_tcp_listener_propagates_rm():
    tcp = TCP()
    rm = make_mock_rm(True)
    tcp.set_resource_manager(rm)
    async def _noop(conn):
        return None

    listener = tcp.create_listener(_noop)
    # Verify on concrete type to satisfy type-checkers
    from libp2p.transport.tcp.tcp import TCPListener

    assert isinstance(listener, TCPListener)
    assert hasattr(listener, "_resource_manager")
    assert listener._resource_manager is rm


@pytest.mark.trio
async def test_websocket_dial_respects_rm_limits(monkeypatch):
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={},
        muxer_transports_by_protocol={},
    )
    ws = WebsocketTransport(upgrader)
    ws.set_resource_manager(make_mock_rm(False))

    # Use ws over localhost; dial should fail before any network activity.
    maddr = Multiaddr("/ip4/127.0.0.1/tcp/6553/ws")

    # Ensure trio_websocket.connect_websocket is not called when denied.
    called = {"value": False}

    async def fake_connect_websocket(*args, **kwargs):  # pragma: no cover
        called["value"] = True
        raise AssertionError("connect_websocket should not be called when RM denies")

    target = (
        "libp2p.transport.websocket.transport.connect_websocket"
    )
    monkeypatch.setattr(target, fake_connect_websocket, raising=False)

    with pytest.raises(OpenConnectionError):
        await ws.dial(maddr)

    assert called["value"] is False


def test_websocket_listener_propagates_rm():
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={},
        muxer_transports_by_protocol={},
    )
    ws = WebsocketTransport(upgrader)
    rm = make_mock_rm(True)
    ws.set_resource_manager(rm)
    async def _noop(conn):
        return None

    listener = ws.create_listener(_noop)
    # Verify on concrete type to satisfy type-checkers
    from libp2p.transport.websocket.listener import WebsocketListener as WSListener

    assert isinstance(listener, WSListener)
    assert hasattr(listener, "_resource_manager")
    assert listener._resource_manager is rm


