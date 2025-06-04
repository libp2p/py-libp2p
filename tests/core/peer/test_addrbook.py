import pytest

from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IAddrBook base class.


def test_addrs_empty():
    with pytest.raises(PeerStoreError):
        store = PeerStore()
        val = store.addrs("peer")
        assert not val


def test_add_addr_single():
    store = PeerStore()
    store.add_addr("peer1", "/foo", 600)
    store.add_addr("peer1", "/bar", 600)
    store.add_addr("peer2", "/baz", 600)

    assert store.addrs("peer1") == ["/foo", "/bar"]
    assert store.addrs("peer2") == ["/baz"]


def test_add_addrs_multiple():
    store = PeerStore()
    store.add_addrs("peer1", ["/foo1", "/bar1"], 600)
    store.add_addrs("peer2", ["/foo2"], 600)

    assert store.addrs("peer1") == ["/foo1", "/bar1"]
    assert store.addrs("peer2") == ["/foo2"]


def test_clear_addrs():
    store = PeerStore()
    store.add_addrs("peer1", ["/foo1", "/bar1"], 600)
    store.add_addrs("peer2", ["/foo2"], 600)
    store.clear_addrs("peer1")

    assert store.addrs("peer1") == []
    assert store.addrs("peer2") == ["/foo2"]

    store.add_addrs("peer1", ["/foo1", "/bar1"], 600)

    assert store.addrs("peer1") == ["/foo1", "/bar1"]


def test_peers_with_addrs():
    store = PeerStore()
    store.add_addrs("peer1", [], 600)
    store.add_addrs("peer2", ["/foo"], 600)
    store.add_addrs("peer3", ["/bar"], 600)

    assert set(store.peers_with_addrs()) == {"peer2", "peer3"}

    store.clear_addrs("peer2")

    assert set(store.peers_with_addrs()) == {"peer3"}
