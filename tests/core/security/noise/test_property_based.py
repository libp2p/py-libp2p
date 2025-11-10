"""
Property-based tests for Noise modules.

This module tests Noise modules with random inputs to ensure
cryptographic properties and invariants are maintained.
"""

import random
import string

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.security.noise.messages import (
    NoiseExtensions,
    NoiseHandshakePayload,
    make_data_to_be_signed,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)


class TestNoisePropertyBased:
    """Property-based tests for Noise modules."""

    def generate_random_bytes(
        self, min_length: int = 1, max_length: int = 1000
    ) -> bytes:
        """Generate random bytes for testing."""
        length = random.randint(min_length, max_length)
        return bytes(random.randint(0, 255) for _ in range(length))

    def generate_random_string(self, min_length: int = 1, max_length: int = 100) -> str:
        """Generate random string for testing."""
        length = random.randint(min_length, max_length)
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))

    def test_ed25519_properties(self):
        """Test Ed25519 cryptographic properties with random data."""
        # Test multiple random key pairs
        for _ in range(10):
            key_pair = create_new_key_pair()
            private_key = key_pair.private_key
            public_key = key_pair.public_key

            # Test with random data
            random_data = self.generate_random_bytes(0, 1000)

            # Property: Signature generation should always succeed
            signature = private_key.sign(random_data)
            assert isinstance(signature, bytes)
            assert len(signature) == 64  # Ed25519 signature length

            # Property: Signature verification should succeed for correct data
            verification_result = public_key.verify(random_data, signature)
            assert verification_result is True

            # Property: Signature verification should fail for wrong data
            wrong_data = self.generate_random_bytes(0, 1000)
            if wrong_data != random_data:  # Avoid collision
                verification_result = public_key.verify(wrong_data, signature)
                assert verification_result is False

            # Property: Signature verification should fail for wrong signature
            wrong_signature = self.generate_random_bytes(64, 64)
            verification_result = public_key.verify(random_data, wrong_signature)
            assert verification_result is False

    def test_ed25519_key_derivation_properties(self):
        """Test Ed25519 key derivation properties."""
        # Test multiple random key pairs
        for _ in range(10):
            key_pair = create_new_key_pair()
            private_key = key_pair.private_key
            public_key = key_pair.public_key

            # Property: Public key derivation should be deterministic
            derived_public_key1 = private_key.get_public_key()
            derived_public_key2 = private_key.get_public_key()
            assert derived_public_key1 == derived_public_key2

            # Property: Derived public key should match original
            assert derived_public_key1 == public_key

            # Property: Derived public key should work for verification
            random_data = self.generate_random_bytes(0, 1000)
            signature = private_key.sign(random_data)
            verification_result = derived_public_key1.verify(random_data, signature)
            assert verification_result is True

    def test_ed25519_serialization_properties(self):
        """Test Ed25519 serialization properties."""
        # Test multiple random key pairs
        for _ in range(10):
            key_pair = create_new_key_pair()
            private_key = key_pair.private_key
            public_key = key_pair.public_key

            # Property: Serialization should be deterministic
            private_bytes1 = private_key.to_bytes()
            private_bytes2 = private_key.to_bytes()
            assert private_bytes1 == private_bytes2

            public_bytes1 = public_key.to_bytes()
            public_bytes2 = public_key.to_bytes()
            assert public_bytes1 == public_bytes2

            # Property: Deserialization should restore original key
            from libp2p.crypto.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

            deserialized_private = Ed25519PrivateKey.from_bytes(private_bytes1)
            deserialized_public = Ed25519PublicKey.from_bytes(public_bytes1)

            assert deserialized_private == private_key
            assert deserialized_public == public_key

            # Property: Deserialized keys should work for cryptographic operations
            random_data = self.generate_random_bytes(0, 1000)
            signature = deserialized_private.sign(random_data)
            verification_result = deserialized_public.verify(random_data, signature)
            assert verification_result is True

    def test_handshake_payload_properties(self):
        """Test handshake payload properties with random data."""
        # Test multiple random key pairs
        for _ in range(10):
            libp2p_keypair = create_new_key_pair()
            noise_keypair = create_new_key_pair()

            libp2p_privkey = libp2p_keypair.private_key
            libp2p_pubkey = libp2p_keypair.public_key
            noise_static_pubkey = noise_keypair.public_key

            # Property: Data preparation should be deterministic
            data1 = make_data_to_be_signed(noise_static_pubkey)
            data2 = make_data_to_be_signed(noise_static_pubkey)
            assert data1 == data2

            # Property: Data should contain prefix and public key
            prefix = b"noise-libp2p-static-key:"
            assert data1.startswith(prefix)
            assert noise_static_pubkey.to_bytes() in data1

            # Property: Signature generation should be deterministic
            signature1 = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
            signature2 = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
            assert signature1 == signature2

            # Property: Signature verification should succeed for correct payload
            payload = NoiseHandshakePayload(
                id_pubkey=libp2p_pubkey,
                id_sig=signature1,
            )
            verification_result = verify_handshake_payload_sig(
                payload, noise_static_pubkey
            )
            assert verification_result is True

            # Property: Signature verification should fail for wrong noise key
            wrong_noise_keypair = create_new_key_pair()
            verification_result = verify_handshake_payload_sig(
                payload, wrong_noise_keypair.public_key
            )
            assert verification_result is False

    def test_noise_extensions_properties(self):
        """Test NoiseExtensions properties with random data."""
        # Test multiple random extensions
        for _ in range(10):
            # Generate random extension data
            num_certs = random.randint(0, 5)
            webtransport_certhashes = [
                self.generate_random_bytes(32, 32) for _ in range(num_certs)
            ]

            num_muxers = random.randint(0, 5)
            stream_muxers = [
                f"/{self.generate_random_string(3, 10)}/{random.randint(1, 3)}.0.0"
                for _ in range(num_muxers)
            ]

            early_data = (
                self.generate_random_bytes(0, 100)
                if random.choice([True, False])
                else None
            )

            # Create extensions
            extensions = NoiseExtensions(
                webtransport_certhashes=webtransport_certhashes,
                stream_muxers=stream_muxers,
                early_data=early_data,
            )

            # Property: Extensions should preserve data
            assert extensions.webtransport_certhashes == webtransport_certhashes
            assert extensions.stream_muxers == stream_muxers
            assert extensions.early_data == early_data

            # Property: Empty check should work correctly
            is_empty = (
                not webtransport_certhashes and not stream_muxers and early_data is None
            )
            assert extensions.is_empty() == is_empty

            # Property: Individual checks should work correctly
            assert extensions.has_webtransport_certhashes() == bool(
                webtransport_certhashes
            )
            assert extensions.has_stream_muxers() == bool(stream_muxers)
            assert extensions.has_early_data() == (early_data is not None)

            # Property: Protobuf roundtrip should preserve data
            protobuf = extensions.to_protobuf()
            deserialized = NoiseExtensions.from_protobuf(protobuf)

            assert deserialized.webtransport_certhashes == webtransport_certhashes
            assert deserialized.stream_muxers == stream_muxers
            assert deserialized.early_data == early_data

    def test_handshake_payload_serialization_properties(self):
        """Test handshake payload serialization properties."""
        # Test multiple random payloads
        for _ in range(10):
            libp2p_keypair = create_new_key_pair()
            noise_keypair = create_new_key_pair()

            libp2p_privkey = libp2p_keypair.private_key
            libp2p_pubkey = libp2p_keypair.public_key
            noise_static_pubkey = noise_keypair.public_key

            # Generate random extensions
            extensions = None
            if random.choice([True, False]):
                extensions = NoiseExtensions(
                    webtransport_certhashes=[self.generate_random_bytes(32, 32)],
                    stream_muxers=[f"/{self.generate_random_string(3, 10)}/1.0.0"],
                    early_data=self.generate_random_bytes(0, 100),
                )

            # Create payload
            signature = make_handshake_payload_sig(libp2p_privkey, noise_static_pubkey)
            payload = NoiseHandshakePayload(
                id_pubkey=libp2p_pubkey,
                id_sig=signature,
                extensions=extensions,
            )

            # Property: Serialization should be deterministic
            serialized1 = payload.serialize()
            serialized2 = payload.serialize()
            assert serialized1 == serialized2

            # Property: Deserialization should restore original payload
            deserialized = NoiseHandshakePayload.deserialize(serialized1)

            assert deserialized.id_pubkey == payload.id_pubkey
            assert deserialized.id_sig == payload.id_sig

            if payload.extensions is None:
                assert deserialized.extensions is None
            else:
                assert deserialized.extensions is not None
                assert (
                    deserialized.extensions.webtransport_certhashes
                    == payload.extensions.webtransport_certhashes
                )
                assert (
                    deserialized.extensions.stream_muxers
                    == payload.extensions.stream_muxers
                )
                assert (
                    deserialized.extensions.early_data == payload.extensions.early_data
                )

            # Property: Deserialized payload should verify correctly
            verification_result = verify_handshake_payload_sig(
                deserialized, noise_static_pubkey
            )
            assert verification_result is True

    def test_cryptographic_invariants(self):
        """Test cryptographic invariants with random inputs."""
        # Test multiple random scenarios
        for _ in range(20):
            # Generate random key pairs
            libp2p_keypair = create_new_key_pair()
            noise_keypair = create_new_key_pair()

            # Generate random data
            random_data = self.generate_random_bytes(0, 1000)

            # Invariant: Same private key should always produce same signature
            # for same data
            signature1 = libp2p_keypair.private_key.sign(random_data)
            signature2 = libp2p_keypair.private_key.sign(random_data)
            assert signature1 == signature2

            # Invariant: Different private keys should produce different signatures
            # for same data
            different_keypair = create_new_key_pair()
            different_signature = different_keypair.private_key.sign(random_data)
            assert signature1 != different_signature

            # Invariant: Public key should always verify its own private key's
            # signatures
            verification_result = libp2p_keypair.public_key.verify(
                random_data, signature1
            )
            assert verification_result is True

            # Invariant: Public key should not verify different private key's signatures
            verification_result = libp2p_keypair.public_key.verify(
                random_data, different_signature
            )
            assert verification_result is False

            # Invariant: Handshake signature should be deterministic for same inputs
            noise_static_pubkey = noise_keypair.public_key
            handshake_sig1 = make_handshake_payload_sig(
                libp2p_keypair.private_key, noise_static_pubkey
            )
            handshake_sig2 = make_handshake_payload_sig(
                libp2p_keypair.private_key, noise_static_pubkey
            )
            assert handshake_sig1 == handshake_sig2

            # Invariant: Handshake signature should be different for different inputs
            different_noise_keypair = create_new_key_pair()
            different_handshake_sig = make_handshake_payload_sig(
                libp2p_keypair.private_key, different_noise_keypair.public_key
            )
            assert handshake_sig1 != different_handshake_sig

    def test_edge_cases(self):
        """Test edge cases with boundary values."""
        # Test with empty data
        key_pair = create_new_key_pair()
        empty_data = b""

        signature = key_pair.private_key.sign(empty_data)
        verification_result = key_pair.public_key.verify(empty_data, signature)
        assert verification_result is True

        # Test with maximum length data
        max_data = b"x" * 10000
        signature = key_pair.private_key.sign(max_data)
        verification_result = key_pair.public_key.verify(max_data, signature)
        assert verification_result is True

        # Test with single byte data
        single_byte = b"x"
        signature = key_pair.private_key.sign(single_byte)
        verification_result = key_pair.public_key.verify(single_byte, signature)
        assert verification_result is True

        # Test with special characters
        special_data = b"!@#$%^&*()_+-=[]{}|;':\",./<>?"
        signature = key_pair.private_key.sign(special_data)
        verification_result = key_pair.public_key.verify(special_data, signature)
        assert verification_result is True
