import pytest

from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IPeerMetadata base class.


def test_get_empty():
    with pytest.raises(PeerStoreError):
        store = PeerStore()
        val = store.get("peer", "key")
        assert not val


def test_put_get_simple():
    store = PeerStore()
    store.put("peer", "key", "val")
    assert store.get("peer", "key") == "val"


def test_put_get_update():
    store = PeerStore()
    store.put("peer", "key1", "val1")
    store.put("peer", "key2", "val2")
    store.put("peer", "key2", "new val2")

    assert store.get("peer", "key1") == "val1"
    assert store.get("peer", "key2") == "new val2"


def test_put_get_two_peers():
    store = PeerStore()
    store.put("peer1", "key1", "val1")
    store.put("peer2", "key1", "val1 prime")

    assert store.get("peer1", "key1") == "val1"
    assert store.get("peer2", "key1") == "val1 prime"

    # Try update
    store.put("peer2", "key1", "new val1")

    assert store.get("peer1", "key1") == "val1"
    assert store.get("peer2", "key1") == "new val1"
