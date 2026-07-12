import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair as generate_new_ed25519_identity
from libp2p.peer.peerinfo import PeerInfo

pytestmark = pytest.mark.trio

_SERVER_LISTEN_ADDRS = [
    Multiaddr("/ip4/127.0.0.1/tcp/0"),
    Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
    Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
]


def _protocol_names(addr: Multiaddr) -> set[str]:
    return {p.name for p in addr.protocols()}


def _is_plain_tcp_addr(addr: Multiaddr) -> bool:
    protos = _protocol_names(addr)
    return "tcp" in protos and "ws" not in protos and "wss" not in protos


def _is_quic_addr(addr: Multiaddr) -> bool:
    return any(p.startswith("quic") for p in _protocol_names(addr))


async def _wait_for_listen_addr(
    host,
    predicate,
    *,
    label: str,
    attempts: int = 50,
    delay: float = 0.05,
) -> Multiaddr:
    """Poll until host advertises an address matching predicate."""
    for _ in range(attempts):
        matches = [a for a in host.get_addrs() if predicate(a)]
        if matches:
            return matches[0]
        await trio.sleep(delay)
    raise AssertionError(f"No {label} listen addr in {host.get_addrs()}")


async def test_all_three_bind_concurrently():
    """
    Three listeners must all be active after a single host.run() call.
    Timing: all three should start within a few hundred ms of each other
    (parallelism check).
    """
    kp = generate_new_ed25519_identity()
    host = new_host(
        key_pair=kp,
        enable_quic=True,
        enable_websocket=True,
        listen_addrs=_SERVER_LISTEN_ADDRS,
    )
    start = trio.current_time()
    async with host.run(listen_addrs=_SERVER_LISTEN_ADDRS):
        elapsed = trio.current_time() - start
        addrs = host.get_addrs()
        assert len(addrs) == 3, f"Expected 3 addrs, got {addrs}"
        assert elapsed < 2.0, f"Parallel startup took {elapsed:.2f}s — too slow"


async def test_tcp_client_connects_to_tcp_listener():
    """TCP client must connect to a host that also has QUIC and WS active."""
    server = new_host(
        enable_quic=True,
        enable_websocket=True,
        listen_addrs=_SERVER_LISTEN_ADDRS,
    )
    async with server.run(listen_addrs=_SERVER_LISTEN_ADDRS):
        tcp_addr = await _wait_for_listen_addr(
            server, _is_plain_tcp_addr, label="plain TCP"
        )
        client = new_host(listen_addrs=[])
        async with client.run(listen_addrs=[]):
            await client.connect(PeerInfo(server.get_id(), [tcp_addr]))
            assert client.get_network().get_connection(server.get_id()) is not None


async def test_quic_client_connects_to_quic_listener():
    server = new_host(
        enable_quic=True,
        enable_websocket=True,
        listen_addrs=_SERVER_LISTEN_ADDRS[:2],
    )
    async with server.run(listen_addrs=_SERVER_LISTEN_ADDRS[:2]):
        quic_addr = await _wait_for_listen_addr(server, _is_quic_addr, label="QUIC")
        client = new_host(enable_quic=True, listen_addrs=[])
        async with client.run(listen_addrs=[]):
            await client.connect(PeerInfo(server.get_id(), [quic_addr]))
            conn = client.get_network().get_connection(server.get_id())
            assert any("quic" in str(addr) for addr in conn.get_transport_addresses())  # type: ignore
