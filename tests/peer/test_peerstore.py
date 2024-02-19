import pytest

from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IPeerStore base class.


def test_peer_info_empty():
    store = PeerStore()
    with pytest.raises(PeerStoreError):
        store.peer_info("peer")


def test_peer_info_basic():
    store = PeerStore()
    store.add_addr("peer", "/foo", 10)
    info = store.peer_info("peer")

    assert info.peer_id == "peer"
    assert info.addrs == ["/foo"]


def test_add_get_protocols_basic():
    store = PeerStore()
    store.add_protocols("peer1", ["p1", "p2"])
    store.add_protocols("peer2", ["p3"])

    assert set(store.get_protocols("peer1")) == {"p1", "p2"}
    assert set(store.get_protocols("peer2")) == {"p3"}


def test_add_get_protocols_extend():
    store = PeerStore()
    store.add_protocols("peer1", ["p1", "p2"])
    store.add_protocols("peer1", ["p3"])

    assert set(store.get_protocols("peer1")) == {"p1", "p2", "p3"}


def test_set_protocols():
    store = PeerStore()
    store.add_protocols("peer1", ["p1", "p2"])
    store.add_protocols("peer2", ["p3"])

    store.set_protocols("peer1", ["p4"])
    store.set_protocols("peer2", [])

    assert set(store.get_protocols("peer1")) == {"p4"}
    assert set(store.get_protocols("peer2")) == set()


# Test with methods from other Peer interfaces.
def test_peers():
    store = PeerStore()
    store.add_protocols("peer1", [])
    store.put("peer2", "key", "val")
    store.add_addr("peer3", "/foo", 10)

    assert set(store.peer_ids()) == {"peer1", "peer2", "peer3"}
