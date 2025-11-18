"""Tests for early data support through noise extensions (Phase 2)."""

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.messages import NoiseExtensions, NoiseHandshakePayload
from libp2p.security.noise.patterns import PatternXX
from tests.utils.factories import (
    noise_static_key_factory,
    pattern_handshake_factory,
)


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
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]

        ext = NoiseExtensions(
            webtransport_certhashes=certhashes,
            stream_muxers=stream_muxers,
            early_data=early_data,
        )

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Early data should come from extensions
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == early_data
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.extensions.stream_muxers == stream_muxers
        # Early data should be accessible through payload methods
        assert deserialized.has_early_data()
        assert deserialized.get_early_data() == early_data

    def test_handshake_payload_with_stream_muxers_only(self, key_pair):
        """Test handshake payload with only stream muxers (spec compliant)."""
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]

        ext = NoiseExtensions(stream_muxers=stream_muxers)

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should preserve stream muxers
        assert deserialized.extensions is not None
        assert deserialized.extensions.stream_muxers == stream_muxers
        assert deserialized.extensions.webtransport_certhashes == []
        assert deserialized.extensions.early_data is None
        assert not deserialized.has_early_data()

    def test_handshake_payload_with_all_extensions(self, key_pair):
        """Test handshake payload with all extension types."""
        early_data = b"test_early_data"
        certhashes = [b"cert1", b"cert2"]
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]

        ext = NoiseExtensions(
            webtransport_certhashes=certhashes,
            stream_muxers=stream_muxers,
            early_data=early_data,
        )

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # All extensions should be preserved
        assert deserialized.extensions is not None
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.extensions.stream_muxers == stream_muxers
        assert deserialized.extensions.early_data == early_data
        assert deserialized.has_early_data()
        assert deserialized.get_early_data() == early_data


