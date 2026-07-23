import pytest
from libp2p.peer.id import ID
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.identity.identify_push.identify_push import (
    _update_peerstore_from_identify,
)
from multiaddr import Multiaddr
from libp2p.peer.peerstore import PeerStore


@pytest.mark.trio
async def test_pubkey_update_preserves_protocols():
    """Bug 1: Sending pubkey update should not clear protocols."""
    peer_id = ID.from_base58("QmQvGbd2FwM5WJMW226R7z8Z4KxXmBvjPXYz3yQ5f8XyA9")
    peerstore = PeerStore()
    peerstore.add_protocols(peer_id, ["/foo/1.0.0"])

    key_pair = create_new_key_pair()
    identify_msg = Identify()
    identify_msg.public_key = key_pair.public_key.serialize()

    await _update_peerstore_from_identify(peerstore, peer_id, identify_msg)

    assert "/foo/1.0.0" in peerstore.get_protocols(peer_id)



@pytest.mark.trio
async def test_private_addr_always_filtered():
    """Bug 4: Private addrs should be filtered even if no public addrs exist."""
    peer_id = ID.from_base58("QmQvGbd2FwM5WJMW226R7z8Z4KxXmBvjPXYz3yQ5f8XyA9")
    peerstore = PeerStore()

    identify_msg = Identify()
    # All private/loopback/link-local
    addrs = [
        Multiaddr("/ip4/127.0.0.1/tcp/1234"),
        Multiaddr("/ip4/10.0.0.1/tcp/1234"),
        Multiaddr("/ip4/192.168.1.1/tcp/1234"),
        Multiaddr("/ip4/169.254.1.1/tcp/1234"),
        Multiaddr("/ip4/172.16.0.1/tcp/1234"),
        Multiaddr("/ip6/::1/tcp/1234"),
        Multiaddr("/ip6/fe80::1/tcp/1234"),
    ]
    for a in addrs:
        identify_msg.listen_addrs.append(a.to_bytes())

    await _update_peerstore_from_identify(peerstore, peer_id, identify_msg)

    # Should raise because no addresses are found
    from libp2p.peer.peerstore import PeerStoreError
    with pytest.raises(PeerStoreError):
        peerstore.addrs(peer_id)


@pytest.mark.trio
async def test_pubkey_spoofing_rejected():
    """Bug 8: Pubkey spoofing should be rejected."""
    # A peer_id that does not match the key pair
    peer_id = ID.from_base58("QmQvGbd2FwM5WJMW226R7z8Z4KxXmBvjPXYz3yQ5f8XyA9")
    peerstore = PeerStore()

    key_pair = create_new_key_pair()
    identify_msg = Identify()
    identify_msg.public_key = key_pair.public_key.serialize()

    await _update_peerstore_from_identify(peerstore, peer_id, identify_msg)

    from libp2p.peer.peerstore import PeerStoreError
    with pytest.raises(PeerStoreError):
        peerstore.pubkey(peer_id)


@pytest.mark.trio
async def test_listen_addrs_truncated_at_1000():
    """Bug 9: listen_addrs should be truncated to 1000."""
    peer_id = ID.from_base58("QmQvGbd2FwM5WJMW226R7z8Z4KxXmBvjPXYz3yQ5f8XyA9")
    peerstore = PeerStore()

    identify_msg = Identify()
    # Create 1500 valid public addrs
    for i in range(1500):
        # 8.8.8.8 is public
        ma = Multiaddr(f"/ip4/8.8.8.8/tcp/{1000 + i}")
        identify_msg.listen_addrs.append(ma.to_bytes())

    await _update_peerstore_from_identify(peerstore, peer_id, identify_msg)

    stored_addrs = peerstore.addrs(peer_id)
    assert len(stored_addrs) == 1000
