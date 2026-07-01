import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair as generate_new_ed25519_identity
from libp2p.peer.peerinfo import PeerInfo

pytestmark = pytest.mark.trio


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
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
            Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
        ],
    )
    start = trio.current_time()
    async with host.run(
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
            Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
        ]
    ):
        elapsed = trio.current_time() - start
        addrs = host.get_addrs()
        assert len(addrs) == 3, f"Expected 3 addrs, got {addrs}"
        assert elapsed < 2.0, f"Parallel startup took {elapsed:.2f}s — too slow"


async def test_tcp_client_connects_to_tcp_listener():
    """TCP client must connect to a host that also has QUIC and WS active."""
    server = new_host(
        enable_quic=True,
        enable_websocket=True,
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
            Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
        ],
    )
    async with server.run(
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
            Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
        ]
    ):
        tcp_addr = next(
            a for a in server.get_addrs() if "tcp" in str(a) and "ws" not in str(a)
        )
        client = new_host(listen_addrs=[])
        async with client.run(listen_addrs=[]):
            await client.connect(PeerInfo(server.get_id(), [tcp_addr]))
            assert client.get_network().get_connection(server.get_id()) is not None


async def test_quic_client_connects_to_quic_listener():
    server = new_host(
        enable_quic=True,
        enable_websocket=True,
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
        ],
    )
    async with server.run(
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/0"),
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
        ]
    ):
        quic_addr = next(a for a in server.get_addrs() if "quic" in str(a))
        client = new_host(enable_quic=True, listen_addrs=[])
        async with client.run(listen_addrs=[]):
            await client.connect(PeerInfo(server.get_id(), [quic_addr]))
            conn = client.get_network().get_connection(server.get_id())
            assert any("quic" in str(addr) for addr in conn.get_transport_addresses())  # type: ignore
