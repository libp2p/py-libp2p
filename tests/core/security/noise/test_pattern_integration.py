"""
Integration tests for pattern with other Noise modules.

This module tests pattern integration with early data manager,
rekey manager, WebTransport, and other advanced features.
"""

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.early_data import (
    BufferingEarlyDataHandler,
    EarlyDataManager,
)
from libp2p.security.noise.patterns import PatternXX
from libp2p.security.noise.rekey import (
    RekeyManager,
    TimeBasedRekeyPolicy,
)
from libp2p.security.noise.webtransport import WebTransportSupport


class TestPatternIntegration:
    """Test pattern integration with other modules."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        return libp2p_keypair, noise_keypair

    @pytest.fixture
    def pattern_with_early_data(self, key_pairs):
        """Create pattern with early data."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
            early_data=b"test_early_data",
        )

        return pattern, libp2p_keypair, noise_keypair

    def test_pattern_with_early_data_manager(self, pattern_with_early_data):
        """Test pattern integration with early data manager."""
        pattern, libp2p_keypair, noise_keypair = pattern_with_early_data

        # Create early data manager
        handler = BufferingEarlyDataHandler()
        manager = EarlyDataManager(handler)

        # Test that pattern has early data
        assert pattern.early_data == b"test_early_data"

        # Test payload creation with early data
        payload = pattern.make_handshake_payload()

        # When no extensions are provided, early data is not included in payload
        # This is the current behavior - early data is only included when
        # extensions are provided
        assert payload.extensions is None

        # Test payload creation with extensions (this will include early data)
        from libp2p.security.noise.messages import NoiseExtensions

        extensions = NoiseExtensions()
        payload_with_extensions = pattern.make_handshake_payload(extensions)

        # Now early data should be included
        assert payload_with_extensions.extensions is not None
        assert payload_with_extensions.extensions.early_data == b"test_early_data"

        # Test that manager can handle the early data
        assert manager.handler == handler

    @pytest.mark.trio
    async def test_pattern_early_data_handling(self, pattern_with_early_data):
        """Test pattern early data handling through manager."""
        pattern, libp2p_keypair, noise_keypair = pattern_with_early_data

        # Create early data manager
        handler = BufferingEarlyDataHandler()
        manager = EarlyDataManager(handler)

        # Test handling early data
        await manager.handle_early_data(pattern.early_data)

        # Verify early data was handled
        assert manager.has_early_data() is True
        assert manager.get_early_data() == b"test_early_data"

        # Verify handler received the data
        buffered_data = handler.get_buffered_data()
        assert buffered_data == b"test_early_data"

    def test_pattern_with_rekey_manager(self, key_pairs):
        """Test pattern integration with rekey manager."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
        )

        # Create rekey manager
        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        rekey_manager = RekeyManager(policy)

        # Test that pattern can work with rekey manager
        # (Pattern doesn't directly use rekey manager, but transport does)
        assert rekey_manager.policy == policy

        # Test rekey manager functionality
        assert rekey_manager.should_rekey() is False
        rekey_manager.update_bytes_processed(1024)
        assert rekey_manager.get_stats()["bytes_since_rekey"] == 1024

        # Test that pattern was created successfully
        assert pattern.local_peer == local_peer
        assert pattern.libp2p_privkey == libp2p_keypair.private_key
        assert pattern.noise_static_key == noise_keypair.private_key

    def test_pattern_with_webtransport(self, key_pairs):
        """Test pattern integration with WebTransport."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
        )

        # Create WebTransport support
        webtransport_support = WebTransportSupport()

        # Add certificate
        cert_hash = webtransport_support.add_certificate(b"test_certificate")

        # Test WebTransport functionality
        assert webtransport_support.has_certificates() is True
        assert webtransport_support.validate_certificate_hash(cert_hash) is True

        # Test pattern payload creation with WebTransport extensions
        from libp2p.security.noise.messages import NoiseExtensions

        extensions = NoiseExtensions(
            webtransport_certhashes=[cert_hash],
            stream_muxers=["/mplex/1.0.0"],
        )

        payload = pattern.make_handshake_payload(extensions)

        # Verify payload has WebTransport extensions
        assert payload.extensions is not None
        assert payload.extensions.has_webtransport_certhashes() is True
        assert cert_hash in payload.extensions.webtransport_certhashes

    def test_pattern_with_combined_features(self, key_pairs):
        """Test pattern with all advanced features combined."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern with early data
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
            early_data=b"combined_early_data",
        )

        # Create all managers
        handler = BufferingEarlyDataHandler()
        early_data_manager = EarlyDataManager(handler)

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        rekey_manager = RekeyManager(policy)

        webtransport_support = WebTransportSupport()
        cert_hash = webtransport_support.add_certificate(b"combined_cert")

        # Test combined extensions
        from libp2p.security.noise.messages import NoiseExtensions

        extensions = NoiseExtensions(
            webtransport_certhashes=[cert_hash],
            stream_muxers=["/mplex/1.0.0", "/yamux/1.0.0"],
            early_data=b"extensions_early_data",  # Different from pattern early data
        )

        # Test payload creation with combined features
        payload = pattern.make_handshake_payload(extensions)

        # Verify payload has all features
        assert payload.extensions is not None
        assert payload.extensions.has_webtransport_certhashes() is True
        assert payload.extensions.has_stream_muxers() is True
        assert payload.extensions.has_early_data() is True

        # Verify early data priority (extensions early data should be used)
        assert payload.extensions.early_data == b"extensions_early_data"

        # Test managers are ready
        assert early_data_manager.handler == handler
        assert rekey_manager.policy == policy
        assert webtransport_support.has_certificates() is True

    @pytest.mark.trio
    async def test_pattern_early_data_priority(self, key_pairs):
        """Test early data priority handling."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern with early data
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
            early_data=b"pattern_early_data",
        )

        from libp2p.security.noise.messages import NoiseExtensions

        # Test case 1: Extensions have early data (should use extensions)
        extensions_with_early_data = NoiseExtensions(
            early_data=b"extensions_early_data",
        )

        payload1 = pattern.make_handshake_payload(extensions_with_early_data)
        assert payload1.extensions is not None
        assert payload1.extensions.early_data == b"extensions_early_data"

        # Test case 2: Extensions don't have early data (should use pattern)
        extensions_without_early_data = NoiseExtensions(
            stream_muxers=["/mplex/1.0.0"],
        )

        payload2 = pattern.make_handshake_payload(extensions_without_early_data)
        assert payload2.extensions is not None
        assert payload2.extensions.early_data == b"pattern_early_data"

        # Test case 3: No extensions (should create empty payload)
        payload3 = pattern.make_handshake_payload(None)
        assert payload3.extensions is None

    def test_pattern_noise_state_consistency(self, key_pairs):
        """Test that Noise state creation is consistent."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
        )

        # Test multiple state creations
        state1 = pattern.create_noise_state()
        state2 = pattern.create_noise_state()

        # States should be independent but have same configuration
        assert state1.protocol_name == state2.protocol_name
        assert state1.noise_protocol is not None
        assert state2.noise_protocol is not None
        assert state1.noise_protocol.name == state2.noise_protocol.name

        # Test that states are independent instances
        assert state1 is not state2

        # Test protocol name consistency
        assert pattern.protocol_name == b"Noise_XX_25519_ChaChaPoly_SHA256"

    def test_pattern_serialization_roundtrip(self, key_pairs):
        """Test pattern payload serialization roundtrip."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
            early_data=b"serialization_test",
        )

        # Create payload with extensions
        from libp2p.security.noise.messages import NoiseExtensions

        extensions = NoiseExtensions(
            webtransport_certhashes=[b"cert_hash"],
            stream_muxers=["/mplex/1.0.0"],
            early_data=b"extensions_early_data",
        )

        payload = pattern.make_handshake_payload(extensions)

        # Test serialization roundtrip
        serialized = payload.serialize()
        deserialized = payload.__class__.deserialize(serialized)

        # Verify deserialized payload
        assert deserialized.id_pubkey == payload.id_pubkey
        assert deserialized.id_sig == payload.id_sig
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == b"extensions_early_data"
        assert deserialized.extensions.webtransport_certhashes == [b"cert_hash"]
        assert deserialized.extensions.stream_muxers == ["/mplex/1.0.0"]

    def test_pattern_error_handling_integration(self, key_pairs):
        """Test pattern error handling in integration scenarios."""
        libp2p_keypair, noise_keypair = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        # Create pattern
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_keypair.private_key,
        )

        # Test with invalid extensions
        from libp2p.security.noise.messages import NoiseExtensions

        # Test with empty extensions
        empty_extensions = NoiseExtensions()
        payload1 = pattern.make_handshake_payload(empty_extensions)
        assert payload1.extensions == empty_extensions

        # Test with None extensions
        payload2 = pattern.make_handshake_payload(None)
        assert payload2.extensions is None
