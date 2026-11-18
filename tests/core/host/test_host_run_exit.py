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
from libp2p.network import swarm as swarm_module
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


@pytest.mark.trio
async def test_stuck_connection_close_still_releases_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    If one connection never finishes closing, the bounded teardown gives up on
    it but still clears the swarm's state and closes the listener (#1600).
    """
    monkeypatch.setattr(swarm_module, "SHUTDOWN_CLEANUP_TIMEOUT", 0.5)
    monkeypatch.setattr(swarm_module, "SHUTDOWN_RETRY_TIMEOUT", 1.0)

    stop = trio.Event()
    ready = trio.Event()
    peer = new_host(key_pair=create_new_key_pair())

    async def serve() -> None:
        async with peer.run([LISTEN]):
            ready.set()
            await stop.wait()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(serve)
        await ready.wait()

        hub = new_host(key_pair=create_new_key_pair())
        network = hub.get_network()
        closed_listens: list[Multiaddr] = []

        async def record_listen_close(maddr: Multiaddr) -> None:
            closed_listens.append(maddr)

        async with hub.run([LISTEN]):
            port_str = hub.get_addrs()[0].value_for_protocol("tcp")
            assert port_str is not None
            port = int(port_str)
            await hub.connect(PeerInfo(peer.get_id(), peer.get_addrs()))
            (conn,) = network.connections[peer.get_id()]

            async def hang() -> None:
                await trio.sleep_forever()

            monkeypatch.setattr(conn, "close", hang)
            monkeypatch.setattr(network, "notify_listen_close", record_listen_close)
            started = trio.current_time()
        elapsed = trio.current_time() - started

        # 0.5s cleanup bound + 1.0s retry bound, with slack for slow CI.
        assert elapsed < 4.0, f"leaving run() took {elapsed:.2f}s"
        assert network.connections == {}
        assert network.listeners == {}
        assert len(closed_listens) == 1
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0

        stop.set()


@pytest.mark.trio
async def test_connection_registered_during_teardown_is_closed() -> None:
    """
    A dial already in flight when the auto-connector stops can register a
    connection while the teardown is closing the ones it found. Closing a
    single snapshot and then clearing the map would drop that connection
    unclosed and leak its socket, so the teardown drains instead (#1584).
    """
    stop = trio.Event()
    ready = trio.Semaphore(0)
    early, late = (new_host(key_pair=create_new_key_pair()) for _ in range(2))

    async def serve(peer: IHost) -> None:
        async with peer.run([LISTEN]):
            ready.release()
            await stop.wait()

    async with trio.open_nursery() as nursery:
        for peer in (early, late):
            nursery.start_soon(serve, peer)
            await ready.acquire()

        hub = new_host(key_pair=create_new_key_pair())
        network = hub.get_network()

        async with hub.run([LISTEN]):
            for peer in (early, late):
                await hub.connect(PeerInfo(peer.get_id(), peer.get_addrs()))
            (early_conn,) = network.connections[early.get_id()]
            (late_conn,) = network.connections[late.get_id()]

            # Stand `late` back in as if its dial had only just landed: it is
            # out of the map when the teardown takes its first look, and goes
            # back in while `early` is being closed.
            del network.connections[late.get_id()]
            real_close = early_conn.close

            async def close_then_readmit() -> None:
                network.connections[late.get_id()] = [late_conn]
                await real_close()

            early_conn.close = close_then_readmit  # type: ignore[method-assign]

        assert early_conn.is_closed, "the connection present at teardown was not closed"
        assert late_conn.is_closed, (
            "a connection registered during teardown was dropped without closing it"
        )
        assert network.connections == {}

        stop.set()
