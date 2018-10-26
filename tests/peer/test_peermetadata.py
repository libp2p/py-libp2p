from peer.peerstore import PeerStore

# Testing methods from IPeerMetadata base class.

def test_get_empty():
    store = PeerStore()
    val, err = store.get("peer", "key")
    assert not val
    assert err

def test_put_get_simple():
    store = PeerStore()
    store.put("peer", "key", "val")
    assert store.get("peer", "key") == ("val", None)

def test_put_get_update():
    store = PeerStore()
    store.put("peer", "key1", "val1")
    store.put("peer", "key2", "val2")
    store.put("peer", "key2", "new val2")

    assert store.get("peer", "key1") == ("val1", None)
    assert store.get("peer", "key2") == ("new val2", None)

def test_put_get_two_peers():
    store = PeerStore()
    store.put("peer1", "key1", "val1")
    store.put("peer2", "key1", "val1 prime")

    assert store.get("peer1", "key1") == ("val1", None)
    assert store.get("peer2", "key1") == ("val1 prime", None)

    # Try update
    store.put("peer2", "key1", "new val1")

    assert store.get("peer1", "key1") == ("val1", None)
    assert store.get("peer2", "key1") == ("new val1", None)