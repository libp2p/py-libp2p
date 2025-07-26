from collections.abc import Sequence
from typing import Any

import pytest
from multiaddr import Multiaddr

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport

PLAINTEXT_PROTOCOL_ID = "/plaintext/1.0.0"


async def make_host(
    listen_addrs: Sequence[Multiaddr] | None = None,
) -> tuple[BasicHost, Any | None]:
    # Identity
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    # Upgrader
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

    # Transport + Swarm + Host
    transport = WebsocketTransport()
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)

    # Optionally run/listen
    ctx = None
    if listen_addrs:
        ctx = host.run(listen_addrs)
        await ctx.__aenter__()

    return host, ctx


@pytest.mark.trio
async def test_websocket_dial_and_listen():
    server_host, server_ctx = await make_host([Multiaddr("/ip4/127.0.0.1/tcp/0/ws")])
    client_host, _ = await make_host(None)

    peer_info = PeerInfo(server_host.get_id(), server_host.get_addrs())
    await client_host.connect(peer_info)

    assert client_host.get_network().connections.get(server_host.get_id())
    assert server_host.get_network().connections.get(client_host.get_id())

    await client_host.close()
    if server_ctx:
        await server_ctx.__aexit__(None, None, None)
    await server_host.close()
