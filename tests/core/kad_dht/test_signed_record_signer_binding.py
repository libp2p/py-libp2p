"""
Regression tests for libp2p/py-libp2p#1338.

A signed ``PeerRecord`` must only be accepted when the envelope's *signer*
identity matches the ``peer_id`` claimed inside the record.  Otherwise an
attacker can sign a record claiming a victim's peer id (with attacker-controlled
addresses) and poison the certified address book for that victim.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.kad_dht.pb.kademlia_pb2 import Message
from libp2p.kad_dht.utils import maybe_consume_signed_record
from libp2p.peer.envelope import seal_record
from libp2p.peer.id import ID
from libp2p.peer.peer_record import PeerRecord

_ATTACKER_ADDR = Multiaddr("/ip4/10.0.0.1/tcp/4001")


def _host_accepting_records() -> MagicMock:
    """A host whose peerstore would accept any record it is handed."""
    host = MagicMock()
    host.get_peerstore().consume_peer_record.return_value = True
    return host


def test_rejects_signed_record_with_mismatched_signer() -> None:
    """Message.Peer path: record claims the victim id but is attacker-signed."""
    victim = create_new_key_pair()
    attacker = create_new_key_pair()
    victim_id = ID.from_pubkey(victim.public_key)

    # Record claims the victim's id, but is signed by the attacker's key.
    record = PeerRecord(victim_id, [_ATTACKER_ADDR])
    forged = seal_record(record, attacker.private_key)

    peer = Message.Peer()
    peer.id = victim_id.to_bytes()
    peer.signedRecord = forged.marshal_envelope()

    # Claimed id == record id, signature is valid for the attacker key, so the
    # existing checks pass — the signer-identity binding must catch it.
    assert maybe_consume_signed_record(peer, _host_accepting_records()) is False


def test_rejects_sender_record_with_mismatched_signer() -> None:
    """Message.senderRecord path: same forgery, expected peer id supplied."""
    victim = create_new_key_pair()
    attacker = create_new_key_pair()
    victim_id = ID.from_pubkey(victim.public_key)

    record = PeerRecord(victim_id, [_ATTACKER_ADDR])
    forged = seal_record(record, attacker.private_key)

    msg = Message()
    msg.senderRecord = forged.marshal_envelope()

    # record.peer_id == peer_id (victim) passes the existing check; the binding
    # check must still reject it because the signer is the attacker.
    assert (
        maybe_consume_signed_record(msg, _host_accepting_records(), peer_id=victim_id)
        is False
    )


def test_accepts_self_signed_record() -> None:
    """A record signed by the same identity it claims must still be accepted."""
    owner = create_new_key_pair()
    owner_id = ID.from_pubkey(owner.public_key)

    record = PeerRecord(owner_id, [Multiaddr("/ip4/127.0.0.1/tcp/4001")])
    envelope = seal_record(record, owner.private_key)

    peer = Message.Peer()
    peer.id = owner_id.to_bytes()
    peer.signedRecord = envelope.marshal_envelope()

    assert maybe_consume_signed_record(peer, _host_accepting_records()) is True
