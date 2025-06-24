import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.peer.id import ID
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
