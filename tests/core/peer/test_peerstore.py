import pytest
import time

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
    store.add_addr("peer", "/foo", 2)
    
    # update ttl to new value
    store.add_addr("peer", "/foo2", 4) 
    
    time.sleep(2)
    info = store.peer_info("peer")
    assert info.peer_id == "peer"
    assert info.addrs == ["/foo", "/foo2"]
    
    # Check that addresses are cleared after ttl
    time.sleep(3)
    info = store.peer_info("peer")
    assert info.peer_id == "peer"
    assert info.addrs == []
    assert store.peer_ids() == ["peer"]
    assert store.valid_peer_ids() == []
    
# Check if all the data remains valid if ttl is set to default(0)
def test_peer_permanent_ttl():
    store = PeerStore()
    store.add_addr("peer", "/foo")
    time.sleep(2)
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
    store.add_addr("peer3", "/foo", 600)

    assert set(store.peer_ids()) == {"peer1", "peer2", "peer3"}
