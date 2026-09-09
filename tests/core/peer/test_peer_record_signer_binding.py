"""
Regression tests for libp2p/py-libp2p#1338.

A signed ``PeerRecord`` must only be accepted when the envelope's signer
identity matches the ``peer_id`` claimed inside the record.
"""

from __future__ import annotations

import pytest
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.envelope import Envelope, seal_record
from libp2p.peer.id import ID
from libp2p.peer.peer_record import PeerRecord
from libp2p.peer.peerstore import PeerStore
from libp2p.peer.persistent import (
    create_async_memory_peerstore,
    create_sync_memory_peerstore,
)

_ATTACKER_ADDR = Multiaddr("/ip4/10.0.0.1/tcp/4001")
_OWNER_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/4001")
_TTL = 7200


def _forged_envelope() -> tuple[ID, Envelope]:
    victim = create_new_key_pair()
    attacker = create_new_key_pair()
    victim_id = ID.from_pubkey(victim.public_key)
    record = PeerRecord(victim_id, [_ATTACKER_ADDR])
    forged = seal_record(record, attacker.private_key)
    return victim_id, forged


def _self_signed_envelope() -> tuple[ID, Envelope]:
    owner = create_new_key_pair()
    owner_id = ID.from_pubkey(owner.public_key)
    record = PeerRecord(owner_id, [_OWNER_ADDR])
    envelope = seal_record(record, owner.private_key)
    return owner_id, envelope


@pytest.mark.parametrize(
    "store_factory",
    [PeerStore, create_sync_memory_peerstore],
    ids=["in_memory", "sync_persistent"],
)
def test_rejects_forged_peer_record(store_factory) -> None:
    store = store_factory()
    victim_id, forged = _forged_envelope()

    assert store.consume_peer_record(forged, _TTL) is False
    assert store.get_peer_record(victim_id) is None


@pytest.mark.parametrize(
    "store_factory",
    [PeerStore, create_sync_memory_peerstore],
    ids=["in_memory", "sync_persistent"],
)
def test_accepts_self_signed_peer_record(store_factory) -> None:
    store = store_factory()
    owner_id, envelope = _self_signed_envelope()

    assert store.consume_peer_record(envelope, _TTL) is True
    assert set(store.addrs(owner_id)) == {_OWNER_ADDR}


@pytest.mark.trio
async def test_rejects_forged_peer_record_async() -> None:
    store = create_async_memory_peerstore()
    victim_id, forged = _forged_envelope()

    assert await store.consume_peer_record_async(forged, _TTL) is False
    assert await store.get_peer_record_async(victim_id) is None


@pytest.mark.trio
async def test_accepts_self_signed_peer_record_async() -> None:
    store = create_async_memory_peerstore()
    owner_id, envelope = _self_signed_envelope()

    assert await store.consume_peer_record_async(envelope, _TTL) is True
    assert set(await store.addrs_async(owner_id)) == {_OWNER_ADDR}
