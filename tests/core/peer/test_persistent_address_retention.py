"""Expiry and deletion must survive a peer's eviction from the memory cache."""

import pytest
from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.persistent.datastore.memory_sync import MemoryDatastoreSync
from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
from libp2p.peer.persistent.serialization import serialize_addresses
from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore


@pytest.fixture(params=["memory", "sqlite"])
def datastore(request, tmp_path):
    backend = (
        MemoryDatastoreSync()
        if request.param == "memory"
        else SQLiteDatastoreSync(tmp_path / "peers.db")
    )
    yield backend
    backend.close()


def test_address_expiry_survives_cache_eviction(monkeypatch, datastore):
    clock = [1000]
    monkeypatch.setattr("libp2p.peer.peerdata.time.time", lambda: clock[0])
    store = SyncPersistentPeerStore(datastore, max_cached_peers=1)
    peer, other = ID(b"peer"), ID(b"other")
    store.add_addrs(peer, [Multiaddr("/ip4/127.0.0.1/tcp/4001")], ttl=1)
    store.add_addrs(other, [Multiaddr("/ip4/127.0.0.1/tcp/4002")], ttl=1)
    assert peer not in store.peer_data_map
    clock[0] = 1002
    with pytest.raises(PeerStoreError, match="expired"):
        store.addrs(peer)


@pytest.mark.parametrize("field", ["addresses", "protocols", "metadata"])
def test_cleared_records_do_not_reappear_after_eviction(field, datastore):
    store = SyncPersistentPeerStore(datastore, max_cached_peers=1)
    peer, other = ID(b"peer"), ID(b"other")
    if field == "addresses":
        store.add_addrs(peer, [Multiaddr("/ip4/127.0.0.1/tcp/4001")], ttl=0)
        store.clear_addrs(peer)
    elif field == "protocols":
        store.add_protocols(peer, ["/test/1.0.0"])
        store.clear_protocol_data(peer)
    else:
        store.put(peer, "test", "value")
        store.clear_metadata(peer)
    store.add_protocols(other, ["/test/1.0.0"])
    assert peer not in store.peer_data_map
    if field == "addresses":
        assert store.addrs(peer) == []
    elif field == "protocols":
        assert store.get_protocols(peer) == []
    else:
        with pytest.raises(PeerStoreError):
            store.get(peer, "test")


def test_expiry_survives_sqlite_reopen(monkeypatch, tmp_path):
    clock = [1000]
    monkeypatch.setattr("libp2p.peer.peerdata.time.time", lambda: clock[0])
    path = tmp_path / "peers.db"
    peer = ID(b"peer")
    store = SyncPersistentPeerStore(SQLiteDatastoreSync(path))
    store.add_addrs(peer, [Multiaddr("/ip4/127.0.0.1/tcp/4001")], ttl=1)
    store.close()
    clock[0] = 1002
    reopened = SyncPersistentPeerStore(SQLiteDatastoreSync(path))
    try:
        with pytest.raises(PeerStoreError, match="expired"):
            reopened.addrs(peer)
    finally:
        reopened.close()


def test_permanent_and_legacy_addresses_remain_valid(monkeypatch, datastore):
    clock = [1000]
    monkeypatch.setattr("libp2p.peer.peerdata.time.time", lambda: clock[0])
    store = SyncPersistentPeerStore(datastore, max_cached_peers=1)
    permanent, legacy = ID(b"permanent"), ID(b"legacy")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    store.add_addrs(permanent, [addr], ttl=0)
    # Existing databases have address records without optional expiry metadata.
    datastore.put(store._get_addr_key(legacy), serialize_addresses([addr]))
    assert store.addrs(legacy) == [addr]
    clock[0] = 100000
    assert store.addrs(permanent) == [addr]
    assert store.addrs(legacy) == [addr]
