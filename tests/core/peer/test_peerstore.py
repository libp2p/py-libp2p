import time

import pytest
from multiaddr import Multiaddr

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
