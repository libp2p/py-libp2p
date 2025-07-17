"""Tests for peer record implementation."""

import pytest
import multiaddr

from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
)
from libp2p.peer.envelope import (
    Envelope,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.record import (
    PeerRecord,
)


@pytest.fixture
def private_key():
    """Create a test private key."""
    return Ed25519PrivateKey.new()


@pytest.fixture
def peer_id(private_key):
    """Create a test peer ID."""
    return ID.from_pubkey(private_key.get_public_key())


@pytest.fixture
def test_addrs():
    """Create test multiaddresses."""
    return [
        multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8000"),
        multiaddr.Multiaddr("/ip6/::1/tcp/8001"),
    ]


class TestEnvelope:
    """Test cases for the Envelope class."""

    def test_create_and_verify(self, private_key):
        """Test creating and verifying an envelope."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope = Envelope.create(payload_type, payload, private_key)

        assert envelope.payload_type == payload_type
        assert envelope.payload == payload
        assert envelope.verify() is True
        assert envelope.peer_id() == ID.from_pubkey(private_key.get_public_key())

    def test_serialize_deserialize(self, private_key):
        """Test envelope serialization and deserialization."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope = Envelope.create(payload_type, payload, private_key)

        # Serialize and deserialize
        serialized = envelope.serialize()
        deserialized = Envelope.deserialize(serialized)

        assert deserialized == envelope
        assert deserialized.verify() is True

    def test_invalid_signature_fails_verification(self, private_key):
        """Test that an envelope with invalid signature fails verification."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope = Envelope.create(payload_type, payload, private_key)

        # Tamper with the signature
        envelope.signature = b"invalid signature"

        assert envelope.verify() is False

    def test_tampered_payload_fails_verification(self, private_key):
        """Test that an envelope with tampered payload fails verification."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope = Envelope.create(payload_type, payload, private_key)

        # Tamper with the payload
        envelope.payload = b"tampered payload"

        assert envelope.verify() is False

    def test_envelope_equality(self, private_key):
        """Test envelope equality comparison."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope1 = Envelope.create(payload_type, payload, private_key)
        envelope2 = Envelope.create(payload_type, payload, private_key)

        # Should not be equal due to different signatures (randomness)
        assert envelope1 != envelope2

    def test_envelope_repr(self, private_key):
        """Test envelope string representation."""
        payload_type = b"\x03\x01"  # libp2p-peer-record codec
        payload = b"test payload data"
        envelope = Envelope.create(payload_type, payload, private_key)

        repr_str = repr(envelope)
        assert "Envelope" in repr_str
        assert str(envelope.peer_id()) in repr_str


class TestPeerRecord:
    """Test cases for the PeerRecord class."""

    def test_create_peer_record(self, peer_id, test_addrs):
        """Test creating a peer record."""
        record = PeerRecord(peer_id, test_addrs)

        assert record.peer_id == peer_id
        assert record.addrs == test_addrs
        assert isinstance(record.seq, int)
        assert record.seq > 0

    def test_serialize_deserialize(self, peer_id, test_addrs):
        """Test peer record serialization and deserialization."""
        record = PeerRecord(peer_id, test_addrs, seq=12345)

        # Serialize and deserialize
        serialized = record.serialize()
        deserialized = PeerRecord.deserialize(serialized)

        assert deserialized == record
        assert deserialized.peer_id == peer_id
        assert deserialized.addrs == test_addrs
        assert deserialized.seq == 12345

    def test_sign_and_verify(self, private_key, peer_id, test_addrs):
        """Test signing a peer record and verifying the envelope."""
        record = PeerRecord(peer_id, test_addrs)

        # Sign the record
        envelope = record.sign(private_key)

        assert envelope.verify() is True
        assert envelope.peer_id() == peer_id

    def test_sign_with_wrong_key_fails(self, private_key, test_addrs):
        """Test signing with a key that doesn't match the peer ID fails."""
        wrong_key = Ed25519PrivateKey.new()
        wrong_peer_id = ID.from_pubkey(wrong_key.get_public_key())
        record = PeerRecord(wrong_peer_id, test_addrs)

        with pytest.raises(ValueError, match="does not match record peer ID"):
            record.sign(private_key)

    def test_from_envelope(self, private_key, peer_id, test_addrs):
        """Test extracting a peer record from an envelope."""
        original_record = PeerRecord(peer_id, test_addrs, seq=54321)
        envelope = original_record.sign(private_key)

        # Extract record from envelope
        extracted_record = PeerRecord.from_envelope(envelope)

        assert extracted_record == original_record

    def test_from_envelope_with_invalid_signature_fails(
        self, private_key, peer_id, test_addrs
    ):
        """Test extracting from envelope with invalid signature fails."""
        record = PeerRecord(peer_id, test_addrs)
        envelope = record.sign(private_key)

        # Tamper with the signature
        envelope.signature = b"invalid signature"

        with pytest.raises(ValueError, match="signature verification failed"):
            PeerRecord.from_envelope(envelope)

    def test_from_envelope_with_wrong_payload_type_fails(self, private_key):
        """Test extracting from envelope with wrong payload type fails."""
        wrong_payload_type = b"\x00\x50"  # wrong codec
        payload = b"some data"
        envelope = Envelope.create(wrong_payload_type, payload, private_key)

        with pytest.raises(ValueError, match="does not contain a peer record"):
            PeerRecord.from_envelope(envelope)

    def test_from_envelope_with_mismatched_peer_id_fails(self, private_key, test_addrs):
        """Test extracting from envelope with mismatched peer ID fails."""
        # Create record with one peer ID
        wrong_key = Ed25519PrivateKey.new()
        wrong_peer_id = ID.from_pubkey(wrong_key.get_public_key())
        record = PeerRecord(wrong_peer_id, test_addrs)

        # But sign with different key
        from libp2p.peer.record import LIBP2P_PEER_RECORD_CODEC

        record_data = record.serialize()
        envelope = Envelope.create(LIBP2P_PEER_RECORD_CODEC, record_data, private_key)

        with pytest.raises(ValueError, match="does not match envelope signer ID"):
            PeerRecord.from_envelope(envelope)

    def test_is_newer_than(self, peer_id, test_addrs):
        """Test comparing record freshness."""
        record1 = PeerRecord(peer_id, test_addrs, seq=100)
        record2 = PeerRecord(peer_id, test_addrs, seq=200)

        assert record2.is_newer_than(record1) is True
        assert record1.is_newer_than(record2) is False
        assert record1.is_newer_than(record1) is False

    def test_peer_record_equality(self, peer_id, test_addrs):
        """Test peer record equality comparison."""
        record1 = PeerRecord(peer_id, test_addrs, seq=123)
        record2 = PeerRecord(peer_id, test_addrs, seq=123)
        record3 = PeerRecord(peer_id, test_addrs, seq=456)

        assert record1 == record2
        assert record1 != record3

    def test_peer_record_repr(self, peer_id, test_addrs):
        """Test peer record string representation."""
        record = PeerRecord(peer_id, test_addrs, seq=123)

        repr_str = repr(record)
        assert "PeerRecord" in repr_str
        assert str(peer_id) in repr_str
        assert "123" in repr_str


class TestIntegration:
    """Integration tests for peer records and envelopes."""

    def test_full_workflow(self, private_key, peer_id, test_addrs):
        """
        Test the complete workflow of creating, signing, and verifying a peer record.
        """
        # Create a peer record
        record = PeerRecord(peer_id, test_addrs)

        # Sign it to create an envelope
        envelope = record.sign(private_key)

        # Serialize the envelope
        envelope_data = envelope.serialize()

        # Deserialize the envelope
        deserialized_envelope = Envelope.deserialize(envelope_data)

        # Verify the envelope
        assert deserialized_envelope.verify() is True

        # Extract the peer record
        extracted_record = PeerRecord.from_envelope(deserialized_envelope)

        # Verify the extracted record matches the original
        assert extracted_record.peer_id == record.peer_id
        assert extracted_record.addrs == record.addrs
        assert extracted_record.seq == record.seq

    def test_multiple_keys_different_signatures(self, test_addrs):
        """Test that different keys produce different signatures for the same record."""
        key1 = Ed25519PrivateKey.new()
        key2 = Ed25519PrivateKey.new()

        peer_id1 = ID.from_pubkey(key1.get_public_key())
        peer_id2 = ID.from_pubkey(key2.get_public_key())

        # Create records with same addresses but different peer IDs
        record1 = PeerRecord(peer_id1, test_addrs, seq=123)
        record2 = PeerRecord(peer_id2, test_addrs, seq=123)

        envelope1 = record1.sign(key1)
        envelope2 = record2.sign(key2)

        # Should have different signatures and public keys
        assert envelope1.signature != envelope2.signature
        assert envelope1.public_key.serialize() != envelope2.public_key.serialize()

        # But both should verify correctly
        assert envelope1.verify() is True
        assert envelope2.verify() is True
