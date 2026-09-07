"""Tests for the DHT Peer-ID chat example (issue #880)."""

from __future__ import annotations

import pytest
import trio

from libp2p import (
    new_host,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.kad_dht.kad_dht import (
    DHTMode,
    KadDHT,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.tools.anyio_service import (
    background_trio_service,
)
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
)

PROTOCOL_ID = TProtocol("/dht-chat/1.0.0")


def test_dht_chat_example_imports() -> None:
    from examples.dht_chat import dht_chat

    assert hasattr(dht_chat, "main")
    assert hasattr(dht_chat, "run")
    assert dht_chat.PROTOCOL_ID == PROTOCOL_ID


async def _seed_connected(dht: KadDHT) -> None:
    host = dht.host
    for peer_id in host.get_connected_peers():
        await dht.add_peer(peer_id)


@pytest.mark.trio
async def test_dht_chat_find_peer_then_message() -> None:
    """
    Three SERVER DHT peers: B and C join via A, then B looks up C by Peer ID
    (no multiaddr) and delivers a chat message over /dht-chat/1.0.0.
    """
    port_a = find_free_port()
    port_b = find_free_port()
    port_c = find_free_port()

    host_a = new_host()
    host_b = new_host()
    host_c = new_host()

    received = trio.Event()
    got: dict[str, bytes | None] = {"data": None}

    async with (
        host_a.run(listen_addrs=get_available_interfaces(port_a)),
        host_b.run(listen_addrs=get_available_interfaces(port_b)),
        host_c.run(listen_addrs=get_available_interfaces(port_c)),
    ):

        async def handler(stream: INetStream) -> None:
            data = await stream.read(1024)
            got["data"] = data
            received.set()
            await stream.close()

        host_c.set_stream_handler(PROTOCOL_ID, handler)

        dht_a = KadDHT(host_a, DHTMode.SERVER)
        dht_b = KadDHT(host_b, DHTMode.SERVER)
        dht_c = KadDHT(host_c, DHTMode.SERVER)

        async with (
            background_trio_service(dht_a),
            background_trio_service(dht_b),
            background_trio_service(dht_c),
        ):
            info_a = PeerInfo(host_a.get_id(), host_a.get_addrs())
            await host_b.connect(info_a)
            await host_c.connect(info_a)

            await _seed_connected(dht_a)
            await _seed_connected(dht_b)
            await _seed_connected(dht_c)

            # Intro peer must know both joiners for FIND_NODE to answer.
            await dht_a.add_peer(host_b.get_id())
            await dht_a.add_peer(host_c.get_id())
            await dht_b.add_peer(host_a.get_id())
            await dht_c.add_peer(host_a.get_id())

            found: PeerInfo | None = None
            with trio.fail_after(10):
                while True:
                    found = await dht_b.find_peer(host_c.get_id())
                    if found is not None and found.addrs:
                        break
                    await trio.sleep(0.2)

            assert found is not None
            assert found.peer_id == host_c.get_id()
            assert found.addrs

            await host_b.connect(found)
            stream = await host_b.new_stream(found.peer_id, [PROTOCOL_ID])
            try:
                await stream.write(b"hello-from-B\n")
            finally:
                await stream.close()

            with trio.fail_after(5):
                await received.wait()

            assert got["data"] == b"hello-from-B\n"
