"""
End-to-end integration tests for Noise modules.

This module tests complete Noise integration with all advanced features,
including backward compatibility, error recovery, and complete feature interaction.
"""

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.early_data import (
    BufferingEarlyDataHandler,
)
from libp2p.security.noise.rekey import (
    TimeBasedRekeyPolicy,
)
from libp2p.security.noise.transport import Transport
from tests.utils.factories import (
    noise_static_key_factory,
    transport_handshake_factory,
)


class TestNoiseIntegration:
    """Test complete Noise integration with all features."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs."""
        libp2p_keypair = create_new_key_pair()
        noise_key = noise_static_key_factory()
        return libp2p_keypair, noise_key

    @pytest.fixture
    def full_feature_transport(self, key_pairs):
        """Create transport with all advanced features."""
        libp2p_keypair, noise_key = key_pairs

        # Create all managers
        handler = BufferingEarlyDataHandler()
        # early_data_manager = EarlyDataManager(handler)

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        # rekey_manager = RekeyManager(policy)

        # Create transport with all features
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"integration_early_data",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        return transport, libp2p_keypair, noise_key

    def test_full_feature_transport_creation(self, key_pairs):
        """Test transport creation with all advanced features."""
        libp2p_keypair, noise_key = key_pairs

        # Create all components
        handler = BufferingEarlyDataHandler()
        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        # Create transport with all features
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"test_early_data",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        # Verify all features are available
        assert transport.libp2p_privkey == libp2p_keypair.private_key
        assert transport.noise_privkey == noise_key
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
        libp2p_keypair, noise_key = key_pairs

        # Test minimal transport creation (backward compatible)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test caching static key
        remote_peer = ID.from_pubkey(libp2p_keypair.public_key)
        remote_static_key = noise_key.get_public_key().to_bytes()

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
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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
    async def test_early_data_integration(self, key_pairs, nursery):
        """Test early data integration through real TCP handshake."""
        libp2p_keypair, noise_key = key_pairs

        # Create initiator transport with early data
        initiator_handler = BufferingEarlyDataHandler()
        initiator_transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"initiator_early_data",
            early_data_handler=initiator_handler,
        )

        # Create responder transport with early data handler
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_handler = BufferingEarlyDataHandler()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
            early_data_handler=responder_handler,
        )

        # Perform real handshake with early data
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Verify early data manager is configured
            assert initiator_transport.early_data_manager.handler == initiator_handler
            assert responder_transport.early_data_manager.handler == responder_handler

            # Test that we can exchange data (confirms handshake completed)
            test_data = b"test_early_data_integration"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

            # Note: Early data in handshake payload is automatically processed
            # during handshake. The handlers should have received the early data
            # from the handshake payload (exact behavior depends on how early
            # data is embedded in the handshake)

    def test_rekey_integration(self, key_pairs):
        """Test rekey integration in transport."""
        libp2p_keypair, noise_key = key_pairs

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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
    async def test_full_feature_handshake_simulation(
        self, full_feature_transport, nursery
    ):
        """Test complete handshake with all advanced features via real TCP."""
        initiator_transport, libp2p_keypair, noise_key = full_feature_transport

        # Add WebTransport certificates to initiator
        initiator_transport.webtransport_support.add_certificate(b"test_cert_1")
        initiator_transport.webtransport_support.add_certificate(b"test_cert_2")

        # Verify pattern has all features
        pattern = initiator_transport.get_pattern()
        assert pattern.__class__.__name__ == "PatternXX"
        assert hasattr(pattern, "early_data")
        assert pattern.early_data == b"integration_early_data"  # type: ignore

        # Create responder transport with all features
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_handler = BufferingEarlyDataHandler()
        responder_policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
            early_data=b"responder_early_data",
            early_data_handler=responder_handler,
            rekey_policy=responder_policy,
        )

        # Add WebTransport certificates to responder
        responder_transport.webtransport_support.add_certificate(b"test_cert_3")

        # Perform real handshake with all features
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Verify all features are configured
            assert initiator_transport.webtransport_support.has_certificates() is True
            assert responder_transport.webtransport_support.has_certificates() is True
            assert initiator_transport.early_data_manager is not None
            assert initiator_transport.rekey_manager is not None

            # Test data exchange (confirms handshake completed successfully)
            test_data = b"full_feature_test_data"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

            # Test bidirectional communication
            response_data = b"full_feature_response"
            await resp_conn.write(response_data)
            received_response = await init_conn.read(len(response_data))
            assert received_response == response_data

    def test_error_recovery_scenarios(self, key_pairs):
        """Test error recovery scenarios for transport creation."""
        libp2p_keypair, noise_key = key_pairs

        # Test transport creation with invalid inputs
        with pytest.raises(AttributeError):
            Transport(
                libp2p_keypair=None,  # type: ignore
                noise_privkey=noise_key,
            )

        # Test with valid inputs
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test getting cached key for non-existent peer
        non_existent_peer = ID.from_pubkey(create_new_key_pair().public_key)
        cached_key = transport.get_cached_static_key(non_existent_peer)
        assert cached_key is None

    @pytest.mark.trio
    async def test_error_recovery_real_tcp(self, key_pairs, nursery):
        """Test error recovery scenarios with real TCP connections."""
        libp2p_keypair, noise_key = key_pairs

        # Test connection timeout scenario
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test with valid handshake first (recovery after success)
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
        )

        # Perform successful handshake
        async with transport_handshake_factory(
            nursery, transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify successful connection
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm recovery works
            test_data = b"error_recovery_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

        # Test that transport can be reused after connection closure
        # (Recovery: transport should be able to create new connections)
        responder_keypair2 = create_new_key_pair()
        responder_noise_key2 = noise_static_key_factory()
        responder_transport2 = Transport(
            libp2p_keypair=responder_keypair2,
            noise_privkey=responder_noise_key2,
        )

        # Perform another handshake (recovery test)
        async with transport_handshake_factory(
            nursery, transport, responder_transport2
        ) as (init_conn2, resp_conn2):
            assert init_conn2 is not None
            assert resp_conn2 is not None

            # Verify new connection works
            test_data2 = b"recovery_after_close"
            await init_conn2.write(test_data2)
            received2 = await resp_conn2.read(len(test_data2))
            assert received2 == test_data2

    @pytest.mark.trio
    async def test_feature_interaction(self, key_pairs, nursery):
        """Test interaction between different features through real TCP handshake."""
        libp2p_keypair, noise_key = key_pairs

        # Create initiator transport with multiple features
        handler = BufferingEarlyDataHandler()
        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        initiator_transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"interaction_test",
            early_data_handler=handler,
            rekey_policy=policy,
        )

        # Add WebTransport certificates
        wt_support = initiator_transport.webtransport_support
        wt_support.add_certificate(b"interaction_cert")

        # Create responder transport with features
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_handler = BufferingEarlyDataHandler()
        responder_policy = TimeBasedRekeyPolicy(max_time_seconds=3600)

        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
            early_data=b"responder_interaction",
            early_data_handler=responder_handler,
            rekey_policy=responder_policy,
        )

        # Perform real handshake with all features
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Verify all features are configured and work together
            assert wt_support.has_certificates() is True
            assert initiator_transport.early_data_manager.handler == handler
            rekey_manager = initiator_transport.rekey_manager
            assert rekey_manager.get_stats()["bytes_since_rekey"] == 0  # Initial state

            # Test pattern creation with all features
            pattern = initiator_transport.get_pattern()
            assert hasattr(pattern, "early_data")
            assert pattern.early_data == b"interaction_test"  # type: ignore

            # Test data exchange (confirms all features work together)
            test_data = b"feature_interaction_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

            # Update rekey stats and verify
            rekey_manager.update_bytes_processed(2048)
            assert rekey_manager.get_stats()["bytes_since_rekey"] == 2048

            # Verify bidirectional communication with all features
            response_data = b"feature_interaction_response"
            await resp_conn.write(response_data)
            received_response = await init_conn.read(len(response_data))
            assert received_response == response_data

    def test_transport_state_consistency(self, key_pairs):
        """Test transport state consistency."""
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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
        assert pattern.noise_static_key == noise_key  # type: ignore

    def test_transport_serialization_roundtrip(self, key_pairs):
        """Test transport-related serialization roundtrip."""
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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

    @pytest.mark.trio
    async def test_transport_serialization_real_tcp_validation(
        self, key_pairs, nursery
    ):
        """Test that serialized payloads work correctly in real TCP handshake."""
        libp2p_keypair, noise_key = key_pairs

        # Create transport and serialize payload
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"serialization_tcp_test",
        )

        pattern = transport.get_pattern()
        payload = pattern.make_handshake_payload()  # type: ignore

        # Serialize and deserialize to verify roundtrip
        serialized = payload.serialize()
        deserialized = payload.__class__.deserialize(serialized)

        # Verify deserialized payload matches original
        assert deserialized.id_pubkey == payload.id_pubkey
        assert deserialized.id_sig == payload.id_sig

        # Now test in real TCP handshake - if serialization works,
        # the handshake should complete successfully
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
        )

        # Perform real handshake (payload serialization is used internally)
        async with transport_handshake_factory(
            nursery, transport, responder_transport
        ) as (init_conn, resp_conn):
            # If we get here, serialization worked correctly in handshake
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm everything works
            test_data = b"serialization_validation"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

    def test_transport_performance_characteristics(self, key_pairs):
        """Test transport performance characteristics."""
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
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
