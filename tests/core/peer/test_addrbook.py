import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.envelope import Envelope, seal_record
from libp2p.peer.id import ID
from libp2p.peer.peer_record import PeerRecord
from libp2p.peer.peerstore import (
    PeerStore,
    PeerStoreError,
)

# Testing methods from IAddrBook base class.


def test_addrs_empty():
    with pytest.raises(PeerStoreError):
        store = PeerStore()
        val = store.addrs(ID(b"peer"))
        assert not val


def test_add_addr_single():
    store = PeerStore()
    store.add_addr(ID(b"peer1"), Multiaddr("/ip4/127.0.0.1/tcp/4001"), 10)
    store.add_addr(ID(b"peer1"), Multiaddr("/ip4/127.0.0.1/tcp/4002"), 10)
    store.add_addr(ID(b"peer2"), Multiaddr("/ip4/127.0.0.1/tcp/4003"), 10)

    assert store.addrs(ID(b"peer1")) == [
        Multiaddr("/ip4/127.0.0.1/tcp/4001"),
        Multiaddr("/ip4/127.0.0.1/tcp/4002"),
    ]
    assert store.addrs(ID(b"peer2")) == [Multiaddr("/ip4/127.0.0.1/tcp/4003")]


def test_add_addrs_multiple():
    store = PeerStore()
    store.add_addrs(
        ID(b"peer1"),
        [Multiaddr("/ip4/127.0.0.1/tcp/40011"), Multiaddr("/ip4/127.0.0.1/tcp/40021")],
        10,
    )
    store.add_addrs(ID(b"peer2"), [Multiaddr("/ip4/127.0.0.1/tcp/40012")], 10)

    assert store.addrs(ID(b"peer1")) == [
        Multiaddr("/ip4/127.0.0.1/tcp/40011"),
        Multiaddr("/ip4/127.0.0.1/tcp/40021"),
    ]
    assert store.addrs(ID(b"peer2")) == [Multiaddr("/ip4/127.0.0.1/tcp/40012")]


def test_clear_addrs():
    store = PeerStore()
    store.add_addrs(
        ID(b"peer1"),
        [Multiaddr("/ip4/127.0.0.1/tcp/40011"), Multiaddr("/ip4/127.0.0.1/tcp/40021")],
        10,
    )
    store.add_addrs(ID(b"peer2"), [Multiaddr("/ip4/127.0.0.1/tcp/40012")], 10)
    store.clear_addrs(ID(b"peer1"))

    assert store.addrs(ID(b"peer1")) == []
    assert store.addrs(ID(b"peer2")) == [Multiaddr("/ip4/127.0.0.1/tcp/40012")]

    store.add_addrs(
        ID(b"peer1"),
        [Multiaddr("/ip4/127.0.0.1/tcp/40011"), Multiaddr("/ip4/127.0.0.1/tcp/40021")],
        10,
    )

    assert store.addrs(ID(b"peer1")) == [
        Multiaddr("/ip4/127.0.0.1/tcp/40011"),
        Multiaddr("/ip4/127.0.0.1/tcp/40021"),
    ]


def test_peers_with_addrs():
    store = PeerStore()
    store.add_addrs(ID(b"peer1"), [], 10)
    store.add_addrs(ID(b"peer2"), [Multiaddr("/ip4/127.0.0.1/tcp/4001")], 10)
    store.add_addrs(ID(b"peer3"), [Multiaddr("/ip4/127.0.0.1/tcp/4002")], 10)

    assert set(store.peers_with_addrs()) == {ID(b"peer2"), ID(b"peer3")}

    store.clear_addrs(ID(b"peer2"))

    assert set(store.peers_with_addrs()) == {ID(b"peer3")}


def test_ceritified_addr_book():
    store = PeerStore()

    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    addrs = [
        Multiaddr("/ip4/127.0.0.1/tcp/9000"),
        Multiaddr("/ip4/127.0.0.1/tcp/9001"),
    ]
    ttl = 60

    # Construct signed PereRecord
    record = PeerRecord(peer_id, addrs, 21)
    envelope = seal_record(record, key_pair.private_key)

    result = store.consume_peer_record(envelope, ttl)
    assert result is True
    # Retrieve the record

    retrieved = store.get_peer_record(peer_id)
    assert retrieved is not None
    assert isinstance(retrieved, Envelope)

    addr_list = store.addrs(peer_id)
    assert set(addr_list) == set(addrs)

    # Now try to push an older record (should be rejected)
    old_record = PeerRecord(peer_id, [Multiaddr("/ip4/10.0.0.1/tcp/4001")], 20)
    old_envelope = seal_record(old_record, key_pair.private_key)
    result = store.consume_peer_record(old_envelope, ttl)
    assert result is False

    # Push a new record (should override)
    new_addrs = [Multiaddr("/ip4/192.168.0.1/tcp/5001")]
    new_record = PeerRecord(peer_id, new_addrs, 23)
    new_envelope = seal_record(new_record, key_pair.private_key)
    result = store.consume_peer_record(new_envelope, ttl)
    assert result is True

    # Confirm the record is updated
    latest = store.get_peer_record(peer_id)
    assert isinstance(latest, Envelope)
    assert latest.record().seq == 23

    # Merged addresses = old addres + new_addrs
    expected_addrs = set(new_addrs)
    actual_addrs = set(store.addrs(peer_id))
    assert actual_addrs == expected_addrs
