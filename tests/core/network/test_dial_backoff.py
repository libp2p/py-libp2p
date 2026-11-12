import pytest
from multiaddr import Multiaddr

from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.backoff import DialBackoff
from libp2p.network.exceptions import SwarmDialBackoffError, SwarmException
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader


def test_dial_backoff_quadratic_progression():
    db = DialBackoff(base=5.0, coef=1.0, max_backoff=60.0)
    peer_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    addr = Multiaddr("/ip4/198.51.100.1/tcp/4001")

    assert not db.is_backed_off(peer_id, addr)
    assert db.backoff_delay(peer_id, addr) == 0.0
    assert db.tries(peer_id, addr) == 0

    # First failure: base + coef * 1^2 = 5 + 1 = 6s
    db.add_backoff(peer_id, addr)
    assert db.is_backed_off(peer_id, addr)
    assert db.tries(peer_id, addr) == 1
    delay1 = db.backoff_delay(peer_id, addr)
    assert 5.5 <= delay1 <= 6.5

    # Second failure: base + coef * 2^2 = 5 + 4 = 9s
    db.add_backoff(peer_id, addr)
    assert db.is_backed_off(peer_id, addr)
    assert db.tries(peer_id, addr) == 2
    delay2 = db.backoff_delay(peer_id, addr)
    assert 8.5 <= delay2 <= 9.5

    # Third failure: base + coef * 3^2 = 5 + 9 = 14s
    db.add_backoff(peer_id, addr)
    assert db.is_backed_off(peer_id, addr)
    assert db.tries(peer_id, addr) == 3
    delay3 = db.backoff_delay(peer_id, addr)
    assert 13.5 <= delay3 <= 14.5


def test_dial_backoff_clear_on_peer_success():
    db = DialBackoff()
    peer_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    addr1 = Multiaddr("/ip4/198.51.100.1/tcp/4001")
    addr2 = Multiaddr("/ip4/198.51.100.2/tcp/4001")

    db.add_backoff(peer_id, addr1)
    db.add_backoff(peer_id, addr2)
    assert db.is_backed_off(peer_id, addr1)
    assert db.is_backed_off(peer_id, addr2)

    # When dial to peer succeeds, clear removes all address backoffs for that peer
    db.clear(peer_id)
    assert not db.is_backed_off(peer_id, addr1)
    assert not db.is_backed_off(peer_id, addr2)


def test_dial_backoff_cap_at_max():
    db = DialBackoff(base=5.0, coef=1.0, max_backoff=20.0)
    peer_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    addr = Multiaddr("/ip4/198.51.100.1/tcp/4001")

    for _ in range(10):
        db.add_backoff(peer_id, addr)

    assert db.is_backed_off(peer_id, addr)
    assert db.tries(peer_id, addr) == 10
    # Should be capped at max_backoff = 20.0
    assert db.backoff_delay(peer_id, addr) <= 20.1


@pytest.mark.trio
async def test_swarm_dial_backoff_skips_backed_off_peer():
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peerstore = PeerStore()
    tcp = TCP()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol("/plaintext"): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={},
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transports=[tcp])

    target_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    target_addr = Multiaddr("/ip4/198.51.100.1/tcp/4001")
    peerstore.add_addrs(target_id, [target_addr], 3600)

    # Manually add target_addr to backoff
    swarm.dial_backoff.add_backoff(target_id, target_addr)

    # Dialing should immediately fail with SwarmDialBackoffError without dialing
    with pytest.raises(SwarmDialBackoffError):
        await swarm.dial_peer(target_id)


@pytest.mark.trio
async def test_swarm_dials_multiple_addresses_of_same_transport():
    """Verify Happy Eyeballs does not discard multiple addresses of same transport."""
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peerstore = PeerStore()
    tcp = TCP()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol("/plaintext"): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={},
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transports=[tcp])

    target_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    addr1 = Multiaddr("/ip4/127.0.0.1/tcp/59998")
    addr2 = Multiaddr("/ip4/127.0.0.1/tcp/59999")
    peerstore.add_addrs(target_id, [addr1, addr2], 3600)

    dialed_addrs = []
    orig_dial_with_retry = swarm._dial_with_retry

    async def mock_dial_with_retry(addr, pid, source=None):
        dialed_addrs.append(addr)
        return await orig_dial_with_retry(addr, pid, source)

    swarm._dial_with_retry = mock_dial_with_retry  # type: ignore[method-assign]

    with pytest.raises(SwarmException):
        await swarm.dial_peer(target_id)

    # Both addresses of the same transport class should be dialed via fallback
    assert addr1 in dialed_addrs
    assert addr2 in dialed_addrs


@pytest.mark.trio
async def test_swarm_prefers_non_loopback_private_addrs():
    """Verify swarm filters loopback addrs when non-loopback private addrs exist."""
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peerstore = PeerStore()
    tcp = TCP()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol("/plaintext"): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={},
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transports=[tcp])

    target_id = ID.from_base58("12D3KooWFXc3Tht1FgrFVNg7SigUJvWrk15ELYtXvs3hLrDFdtEA")
    loopback_addr = Multiaddr("/ip4/127.0.0.1/tcp/59998")
    private_addr = Multiaddr("/ip4/192.168.1.100/tcp/59999")
    peerstore.add_addrs(target_id, [loopback_addr, private_addr], 3600)

    dialed_addrs = []
    orig_dial_with_retry = swarm._dial_with_retry

    async def mock_dial_with_retry(addr, pid, source=None):
        dialed_addrs.append(addr)
        return await orig_dial_with_retry(addr, pid, source)

    swarm._dial_with_retry = mock_dial_with_retry  # type: ignore[method-assign]

    with pytest.raises(SwarmException):
        await swarm.dial_peer(target_id)

    # Loopback address should have been filtered out in favor of the LAN private address
    assert private_addr in dialed_addrs
    assert loopback_addr not in dialed_addrs