class TestPatternEarlyDataIntegration:
    """Test pattern integration with early data through extensions."""

    @pytest.fixture
    def pattern_setup(self):
        """Set up pattern for testing."""
        libp2p_keypair = create_new_key_pair()
        noise_key = noise_static_key_factory()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer,
            libp2p_keypair.private_key,
            noise_key,
            early_data=b"pattern_early_data",
        )

        return pattern, libp2p_keypair, noise_key

    @pytest.mark.trio
    async def test_pattern_with_extensions_and_early_data(self, pattern_setup, nursery):
        """Test pattern with extensions and early data through real TCP handshake."""
        responder_pattern, libp2p_keypair, noise_key = pattern_setup

        # Create initiator pattern with early data
        initiator_keypair = create_new_key_pair()
        initiator_noise_key = noise_static_key_factory()
        initiator_peer = ID.from_pubkey(initiator_keypair.public_key)
        initiator_pattern = PatternXX(
            local_peer=initiator_peer,
            libp2p_privkey=initiator_keypair.private_key,
            noise_static_key=initiator_noise_key,
            early_data=b"pattern_early_data",
        )

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        # Test payload creation with extensions (unit test aspect)
        payload = initiator_pattern.make_handshake_payload(extensions=ext)

        # Early data should be in extensions
        assert payload.extensions is not None
        assert payload.extensions.early_data == b"pattern_early_data"
        assert payload.extensions.webtransport_certhashes == certhashes
        # Early data should be accessible through payload methods
        assert payload.has_early_data()
        assert payload.get_early_data() == b"pattern_early_data"

        # Perform real handshake to verify early data with extensions works
        async with pattern_handshake_factory(
            nursery, initiator_pattern, responder_pattern
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm handshake completed successfully
            test_data = b"extensions_and_early_data_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

    def test_pattern_with_extensions_without_early_data(self, pattern_setup):
        """Test pattern with extensions but no early data."""
        pattern, libp2p_keypair, noise_key = pattern_setup

        # Create pattern without early data
        libp2p_keypair2 = create_new_key_pair()
        noise_key2 = noise_static_key_factory()
        local_peer2 = ID.from_pubkey(libp2p_keypair2.public_key)

        pattern_no_early = PatternXX(
            local_peer2,
            libp2p_keypair2.private_key,
            noise_key2,
            early_data=None,
        )

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        payload = pattern_no_early.make_handshake_payload(extensions=ext)

        # Should have extensions but no early data
        assert payload.extensions is not None
        assert payload.extensions.early_data is None
        assert payload.extensions.webtransport_certhashes == certhashes
        assert not payload.has_early_data()

    def test_pattern_without_extensions_no_early_data(self, pattern_setup):
        """Test pattern without extensions (no early data)."""
        pattern, libp2p_keypair, noise_key = pattern_setup

        payload = pattern.make_handshake_payload()

        # Should have no early data when no extensions
        assert payload.extensions is None
        assert not payload.has_early_data()

    @pytest.mark.trio
    async def test_pattern_early_data_roundtrip(self, pattern_setup, nursery):
        """Test pattern early data roundtrip through real TCP handshake."""
        responder_pattern, libp2p_keypair, noise_key = pattern_setup

        # Create initiator pattern with early data
        initiator_keypair = create_new_key_pair()
        initiator_noise_key = noise_static_key_factory()
        initiator_peer = ID.from_pubkey(initiator_keypair.public_key)
        initiator_pattern = PatternXX(
            local_peer=initiator_peer,
            libp2p_privkey=initiator_keypair.private_key,
            noise_static_key=initiator_noise_key,
            early_data=b"initiator_pattern_early_data",
        )

        certhashes = [b"cert1", b"cert2"]
        ext = NoiseExtensions(webtransport_certhashes=certhashes)

        # Test serialization roundtrip (unit test aspect)
        payload = initiator_pattern.make_handshake_payload(extensions=ext)

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Early data should be preserved in serialization
        assert deserialized.extensions is not None
        assert deserialized.extensions.early_data == b"initiator_pattern_early_data"
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.has_early_data()
        assert deserialized.get_early_data() == b"initiator_pattern_early_data"

        # Perform real handshake to verify early data works end-to-end
        async with pattern_handshake_factory(
            nursery, initiator_pattern, responder_pattern
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm handshake completed successfully
            test_data = b"early_data_roundtrip_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data


class TestBackwardCompatibility:
    """Test backward compatibility with existing implementations."""

    @pytest.fixture
    def key_pair(self):
        """Create a test key pair."""
        return create_new_key_pair()

    def test_spec_compliant_handshake_payload(self, key_pair):
        """Test that spec-compliant handshake payloads work."""
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]

        # Create payload with spec-compliant extensions
        ext = NoiseExtensions(stream_muxers=stream_muxers)
        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key, id_sig=b"test_sig", extensions=ext
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should preserve spec-compliant extensions
        assert deserialized.extensions is not None
        assert deserialized.extensions.stream_muxers == stream_muxers
        assert not deserialized.has_early_data()

    def test_pattern_with_spec_compliant_extensions(self, key_pair):
        """Test that patterns work with spec-compliant extensions."""
        libp2p_keypair = create_new_key_pair()
        noise_keypair = create_new_key_pair()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer,
            libp2p_keypair.private_key,
            noise_keypair.private_key,
            early_data=None,  # No early data for spec compliance
        )

        # Create payload with spec-compliant extensions
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]
        ext = NoiseExtensions(stream_muxers=stream_muxers)
        payload = pattern.make_handshake_payload(extensions=ext)

        # Should work with spec-compliant extensions
        assert payload.extensions is not None
        assert payload.extensions.stream_muxers == stream_muxers
        assert not payload.has_early_data()

    def test_python_extensions_compatibility(self, key_pair):
        """Test Python-specific extensions work alongside spec compliance."""
        # Test that we can use Python extensions (early data) with spec compliance
        early_data = b"python_early_data"
        certhashes = [b"cert1", b"cert2"]
        stream_muxers = ["/mplex/1.0.0", "/yamux/1.0.0"]

        ext = NoiseExtensions(
            webtransport_certhashes=certhashes,
            stream_muxers=stream_muxers,
            early_data=early_data,
        )

        payload = NoiseHandshakePayload(
            id_pubkey=key_pair.public_key,
            id_sig=b"test_sig",
            extensions=ext,
        )

        # Serialize and deserialize
        serialized = payload.serialize()
        deserialized = NoiseHandshakePayload.deserialize(serialized)

        # Should preserve all extensions
        assert deserialized.extensions is not None
        assert deserialized.extensions.webtransport_certhashes == certhashes
        assert deserialized.extensions.stream_muxers == stream_muxers
        assert deserialized.extensions.early_data == early_data
        assert deserialized.has_early_data()
        assert deserialized.get_early_data() == early_data
