"""
Comprehensive tests for messages module core functions.

This module tests the core functions in the messages module,
including signature generation, verification, and data preparation.
"""

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.security.noise.messages import (
    NoiseExtensions,
    NoiseHandshakePayload,
    make_data_to_be_signed,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)


class TestMessagesCoreFunctions:
    """Test core functions in messages module."""

    def test_make_data_to_be_signed(self):
        """Test data preparation for signing."""
        # Create test key pair
        key_pair = create_new_key_pair()
        public_key = key_pair.public_key

        # Test data preparation
        data = make_data_to_be_signed(public_key)

        # Verify format
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Verify prefix
        prefix = b"noise-libp2p-static-key:"
        assert data.startswith(prefix)

        # Verify public key is included
        public_key_bytes = public_key.to_bytes()
        assert public_key_bytes in data

        # Test deterministic output
        data2 = make_data_to_be_signed(public_key)
        assert data == data2

        # Test different keys produce different data
        key_pair2 = create_new_key_pair()
        public_key2 = key_pair2.public_key
        data3 = make_data_to_be_signed(public_key2)
        assert data != data3

    def test_make_handshake_payload_sig(self):
        """Test handshake payload signature generation."""
        # Create test key pairs
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()

        libp2p_privkey = libp2p_keypair.private_key
        noise_static_pubkey = noise_keypair.public_key

        # Generate signature
        signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)

        # Verify signature format
        assert isinstance(signature, bytes)
        assert len(signature) == 64  # Ed25519 signature length

        # Test deterministic output
        signature2 = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
        assert signature == signature2

        # Test different keys produce different signatures
        libp2p_keypair2 = create_new_key_pair()
        libp2p_privkey2 = libp2p_keypair2.private_key
        signature3 = make_handshake_payload_sig(libp2p_privkey2, noise_static_pubkey)
        assert signature != signature3

    def test_verify_handshake_payload_sig(self):
        """Test handshake payload signature verification."""
        # Create test key pairs
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()

        libp2p_privkey = libp2p_keypair.private_key
        libp2p_pubkey = libp2p_keypair.public_key
        noise_static_pubkey = noise_keypair.public_key

        # Create handshake payload
        payload = NoiseHandshakePayload(
            id_pubkey=libp2p_pubkey,
            id_sig=b"",  # Will be set after signature generation
        )

        # Generate signature
        signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
        payload.id_sig = signature

        # Verify signature
        verification_result = verify_handshake_payload_sig(payload, noise_static_pubkey)
        assert verification_result is True

        # Test with wrong noise static public key
        wrong_noise_keypair = create_new_key_pair()
        wrong_noise_static_pubkey = wrong_noise_keypair.public_key
        verification_result = verify_handshake_payload_sig(
            payload, wrong_noise_static_pubkey
        )
        assert verification_result is False

        # Test with tampered signature
        tampered_payload = NoiseHandshakePayload(
            id_pubkey=libp2p_pubkey,
            id_sig=b"tampered_signature" + b"0" * 48,  # 64 bytes
        )
        verification_result = verify_handshake_payload_sig(
            tampered_payload, noise_static_pubkey
        )
        assert verification_result is False

        # Test with wrong identity public key
        wrong_libp2p_keypair = create_new_key_pair()
        wrong_payload = NoiseHandshakePayload(
            id_pubkey=wrong_libp2p_keypair.public_key,
            id_sig=signature,  # Signature from different key
        )
        verification_result = verify_handshake_payload_sig(
            wrong_payload, noise_static_pubkey
        )
        assert verification_result is False

    def test_signature_roundtrip(self):
        """Test complete signature generation and verification."""
        # Create test key pairs
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()

        libp2p_privkey = libp2p_keypair.private_key
        libp2p_pubkey = libp2p_keypair.public_key
        noise_static_pubkey = noise_keypair.public_key

        # Generate signature
        signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)

        # Create payload with signature
        payload = NoiseHandshakePayload(
            id_pubkey=libp2p_pubkey,
            id_sig=signature,
        )

        # Verify signature
        verification_result = verify_handshake_payload_sig(payload, noise_static_pubkey)
        assert verification_result is True

        # Test serialization roundtrip
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Verify deserialized payload
        verification_result = verify_handshake_payload_sig(
            deserialized, noise_static_pubkey
        )
        assert verification_result is True

    def test_noise_extensions_edge_cases(self):
        """Test NoiseExtensions edge cases."""
        # Test empty extensions
        empty_extensions = NoiseExtensions()
        assert empty_extensions.is_empty() is True
        assert empty_extensions.has_webtransport_certhashes() is False
        assert empty_extensions.has_stream_muxers() is False
        assert empty_extensions.has_early_data() is False

        # Test extensions with only early data
        early_data_extensions = NoiseExtensions(early_data=b"test_early_data")
        assert early_data_extensions.is_empty() is False
        assert early_data_extensions.has_early_data() is True
        assert early_data_extensions.early_data == b"test_early_data"

        # Test extensions with only stream muxers
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]
        muxer_extensions = NoiseExtensions(stream_muxers=stream_muxers)
        assert muxer_extensions.is_empty() is False
        assert muxer_extensions.has_stream_muxers() is True
        assert muxer_extensions.stream_muxers == stream_muxers

        # Test extensions with only WebTransport certs
        cert_hashes = [b"cert_hash_1", b"cert_hash_2"]
        cert_extensions = NoiseExtensions(webtransport_certhashes=cert_hashes)
        assert cert_extensions.is_empty() is False
        assert cert_extensions.has_webtransport_certhashes() is True
        assert cert_extensions.webtransport_certhashes == cert_hashes

        # Test combined extensions
        combined_extensions = NoiseExtensions(
            webtransport_certhashes=cert_hashes,
            stream_muxers=stream_muxers,
            early_data=b"combined_early_data",
        )
        assert combined_extensions.is_empty() is False
        assert combined_extensions.has_webtransport_certhashes() is True
        assert combined_extensions.has_stream_muxers() is True
        assert combined_extensions.has_early_data() is True

    def test_noise_extensions_protobuf_roundtrip(self):
        """Test NoiseExtensions protobuf serialization roundtrip."""
        # Test empty extensions
        empty_extensions = NoiseExtensions()
        protobuf = empty_extensions.to_protobuf()
        deserialized = NoiseExtensions.from_protobuf(protobuf)
        assert deserialized.is_empty() is True

        # Test extensions with all fields
        original_extensions = NoiseExtensions(
            webtransport_certhashes=[b"cert1", b"cert2"],
            stream_muxers=["/mplex/1.0.0", "/yamux/1.0.0"],
            early_data=b"test_early_data",
        )

        protobuf = original_extensions.to_protobuf()
        deserialized = NoiseExtensions.from_protobuf(protobuf)

        assert (
            deserialized.webtransport_certhashes
            == original_extensions.webtransport_certhashes
        )
        assert deserialized.stream_muxers == original_extensions.stream_muxers
        assert deserialized.early_data == original_extensions.early_data

    def test_handshake_payload_with_extensions(self):
        """Test handshake payload with extensions."""
        # Create test key pairs
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()

        libp2p_privkey = libp2p_keypair.private_key
        libp2p_pubkey = libp2p_keypair.public_key
        noise_static_pubkey = noise_keypair.public_key

        # Create extensions
        extensions = NoiseExtensions(
            webtransport_certhashes=[b"cert_hash"],
            stream_muxers=["/mplex/1.0.0"],
            early_data=b"test_early_data",
        )

        # Generate signature
        signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)

        # Create payload with extensions
        payload = NoiseHandshakePayload(
            id_pubkey=libp2p_pubkey,
            id_sig=signature,
            extensions=extensions,
        )

        # Test payload properties
        assert payload.has_extensions() is True
        assert payload.has_early_data() is True
        assert payload.get_early_data() == b"test_early_data"

        # Test serialization roundtrip
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Verify deserialized payload
        assert deserialized.has_extensions() is True
        assert deserialized.has_early_data() is True
        assert deserialized.get_early_data() == b"test_early_data"

        # Verify signature still works
        verification_result = verify_handshake_payload_sig(
            deserialized, noise_static_pubkey
        )
        assert verification_result is True

    def test_handshake_payload_without_extensions(self):
        """Test handshake payload without extensions."""
        # Create test key pairs
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()

        libp2p_privkey = libp2p_keypair.private_key
        libp2p_pubkey = libp2p_keypair.public_key
        noise_static_pubkey = noise_keypair.public_key

        # Generate signature
        signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)

        # Create payload without extensions
        payload = NoiseHandshakePayload(
            id_pubkey=libp2p_pubkey,
            id_sig=signature,
            extensions=None,
        )

        # Test payload properties
        assert payload.has_extensions() is False
        assert payload.has_early_data() is False
        assert payload.get_early_data() is None

        # Test serialization roundtrip
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Verify deserialized payload
        assert deserialized.has_extensions() is False
        assert deserialized.has_early_data() is False
        assert deserialized.get_early_data() is None

        # Verify signature still works
        verification_result = verify_handshake_payload_sig(
            deserialized, noise_static_pubkey
        )
        assert verification_result is True

    def test_handshake_payload_validation(self):
        """Test handshake payload validation."""
        # Test empty protobuf data
        with pytest.raises(ValueError, match="Empty protobuf data"):
            NoiseHandshakePayload.deserialize(b"")

        # Test invalid protobuf data
        with pytest.raises(ValueError, match="Failed to deserialize protobuf"):
            NoiseHandshakePayload.deserialize(b"invalid_protobuf_data")

    def test_multiple_signatures_different_keys(self):
        """Test signature generation with multiple different key pairs."""
        # Create multiple key pairs
        key_pairs = [create_new_key_pair() for _ in range(5)]
        noise_keypair = create_new_key_pair()
        noise_static_pubkey = noise_keypair.public_key

        signatures = []
        for libp2p_keypair in key_pairs:
            libp2p_privkey = libp2p_keypair.private_key
            libp2p_pubkey = libp2p_keypair.public_key

            # Generate signature
            signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
            signatures.append(signature)

            # Create payload
            payload = NoiseHandshakePayload(
                id_pubkey=libp2p_pubkey,
                id_sig=signature,
            )

            # Verify signature
            verification_result = verify_handshake_payload_sig(
                payload, noise_static_pubkey
            )
            assert verification_result is True

        # Verify all signatures are different
        for i in range(len(signatures)):
            for j in range(i + 1, len(signatures)):
                assert signatures[i] != signatures[j]
