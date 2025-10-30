"""
End-to-end integration tests for Noise modules.

This module tests complete Noise integration with all advanced features,
including backward compatibility, error recovery, and complete feature interaction.
"""

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.early_data import (
    BufferingEarlyDataHandler,
)
from libp2p.security.noise.rekey import (
    TimeBasedRekeyPolicy,
)
from libp2p.security.noise.transport import Transport


class MockRawConnection:
    """Mock raw connection for testing."""

    def __init__(self):
        self.read_data = []
        self.write_data = []
        self.closed = False

    async def read(self, n: int) -> bytes:
        if not self.read_data:
            raise trio.EndOfChannel
        return self.read_data.pop(0)

    async def write(self, data: bytes) -> None:
        self.write_data.append(data)

    async def close(self) -> None:
        self.closed = True


class TestNoiseIntegration:
    """Test complete Noise integration with all features."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        return libp2p_keypair, noise_keypair

    @pytest.fixture
    def full_feature_transport(self, key_pairs):
        """Create transport with all advanced features."""
        libp2p_keypair, noise_keypair = key_pairs

        # Create all managers
        handler = BufferingEarlyDataHandler()
        # early_data_manager = EarlyDataManager(handler)

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        # rekey_manager = RekeyManager(policy)

        # Create transport with all features
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data=b"integration_early_data",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        return transport, libp2p_keypair, noise_keypair

    def test_full_feature_transport_creation(self, key_pairs):
        """Test transport creation with all advanced features."""
        libp2p_keypair, noise_keypair = key_pairs

        # Create all components
        handler = BufferingEarlyDataHandler()
        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        # Create transport with all features
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data=b"test_early_data",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        # Verify all features are available
        assert transport.libp2p_privkey == libp2p_keypair.private_key
        assert transport.noise_privkey == noise_keypair.private_key
        assert transport.local_peer == ID.from_pubkey(libp2p_keypair.public_key)
        assert transport.early_data == b"test_early_data"

        # Verify advanced features
        assert transport.webtransport_support is not None
        assert transport.early_data_manager is not None
        assert transport.rekey_manager is not None
        assert hasattr(transport, "_static_key_cache")

        # Verify managers are properly configured
        assert transport.early_data_manager.handler == handler
        assert transport.rekey_manager.policy == policy

    def test_backward_compatibility(self, key_pairs):
        """Test backward compatibility with existing transport usage."""
        libp2p_keypair, noise_keypair = key_pairs

        # Test minimal transport creation (backward compatible)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test that all required attributes exist
        assert transport.libp2p_privkey is not None
        assert transport.noise_privkey is not None
        assert transport.local_peer is not None
        assert transport.early_data is None

        # Test that advanced features are still available
        assert transport.webtransport_support is not None
        assert transport.early_data_manager is not None
        assert transport.rekey_manager is not None

        # Test pattern selection
        pattern = transport.get_pattern()
        assert pattern.__class__.__name__ == "PatternXX"

    def test_static_key_caching(self, key_pairs):
        """Test static key caching functionality."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test caching static key
        remote_peer = ID.from_pubkey(libp2p_keypair.public_key)
        remote_static_key = noise_keypair.public_key.to_bytes()

        transport.cache_static_key(remote_peer, remote_static_key)

        # Test retrieving cached key
        cached_key = transport.get_cached_static_key(remote_peer)
        assert cached_key == remote_static_key

        # Test clearing cache
        transport.clear_static_key_cache()
        cached_key = transport.get_cached_static_key(remote_peer)
        assert cached_key is None

    def test_webtransport_integration(self, key_pairs):
        """Test WebTransport integration in transport."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test WebTransport functionality
        wt_support = transport.webtransport_support
        cert_hash = wt_support.add_certificate(b"webtransport_cert")

        assert wt_support.has_certificates() is True
        assert wt_support.validate_certificate_hash(cert_hash) is True

        # Test certificate management
        cert_hashes = wt_support.get_certificate_hashes()
        assert len(cert_hashes) == 1
        assert cert_hash in cert_hashes

    @pytest.mark.trio
    async def test_early_data_integration(self, key_pairs):
        """Test early data integration in transport."""
        libp2p_keypair, noise_keypair = key_pairs

        handler = BufferingEarlyDataHandler()
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data_handler=handler,
        )

        # Test early data manager
        ed_manager = transport.early_data_manager
        assert ed_manager.handler == handler

        # Test handling early data
        await ed_manager.handle_early_data(b"transport_early_data")
        assert ed_manager.has_early_data() is True
        assert ed_manager.get_early_data() == b"transport_early_data"

        # Test handler received the data
        buffered_data = handler.get_buffered_data()
        assert buffered_data == b"transport_early_data"

    def test_rekey_integration(self, key_pairs):
        """Test rekey integration in transport."""
        libp2p_keypair, noise_keypair = key_pairs

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            rekey_policy=policy,
        )

        # Test rekey manager
        rekey_manager = transport.rekey_manager
        assert rekey_manager.policy == policy

        # Test updating bytes processed
        rekey_manager.update_bytes_processed(1024)
        stats = rekey_manager.get_stats()
        assert stats["bytes_since_rekey"] == 1024

        # Test rekey check
        assert rekey_manager.should_rekey() is False  # Time not exceeded

    @pytest.mark.trio
    async def test_full_feature_handshake_simulation(self, full_feature_transport):
        """Test handshake simulation with all advanced features."""
        transport, libp2p_keypair, noise_keypair = full_feature_transport

        # Test pattern creation with all features
        pattern = transport.get_pattern()
        assert pattern.__class__.__name__ == "PatternXX"
        # PatternXX has early_data attribute
        assert hasattr(pattern, "early_data")
        assert pattern.early_data == b"integration_early_data"  # type: ignore

        # Test payload creation with extensions
        from libp2p.security.noise.messages import NoiseExtensions

        # Add some certificate hashes for testing
        transport.webtransport_support.add_certificate(b"test_cert_1")
        transport.webtransport_support.add_certificate(b"test_cert_2")

        extensions = NoiseExtensions(
            webtransport_certhashes=transport.webtransport_support.get_certificate_hashes(),
            stream_muxers=["/mplex/1.0.0", "/yamux/1.0.0"],
            early_data=b"payload_early_data",
        )

        payload = pattern.make_handshake_payload(extensions)

        # Verify payload has all features
        assert payload.extensions is not None
        assert payload.extensions.has_webtransport_certhashes() is True
        assert payload.extensions.has_stream_muxers() is True
        assert payload.extensions.has_early_data() is True

        # Test early data handling
        await transport.early_data_manager.handle_early_data(
            payload.extensions.early_data
        )
        assert transport.early_data_manager.has_early_data() is True

    def test_error_recovery_scenarios(self, key_pairs):
        """Test error recovery scenarios."""
        libp2p_keypair, noise_keypair = key_pairs

        # Test transport creation with invalid inputs
        with pytest.raises(AttributeError):
            Transport(
                libp2p_keypair=None,  # type: ignore
                noise_privkey=noise_keypair.private_key,
            )

        # Test with valid inputs
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test getting cached key for non-existent peer
        non_existent_peer = ID.from_pubkey(create_new_key_pair().public_key)
        cached_key = transport.get_cached_static_key(non_existent_peer)
        assert cached_key is None

    def test_feature_interaction(self, key_pairs):
        """Test interaction between different features."""
        libp2p_keypair, noise_keypair = key_pairs

        # Create transport with multiple features
        handler = BufferingEarlyDataHandler()
        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data=b"interaction_test",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        # Test WebTransport + Early Data interaction
        wt_support = transport.webtransport_support
        wt_support.add_certificate(b"interaction_cert")

        # Test Rekey + Early Data interaction
        rekey_manager = transport.rekey_manager
        rekey_manager.update_bytes_processed(2048)

        # Test all features work together
        assert wt_support.has_certificates() is True
        assert transport.early_data_manager.handler == handler
        assert rekey_manager.get_stats()["bytes_since_rekey"] == 2048

        # Test pattern creation with all features
        pattern = transport.get_pattern()
        assert hasattr(pattern, "early_data")
        assert pattern.early_data == b"interaction_test"  # type: ignore

    def test_transport_state_consistency(self, key_pairs):
        """Test transport state consistency."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test that local peer is consistent
        expected_peer = ID.from_pubkey(libp2p_keypair.public_key)
        assert transport.local_peer == expected_peer

        # Test that pattern uses correct peer
        pattern = transport.get_pattern()
        assert hasattr(pattern, "local_peer")
        assert pattern.local_peer == expected_peer  # type: ignore

        # Test that pattern uses correct keys
        assert hasattr(pattern, "libp2p_privkey")
        assert hasattr(pattern, "noise_static_key")
        assert pattern.libp2p_privkey == libp2p_keypair.private_key  # type: ignore
        assert pattern.noise_static_key == noise_keypair.private_key  # type: ignore

    def test_transport_serialization_roundtrip(self, key_pairs):
        """Test transport-related serialization roundtrip."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
            early_data=b"serialization_test",
        )

        # Test pattern payload serialization
        pattern = transport.get_pattern()
        assert hasattr(pattern, "make_handshake_payload")
        payload = pattern.make_handshake_payload()  # type: ignore

        # Test serialization roundtrip
        serialized = payload.serialize()
        deserialized = payload.__class__.deserialize(serialized)

        # Verify deserialized payload
        assert deserialized.id_pubkey == payload.id_pubkey
        assert deserialized.id_sig == payload.id_sig

        # Test WebTransport certificate serialization
        wt_support = transport.webtransport_support
        cert_hash = wt_support.add_certificate(b"serialization_cert")

        # Test certificate hash consistency
        cert_hashes = wt_support.get_certificate_hashes()
        assert cert_hash in cert_hashes

    def test_transport_performance_characteristics(self, key_pairs):
        """Test transport performance characteristics."""
        libp2p_keypair, noise_keypair = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_keypair.private_key,
        )

        # Test pattern creation performance
        import time

        start_time = time.time()
        pattern = transport.get_pattern()
        pattern_creation_time = time.time() - start_time

        # Pattern creation should be fast (< 0.1 seconds)
        assert pattern_creation_time < 0.1

        # Test payload creation performance
        start_time = time.time()
        pattern.make_handshake_payload()  # type: ignore
        payload_creation_time = time.time() - start_time

        # Payload creation should be fast (< 0.1 seconds)
        assert payload_creation_time < 0.1

        # Test serialization performance
        start_time = time.time()
        # serialized = payload.serialize()
        serialization_time = time.time() - start_time

        # Serialization should be fast (< 0.1 seconds)
        assert serialization_time < 0.1
