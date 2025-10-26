"""
Comprehensive tests for Ed25519 cryptographic operations.

This module tests the critical cryptographic operations in Ed25519,
including the security-critical fix for verify_key vs public_key.
"""

import pytest

from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
    create_new_key_pair,
)


class TestEd25519CryptographicOperations:
    """Test Ed25519 cryptographic operations and security fixes."""

    def test_signature_generation_and_verification(self):
        """Test signature generation and verification roundtrip."""
        # Create test key pair
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test data
        test_data = b"test_data_for_signing"

        # Generate signature
        signature = private_key.sign(test_data)
        assert isinstance(signature, bytes)
        assert len(signature) == 64  # Ed25519 signature length

        # Verify signature
        verification_result = public_key.verify(test_data, signature)
        assert verification_result is True

        # Test with wrong data
        wrong_data = b"wrong_data"
        verification_result = public_key.verify(wrong_data, signature)
        assert verification_result is False

        # Test with wrong signature (valid length but wrong content)
        wrong_signature = b"0" * 64  # 64 bytes of zeros
        verification_result = public_key.verify(test_data, wrong_signature)
        assert verification_result is False

    def test_public_key_derivation(self):
        """Test public key derivation from private key."""
        # Create test key pair
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key

        # Derive public key
        derived_public_key = private_key.get_public_key()

        # Verify it's the correct type
        assert isinstance(derived_public_key, Ed25519PublicKey)

        # Verify it matches the original public key
        assert derived_public_key == key_pair.public_key

        # Test cryptographic properties
        test_data = b"test_derivation"
        signature = private_key.sign(test_data)
        verification_result = derived_public_key.verify(test_data, signature)
        assert verification_result is True

    def test_critical_verify_key_fix(self):
        """Test the critical fix: verify_key vs public_key."""
        # This test verifies that the critical fix in PR 926 is working
        # The fix changed from self.impl.public_key to self.impl.verify_key

        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test data
        test_data = b"critical_fix_test"

        # Generate signature
        signature = private_key.sign(test_data)

        # Verify signature works (this would fail with the old public_key approach)
        verification_result = public_key.verify(test_data, signature)
        assert verification_result is True

        # Test that the public key can be serialized and deserialized
        public_key_bytes = public_key.to_bytes()
        assert isinstance(public_key_bytes, bytes)
        assert len(public_key_bytes) == 32  # Ed25519 public key length

        # Test deserialization
        deserialized_public_key = Ed25519PublicKey.from_bytes(public_key_bytes)
        assert isinstance(deserialized_public_key, Ed25519PublicKey)

        # Test that deserialized key works for verification
        verification_result = deserialized_public_key.verify(test_data, signature)
        assert verification_result is True

    def test_error_handling(self):
        """Test error handling for invalid inputs."""
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test empty data
        empty_data = b""
        signature = private_key.sign(empty_data)
        verification_result = public_key.verify(empty_data, signature)
        assert verification_result is True

        # Test large data
        large_data = b"x" * 10000
        signature = private_key.sign(large_data)
        verification_result = public_key.verify(large_data, signature)
        assert verification_result is True

        # Test invalid signature length (should raise exception)
        invalid_signature = b"short"
        with pytest.raises(Exception):  # Should raise ValueError or similar
            public_key.verify(b"test", invalid_signature)

        # Test malformed signature
        malformed_signature = b"0" * 64  # All zeros
        verification_result = public_key.verify(b"test", malformed_signature)
        assert verification_result is False

    def test_key_serialization_roundtrip(self):
        """Test key serialization preserves cryptographic properties."""
        # Create test key pair
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test data
        test_data = b"serialization_test"

        # Generate signature with original key
        signature = private_key.sign(test_data)

        # Serialize and deserialize private key
        private_key_bytes = private_key.to_bytes()
        deserialized_private_key = Ed25519PrivateKey.from_bytes(private_key_bytes)

        # Verify deserialized private key works
        assert isinstance(deserialized_private_key, Ed25519PrivateKey)
        new_signature = deserialized_private_key.sign(test_data)
        assert new_signature == signature  # Should be identical

        # Serialize and deserialize public key
        public_key_bytes = public_key.to_bytes()
        deserialized_public_key = Ed25519PublicKey.from_bytes(public_key_bytes)

        # Verify deserialized public key works
        assert isinstance(deserialized_public_key, Ed25519PublicKey)
        verification_result = deserialized_public_key.verify(test_data, signature)
        assert verification_result is True

    def test_key_generation_with_seed(self):
        """Test key generation with specific seed."""
        # Test with specific seed (32 bytes)
        seed = b"test_seed_32_bytes_long_12345678"
        assert len(seed) == 32

        private_key = Ed25519PrivateKey.new(seed)
        assert isinstance(private_key, Ed25519PrivateKey)

        # Test that same seed produces same key
        private_key2 = Ed25519PrivateKey.new(seed)
        assert private_key.to_bytes() == private_key2.to_bytes()

        # Test that different seed produces different key
        different_seed = b"different_seed_32_bytes_long_123"
        private_key3 = Ed25519PrivateKey.new(different_seed)
        assert private_key.to_bytes() != private_key3.to_bytes()

    def test_key_generation_without_seed(self):
        """Test key generation without seed (random)."""
        # Generate random key
        private_key = Ed25519PrivateKey.new()
        assert isinstance(private_key, Ed25519PrivateKey)

        # Generate another random key
        private_key2 = Ed25519PrivateKey.new()
        assert isinstance(private_key2, Ed25519PrivateKey)

        # They should be different (very high probability)
        assert private_key.to_bytes() != private_key2.to_bytes()

    def test_key_type_consistency(self):
        """Test that key types are consistent."""
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test key types
        assert private_key.get_type().name == "Ed25519"
        assert public_key.get_type().name == "Ed25519"

        # Test type equality
        assert private_key.get_type() == public_key.get_type()

    def test_multiple_signatures_different_data(self):
        """Test signing multiple different data with same key."""
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key
        public_key = key_pair.public_key

        # Test multiple different data
        test_data_sets = [
            b"data_1",
            b"data_2",
            b"",
            b"x" * 1000,
            b"special_chars_!@#$%^&*()",
        ]

        signatures = []
        for data in test_data_sets:
            signature = private_key.sign(data)
            signatures.append(signature)

            # Verify each signature
            verification_result = public_key.verify(data, signature)
            assert verification_result is True

        # Verify signatures are different
        for i in range(len(signatures)):
            for j in range(i + 1, len(signatures)):
                assert signatures[i] != signatures[j]

    def test_signature_determinism(self):
        """Test that signatures are deterministic for same inputs."""
        key_pair = create_new_key_pair()
        private_key = key_pair.private_key

        test_data = b"deterministic_test"

        # Generate multiple signatures for same data
        signature1 = private_key.sign(test_data)
        signature2 = private_key.sign(test_data)
        signature3 = private_key.sign(test_data)

        # All signatures should be identical
        assert signature1 == signature2
        assert signature2 == signature3
        assert signature1 == signature3

    def test_public_key_equality(self):
        """Test public key equality and hashing."""
        key_pair1 = create_new_key_pair()
        key_pair2 = create_new_key_pair()

        public_key1 = key_pair1.public_key
        public_key2 = key_pair2.public_key

        # Test equality
        assert public_key1 == public_key1  # Same object
        assert public_key1 != public_key2  # Different keys

        # Test that equal keys have same bytes
        public_key1_copy = Ed25519PublicKey.from_bytes(public_key1.to_bytes())
        assert public_key1 == public_key1_copy

        # Note: Ed25519PublicKey is not hashable, so we can't test set operations
        # This is expected behavior for cryptographic key objects
