"""
Leaving ``host.run()`` without calling ``host.close()`` must release the
host's connections and listeners (#1584).

The test factory closes swarms explicitly, so this exercises the path where
the service manager cancels ``Swarm.run()`` and its teardown runs in a
cancelled scope.
"""

import socket
from typing import Literal

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo

LISTEN = Multiaddr("/ip4/127.0.0.1/tcp/0")
PEERS = 5


@pytest.mark.trio
@pytest.mark.parametrize("muxer", ["YAMUX", "MPLEX"])
async def test_leaving_run_closes_connections_and_listener(
    muxer: Literal["YAMUX", "MPLEX"],
) -> None:
    def make_host() -> IHost:
        return new_host(key_pair=create_new_key_pair(), muxer_preference=muxer)

    stop = trio.Event()
    ready = trio.Semaphore(0)
    peers = [make_host() for _ in range(PEERS)]

    async def serve(peer: IHost) -> None:
        async with peer.run([LISTEN]):
            ready.release()
            await stop.wait()

    async with trio.open_nursery() as nursery:
        for peer in peers:
            nursery.start_soon(serve, peer)
        for _ in peers:
            await ready.acquire()

        hub = make_host()
        async with hub.run([LISTEN]):
            port_str = hub.get_addrs()[0].value_for_protocol("tcp")
            assert port_str is not None
            port = int(port_str)
            for peer in peers:
                await hub.connect(PeerInfo(peer.get_id(), peer.get_addrs()))
            assert len(hub.get_network().connections) == PEERS
        # No hub.close(): leaving run() alone must do the teardown.

        hub_id = hub.get_id()
        with trio.fail_after(10):
            while any(hub_id in p.get_network().connections for p in peers):
                await trio.sleep(0.05)

        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0, (
                "the stopped hub's listen port still accepts connections"
            )

        stop.set()
