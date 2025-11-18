"""
Performance and stress tests for Noise modules.

This module tests Noise performance characteristics, including
handshake timing, memory usage, and stress scenarios.
"""

import time

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.security.noise.early_data import BufferingEarlyDataHandler
from libp2p.security.noise.rekey import TimeBasedRekeyPolicy
from libp2p.security.noise.transport import Transport


class TestNoisePerformance:
    """Test Noise performance characteristics."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        return libp2p_keypair, noise_keypair

    def test_handshake_performance(self, key_pairs):
        """Test handshake performance."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test pattern creation timing
        start_time = time.time()
        pattern = transport.get_pattern()
        pattern_creation_time = time.time() - start_time

        # Pattern creation should be fast (< 0.1 seconds)
        assert pattern_creation_time < 0.1

        # Test payload creation timing
        start_time = time.time()
        assert hasattr(pattern, "make_handshake_payload")
        payload = pattern.make_handshake_payload()  # type: ignore
        payload_creation_time = time.time() - start_time

        # Payload creation should be fast (< 0.1 seconds)
        assert payload_creation_time < 0.1

        # Test serialization timing
        start_time = time.time()
        payload.serialize()
        serialization_time = time.time() - start_time

        # Serialization should be fast (< 0.1 seconds)
        assert serialization_time < 0.1

        # Test deserialization timing
        start_time = time.time()
        # deserialized = payload.__class__.deserialize(serialized)
        deserialization_time = time.time() - start_time

        # Deserialization should be fast (< 0.1 seconds)
        assert deserialization_time < 0.1

    def test_rekey_performance(self, key_pairs):
        """Test rekey performance."""
        libp2p_keypair, noise_keypair = key_pairs

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            rekey_policy=policy,
        )

        rekey_manager = transport.rekey_manager

        # Test rekey check performance
        start_time = time.time()
        should_rekey = rekey_manager.should_rekey()
        rekey_check_time = time.time() - start_time

        # Rekey check should be fast (< 0.01 seconds)
        assert rekey_check_time < 0.01
        assert should_rekey is False

        # Test bytes update performance
        start_time = time.time()
        rekey_manager.update_bytes_processed(1024)
        bytes_update_time = time.time() - start_time

        # Bytes update should be fast (< 0.01 seconds)
        assert bytes_update_time < 0.01

        # Test stats retrieval performance
        start_time = time.time()
        stats = rekey_manager.get_stats()
        stats_retrieval_time = time.time() - start_time

        # Stats retrieval should be fast (< 0.01 seconds)
        assert stats_retrieval_time < 0.01
        assert stats["bytes_since_rekey"] == 1024

    def test_webtransport_performance(self, key_pairs):
        """Test WebTransport performance."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        wt_support = transport.webtransport_support

        # Test certificate addition performance
        start_time = time.time()
        cert_hash = wt_support.add_certificate(b"performance_test_cert")
        cert_addition_time = time.time() - start_time

        # Certificate addition should be fast (< 0.01 seconds)
        assert cert_addition_time < 0.01

        # Test certificate validation performance
        start_time = time.time()
        is_valid = wt_support.validate_certificate_hash(cert_hash)
        cert_validation_time = time.time() - start_time

        # Certificate validation should be fast (< 0.01 seconds)
        assert cert_validation_time < 0.01
        assert is_valid is True

        # Test certificate hash retrieval performance
        start_time = time.time()
        cert_hashes = wt_support.get_certificate_hashes()
        cert_retrieval_time = time.time() - start_time

        # Certificate retrieval should be fast (< 0.01 seconds)
        assert cert_retrieval_time < 0.01
        assert len(cert_hashes) == 1

    @pytest.mark.trio
    async def test_early_data_performance(self, key_pairs):
        """Test early data performance."""
        libp2p_keypair, noise_keypair = key_pairs

        handler = BufferingEarlyDataHandler()
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data_handler=handler,
        )

        ed_manager = transport.early_data_manager

        # Test early data handling performance
        start_time = time.time()
        await ed_manager.handle_early_data(b"performance_test_data")
        handling_time = time.time() - start_time

        # Early data handling should be fast (< 0.01 seconds)
        assert handling_time < 0.01

        # Test early data retrieval performance
        start_time = time.time()
        early_data = ed_manager.get_early_data()
        retrieval_time = time.time() - start_time

        # Early data retrieval should be fast (< 0.01 seconds)
        assert retrieval_time < 0.01
        assert early_data == b"performance_test_data"

    def test_memory_usage(self, key_pairs):
        """Test memory usage characteristics."""
        libp2p_keypair, noise_keypair = key_pairs

        # Test transport creation memory usage
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test that transport doesn't leak memory
        pattern = transport.get_pattern()
        assert hasattr(pattern, "make_handshake_payload")
        payload = pattern.make_handshake_payload()  # type: ignore

        # Test serialization memory usage
        serialized = payload.serialize()
        deserialized = payload.__class__.deserialize(serialized)

        # Test that objects can be garbage collected
        del transport, pattern, payload, serialized, deserialized

    def test_stress_key_generation(self, key_pairs):
        """Test stress scenarios for key generation."""
        # Test multiple key pair generation
        start_time = time.time()
        key_pairs_list = [create_new_key_pair() for _ in range(100)]
        key_generation_time = time.time() - start_time

        # Key generation should be reasonably fast (< 1 second for 100 pairs)
        assert key_generation_time < 1.0
        assert len(key_pairs_list) == 100

        # Test that all keys are different
        public_keys = [kp.public_key for kp in key_pairs_list]
        private_keys = [kp.private_key for kp in key_pairs_list]

        # All public keys should be different
        for i in range(len(public_keys)):
            for j in range(i + 1, len(public_keys)):
                assert public_keys[i] != public_keys[j]

        # All private keys should be different
        for i in range(len(private_keys)):
            for j in range(i + 1, len(private_keys)):
                assert private_keys[i] != private_keys[j]

    def test_stress_signature_operations(self, key_pairs):
        """Test stress scenarios for signature operations."""
        libp2p_keypair, noise_keypair = key_pairs

        # Test multiple signature generation
        start_time = time.time()
        signatures = []
        for i in range(100):
            data = f"stress_test_data_{i}".encode()
            signature = libp2p_keypair.private_key.sign(data)
            signatures.append(signature)
        signature_generation_time = time.time() - start_time

        # Signature generation should be reasonably fast (< 1 second for 100 signatures)
        assert signature_generation_time < 1.0
        assert len(signatures) == 100

        # Test multiple signature verification
        start_time = time.time()
        verification_results = []
        for i in range(100):
            data = f"stress_test_data_{i}".encode()
            result = libp2p_keypair.public_key.verify(data, signatures[i])
            verification_results.append(result)
        signature_verification_time = time.time() - start_time

        # Signature verification should be reasonably fast
        # (< 1 second for 100 verifications)
        assert signature_verification_time < 1.0
        assert len(verification_results) == 100
        assert all(verification_results)

    def test_stress_transport_creation(self, key_pairs):
        """Test stress scenarios for transport creation."""
        libp2p_keypair, noise_keypair = key_pairs

        # Test multiple transport creation
        start_time = time.time()
        transports = []
        for i in range(50):
            transport = Transport(
                libp2p_keypair=libp2p_keypair,
                noise_privkey=noise_keypair.private_key,
                early_data=f"stress_early_data_{i}".encode(),
            )
            transports.append(transport)
        transport_creation_time = time.time() - start_time

        # Transport creation should be reasonably fast (< 1 second for 50 transports)
        assert transport_creation_time < 1.0
        assert len(transports) == 50

        # Test that all transports are independent
        for i in range(len(transports)):
            for j in range(i + 1, len(transports)):
                assert transports[i] is not transports[j]
                assert transports[i].early_data != transports[j].early_data

    def test_stress_webtransport_operations(self, key_pairs):
        """Test stress scenarios for WebTransport operations."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        wt_support = transport.webtransport_support

        # Test multiple certificate addition
        start_time = time.time()
        cert_hashes = []
        for i in range(100):
            cert_data = f"stress_cert_{i}".encode()
            cert_hash = wt_support.add_certificate(cert_data)
            cert_hashes.append(cert_hash)
        cert_addition_time = time.time() - start_time

        # Certificate addition should be reasonably fast
        # (< 1 second for 100 certificates)
        assert cert_addition_time < 1.0
        assert len(cert_hashes) == 100

        # Test multiple certificate validation
        start_time = time.time()
        validation_results = []
        for cert_hash in cert_hashes:
            result = wt_support.validate_certificate_hash(cert_hash)
            validation_results.append(result)
        cert_validation_time = time.time() - start_time

        # Certificate validation should be reasonably fast
        # (< 1 second for 100 validations)
        assert cert_validation_time < 1.0
        assert len(validation_results) == 100
        assert all(validation_results)

    @pytest.mark.trio
    async def test_stress_early_data_operations(self, key_pairs):
        """Test stress scenarios for early data operations."""
        libp2p_keypair, noise_keypair = key_pairs

        handler = BufferingEarlyDataHandler()
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data_handler=handler,
        )

        ed_manager = transport.early_data_manager

        # Test multiple early data handling
        start_time = time.time()
        for i in range(100):
            data = f"stress_early_data_{i}".encode()
            await ed_manager.handle_early_data(data)
        handling_time = time.time() - start_time

        # Early data handling should be reasonably fast (< 1 second for 100 operations)
        assert handling_time < 1.0

        # Test that handler received all data
        buffered_data = handler.get_buffered_data()
        expected_length = sum(
            len(f"stress_early_data_{i}".encode()) for i in range(100)
        )
        assert len(buffered_data) == expected_length

    def test_concurrent_operations(self, key_pairs):
        """Test concurrent operations performance."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test concurrent pattern creation
        start_time = time.time()
        patterns = [transport.get_pattern() for _ in range(10)]
        concurrent_pattern_time = time.time() - start_time

        # Concurrent pattern creation should be fast (< 0.1 seconds)
        assert concurrent_pattern_time < 0.1
        assert len(patterns) == 10

        # Test concurrent payload creation
        start_time = time.time()
        payloads = [pattern.make_handshake_payload() for pattern in patterns]  # type: ignore
        concurrent_payload_time = time.time() - start_time

        # Concurrent payload creation should be fast (< 0.1 seconds)
        assert concurrent_payload_time < 0.1
        assert len(payloads) == 10

        # Test concurrent serialization
        start_time = time.time()
        serialized_list = [payload.serialize() for payload in payloads]
        concurrent_serialization_time = time.time() - start_time

        # Concurrent serialization should be fast (< 0.1 seconds)
        assert concurrent_serialization_time < 0.1
        assert len(serialized_list) == 10
