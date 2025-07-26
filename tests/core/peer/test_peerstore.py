import time

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IPeerStore base class.


def test_peer_info_empty():
    store = PeerStore()
    with pytest.raises(PeerStoreError):
        store.peer_info(ID(b"peer"))


def test_peer_info_basic():
    store = PeerStore()
    store.add_addr(ID(b"peer"), Multiaddr("/ip4/127.0.0.1/tcp/4001"), 1)

    # update ttl to new value
    store.add_addr(ID(b"peer"), Multiaddr("/ip4/127.0.0.1/tcp/4002"), 2)

    time.sleep(1)
    info = store.peer_info(ID(b"peer"))
    assert info.peer_id == ID(b"peer")
    assert info.addrs == [
        Multiaddr("/ip4/127.0.0.1/tcp/4001"),
        Multiaddr("/ip4/127.0.0.1/tcp/4002"),
    ]

    # Check that addresses are cleared after ttl
    time.sleep(2)
    info = store.peer_info(ID(b"peer"))
    assert info.peer_id == ID(b"peer")
    assert info.addrs == []
    assert store.peer_ids() == [ID(b"peer")]
    assert store.valid_peer_ids() == []


# Check if all the data remains valid if ttl is set to default(0)
def test_peer_permanent_ttl():
    store = PeerStore()
    store.add_addr(ID(b"peer"), Multiaddr("/ip4/127.0.0.1/tcp/4001"))
    time.sleep(1)
    info = store.peer_info(ID(b"peer"))
    assert info.peer_id == ID(b"peer")
    assert info.addrs == [Multiaddr("/ip4/127.0.0.1/tcp/4001")]


def test_add_get_protocols_basic():
    store = PeerStore()
    store.add_protocols(ID(b"peer1"), ["p1", "p2"])
    store.add_protocols(ID(b"peer2"), ["p3"])

    assert set(store.get_protocols(ID(b"peer1"))) == {"p1", "p2"}
    assert set(store.get_protocols(ID(b"peer2"))) == {"p3"}


def test_add_get_protocols_extend():
    store = PeerStore()
    store.add_protocols(ID(b"peer1"), ["p1", "p2"])
    store.add_protocols(ID(b"peer1"), ["p3"])

    assert set(store.get_protocols(ID(b"peer1"))) == {"p1", "p2", "p3"}


def test_set_protocols():
    store = PeerStore()
    store.add_protocols(ID(b"peer1"), ["p1", "p2"])
    store.add_protocols(ID(b"peer2"), ["p3"])

    store.set_protocols(ID(b"peer1"), ["p4"])
    store.set_protocols(ID(b"peer2"), [])

    assert set(store.get_protocols(ID(b"peer1"))) == {"p4"}
    assert set(store.get_protocols(ID(b"peer2"))) == set()


# Test with methods from other Peer interfaces.
def test_peers():
    store = PeerStore()
    store.add_protocols(ID(b"peer1"), [])
    store.put(ID(b"peer2"), "key", "val")
    store.add_addr(ID(b"peer3"), Multiaddr("/ip4/127.0.0.1/tcp/4001"), 10)

    assert set(store.peer_ids()) == {ID(b"peer1"), ID(b"peer2"), ID(b"peer3")}


@pytest.mark.trio
async def test_addr_stream_yields_new_addrs():
    store = PeerStore()
    peer_id = ID(b"peer1")
    addr1 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    addr2 = Multiaddr("/ip4/127.0.0.1/tcp/4002")

    collected = []

    async def consume_addrs():
        async for addr in store.addr_stream(peer_id):
            collected.append(addr)
            if len(collected) == 2:
                break

    async with trio.open_nursery() as nursery:
        nursery.start_soon(consume_addrs)
        await trio.sleep(2)  # Give time for the stream to start

        store.add_addr(peer_id, addr1, ttl=10)
        await trio.sleep(0.2)
        store.add_addr(peer_id, addr2, ttl=10)
        await trio.sleep(0.2)

        # After collecting expected addresses, cancel the stream
        nursery.cancel_scope.cancel()

    assert collected == [addr1, addr2]


@pytest.mark.trio
async def test_cleanup_task_remove_expired_data():
    store = PeerStore()
    peer_id = ID(b"peer123")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4040")

    # Insert addrs with short TTL (0.01s)
    store.add_addr(peer_id, addr, 1)

    assert store.addrs(peer_id) == [addr]
    assert peer_id in store.peer_data_map

    # Start cleanup task in a nursery
    async with trio.open_nursery() as nursery:
        # Run the cleanup task with a short interval so it runs soon
        nursery.start_soon(store.start_cleanup_task, 1)

        # Sleep long enough for TTL to expire and cleanup to run
        await trio.sleep(3)

        # Cancel the nursery to stop background tasks
        nursery.cancel_scope.cancel()

    # Confirm the peer data is gone from the peer_data_map
    assert peer_id not in store.peer_data_map
