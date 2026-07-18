import pytest
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo

pytestmark = pytest.mark.trio


async def test_multi_port_demux():
    """
    Test that listening on multiple different ports, each with a TCP and WS component,
    works correctly and creates multiple PortDemultiplexers.
    """
    server = new_host(
        enable_quic=False,
        enable_websocket=True,
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/43510"),
            Multiaddr("/ip4/127.0.0.1/tcp/43510/ws"),
        ],
    )
    async with server.run(
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/43510"),
            Multiaddr("/ip4/127.0.0.1/tcp/43510/ws"),
        ]
    ):
        addrs = server.get_addrs()

        tcp_port = None
        ws_port = None
        for a in addrs:
            port = a.value_for_protocol("tcp")
            if "ws" in str(a):
                ws_port = port
            else:
                tcp_port = port

        assert (
            tcp_port == ws_port
        ), f"Expected same port for TCP and WS, got {tcp_port} and {ws_port}"

    # Now listen on two explicitly different ports to ensure they don't overwrite
    # each other or silently break.
    server2 = new_host(
        enable_quic=False,
        enable_websocket=True,
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/43511"),
            Multiaddr("/ip4/127.0.0.1/tcp/43511/ws"),
            Multiaddr("/ip4/127.0.0.1/tcp/43512"),
            Multiaddr("/ip4/127.0.0.1/tcp/43512/ws"),
        ],
    )
    async with server2.run(
        listen_addrs=[
            Multiaddr("/ip4/127.0.0.1/tcp/43511"),
            Multiaddr("/ip4/127.0.0.1/tcp/43511/ws"),
            Multiaddr("/ip4/127.0.0.1/tcp/43512"),
            Multiaddr("/ip4/127.0.0.1/tcp/43512/ws"),
        ]
    ):
        addrs2 = server2.get_addrs()
        assert len(addrs2) == 4, f"Expected 4 addrs, got {addrs2}"

        client1 = new_host(listen_addrs=[])
        async with client1.run(listen_addrs=[]):
            await client1.connect(
                PeerInfo(server2.get_id(), [Multiaddr("/ip4/127.0.0.1/tcp/43511")])
            )
            assert client1.get_network().get_connection(server2.get_id()) is not None

        client2 = new_host(listen_addrs=[])
        async with client2.run(listen_addrs=[]):
            await client2.connect(
                PeerInfo(server2.get_id(), [Multiaddr("/ip4/127.0.0.1/tcp/43512")])
            )
            assert client2.get_network().get_connection(server2.get_id()) is not None
