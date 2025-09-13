"""Tests for early data support through noise extensions (Phase 2)."""

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.messages import NoiseExtensions, NoiseHandshakePayload
from libp2p.security.noise.patterns import PatternXX


class TestNoiseExtensionsEarlyData:
    """Test NoiseExtensions with early data support."""

    def test_extensions_with_early_data(self):
        """Test creating extensions with early data."""
        early_data = b"test_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes, early_data=early_data)

        assert ext.early_data == early_data
        assert ext.webtransport_certhashes == certhashes

    def test_extensions_without_early_data(self):
        """Test creating extensions without early data."""
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        assert ext.early_data is None
        assert ext.webtransport_certhashes == certhashes

    def test_extensions_protobuf_conversion_with_early_data(self):
        """Test protobuf conversion with early data."""
        early_data = b"test_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes, early_data=early_data)

        # Convert to protobuf and back
        pb_ext = ext.to_protobuf()
        ext_roundtrip = NoiseExtensions.from_protobuf(pb_ext)

        assert ext_roundtrip.early_data == early_data
        assert ext_roundtrip.webtransport_certhashes == certhashes

    def test_extensions_protobuf_conversion_without_early_data(self):
        """Test protobuf conversion without early data."""
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        # Convert to protobuf and back
        pb_ext = ext.to_protobuf()
        ext_roundtrip = NoiseExtensions.from_protobuf(pb_ext)

        assert ext_roundtrip.early_data is None
        assert ext_roundtrip.webtransport_certhashes == certhashes


class TestNoiseHandshakePayloadEarlyData:
    """Test NoiseHandshakePayload with early data through extensions."""

    @pytest.fixture
    def key_pair(self):
        """Create a test key pair."""
        return create_new_key_pair()

    def test_handshake_payload_with_early_data_in_extensions(self, key_pair):
        """Test handshake payload with early data in extensions."""
        early_data = b"test_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes, early_data=early_data)

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            early_data=None,  # No legacy early data
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Early data should come from extensions
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == early_data
        assert deserialized.extensions.webtransport_certhashes == certhashes
        # Legacy early data should also be set for backward compatibility
        assert deserialized.early_data == early_data

    def test_handshake_payload_with_legacy_early_data(self, key_pair):
        """Test handshake payload with legacy early data (backward compatibility)."""
        early_data = b"legacy_early_data"

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            early_data=early_data,
            extensions=None,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should preserve legacy early data
        assert deserialized.early_data == early_data
        assert deserialized.extensions is None

    def test_handshake_payload_with_extensions_and_legacy_early_data(self, key_pair):
        """Test handshake payload with both extensions and legacy early data."""
        legacy_early_data = b"legacy_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            early_data=legacy_early_data,
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should preserve both
        assert deserialized.early_data == legacy_early_data
        assert deserialized.extensions is not None
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.extensions.early_data is None

    def test_handshake_payload_early_data_priority(self, key_pair):
        """Test that early data in extensions takes priority over legacy early data."""
        legacy_early_data = b"legacy_early_data"
        extension_early_data = b"extension_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(
            webtransport_certhashes=certhashes, early_data=extension_early_data
        )

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            early_data=legacy_early_data,  # This should be ignored
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Extension early data should take priority
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == extension_early_data
        assert deserialized.early_data == extension_early_data


class TestPatternEarlyDataIntegration:
    """Test pattern integration with early data through extensions."""

    @pytest.fixture
    def pattern_setup(self):
        """Set up pattern for testing."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer,
            libp2p_keypair.private_key,
            noise_keypair.private_key,
            early_data=b"pattern_early_data",
        )

        return pattern, libp2p_keypair, noise_keypair

    def test_pattern_with_extensions_and_early_data(self, pattern_setup):
        """Test pattern with extensions and early data."""
        pattern, libp2p_keypair, noise_keypair = pattern_setup

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = pattern.make_handshake_payload(extensions=ext)

        # Early data should be in extensions
        assert payload.extensions is not None
        assert payload.extensions.early_data == b"pattern_early_data"
        assert payload.extensions.webtransport_certhashes == certhashes
        # Legacy early data should be None
        assert payload.early_data is None

    def test_pattern_with_extensions_without_early_data(self, pattern_setup):
        """Test pattern with extensions but no early data."""
        pattern, libp2p_keypair, noise_keypair = pattern_setup

        # Create pattern without early data
        libp2p_keypair2 = create_new_key_pair()
        noise_keypair2 = create_new_key_pair()
        local_peer2 = ID.from_pubkey(libp2p_keypair2.public_key)

        pattern_no_early = PatternXX(
            local_peer2,
            libp2p_keypair2.private_key,
            noise_keypair2.private_key,
            early_data=None,
        )

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = pattern_no_early.make_handshake_payload(extensions=ext)

        # Should have extensions but no early data
        assert payload.extensions is not None
        assert payload.extensions.early_data is None
        assert payload.extensions.webtransport_certhashes == certhashes
        assert payload.early_data is None

    def test_pattern_without_extensions_legacy_early_data(self, pattern_setup):
        """Test pattern without extensions (legacy behavior)."""
        pattern, libp2p_keypair, noise_keypair = pattern_setup

        payload = pattern.make_handshake_payload()

        # Should use legacy early data
        assert payload.early_data == b"pattern_early_data"
        assert payload.extensions is None

    def test_pattern_early_data_roundtrip(self, pattern_setup):
        """Test pattern early data roundtrip through serialization."""
        pattern, libp2p_keypair, noise_keypair = pattern_setup

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = pattern.make_handshake_payload(extensions=ext)

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Early data should be preserved
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == b"pattern_early_data"
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.early_data == b"pattern_early_data"


class TestBackwardCompatibility:
    """Test backward compatibility with existing implementations."""

    @pytest.fixture
    def key_pair(self):
        """Create a test key pair."""
        return create_new_key_pair()

    def test_legacy_handshake_payload_compatibility(self, key_pair):
        """Test that legacy handshake payloads still work."""
        early_data = b"legacy_early_data"

        # Create payload the old way
        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key, id_sig=b"test_sig", early_data=early_data
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should work exactly as before
        assert deserialized.early_data == early_data
        assert deserialized.extensions is None

    def test_legacy_pattern_compatibility(self, key_pair):
        """Test that legacy pattern usage still works."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer,
            libp2p_keypair.private_key,
            noise_keypair.private_key,
            early_data=b"legacy_early_data",
        )

        # Create payload without extensions (legacy way)
        payload = pattern.make_handshake_payload()

        # Should work exactly as before
        assert payload.early_data == b"legacy_early_data"
        assert payload.extensions is None

    def test_mixed_usage_compatibility(self, key_pair):
        """Test mixed usage of legacy and new features."""
        # Test that we can mix legacy early data with new extensions
        early_data = b"legacy_early_data"
        certhashes = [b"cert1", b"cert2"]

        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            early_data=early_data,
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Both should be preserved
        assert deserialized.early_data == early_data
        assert deserialized.extensions is not None
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.extensions.early_data is None
