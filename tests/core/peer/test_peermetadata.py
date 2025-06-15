import pytest

from libp2p.peer.id import ID
from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IPeerMetadata base class.


def test_get_empty():
    with pytest.raises(PeerStoreError):
        store = PeerStore()
        val = store.get(ID(b"peer"), "key")
        assert not val


def test_put_get_simple():
    store = PeerStore()
    store.put(ID(b"peer"), "key", "val")
    assert store.get(ID(b"peer"), "key") == "val"


def test_put_get_update():
    store = PeerStore()
    store.put(ID(b"peer"), "key1", "val1")
    store.put(ID(b"peer"), "key2", "val2")
    store.put(ID(b"peer"), "key2", "new val2")

    assert store.get(ID(b"peer"), "key1") == "val1"
    assert store.get(ID(b"peer"), "key2") == "new val2"


def test_put_get_two_peers():
    store = PeerStore()
    store.put(ID(b"peer1"), "key1", "val1")
    store.put(ID(b"peer2"), "key1", "val1 prime")

    assert store.get(ID(b"peer1"), "key1") == "val1"
    assert store.get(ID(b"peer2"), "key1") == "val1 prime"

    # Try update
    store.put(ID(b"peer2"), "key1", "new val1")

    assert store.get(ID(b"peer1"), "key1") == "val1"
    assert store.get(ID(b"peer2"), "key1") == "new val1"
