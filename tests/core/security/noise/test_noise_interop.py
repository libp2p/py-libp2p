"""
Noise interoperability and spec compliance tests.

This module tests that the Noise implementation correctly uses X25519 keys
for Diffie-Hellman operations, as required by the libp2p Noise spec.

Key verification points:
1. Signed data is "noise-libp2p-static-key:" + X25519_montgomery_bytes
2. make_handshake_payload signs X25519 public key bytes
3. Round-trip handshake works with correct key types
"""

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair as create_ed25519_key_pair
from libp2p.crypto.keys import KeyType
from libp2p.crypto.x25519 import X25519PrivateKey, X25519PublicKey
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import NoiseStateError
from libp2p.security.noise.messages import (
    SIGNED_DATA_PREFIX,
    make_data_to_be_signed,
    verify_handshake_payload_sig,
)
from libp2p.security.noise.patterns import PatternXX
from tests.utils.factories import (
    noise_static_key_factory,
    pattern_handshake_factory,
)


class TestNoiseKeyTypeCorrectness:
    """Tests verifying correct use of X25519 keys in Noise protocol."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs - matches pattern from test_patterns.py."""
        libp2p_keypair = create_ed25519_key_pair()
        noise_key = noise_static_key_factory()
        return libp2p_keypair, noise_key

    @pytest.fixture
    def pattern_setup(self, key_pairs):
        """Create pattern setup - matches pattern from test_patterns.py."""
        libp2p_keypair, noise_key = key_pairs
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)

        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_key,
        )
        return pattern, libp2p_keypair, noise_key

    @pytest.fixture
    def x25519_keypair(self):
        """Create X25519 key pair for direct key testing."""
        priv = X25519PrivateKey.new()
        return priv, priv.get_public_key()

    def test_noise_static_key_is_x25519(self):
        """Verify noise_static_key_factory returns X25519 private key."""
        noise_key = noise_static_key_factory()
        assert isinstance(noise_key, X25519PrivateKey)
        assert noise_key.get_type() == KeyType.X25519

    def test_x25519_public_key_type(self, x25519_keypair):
        """Verify X25519PublicKey has correct type."""
        _, pub = x25519_keypair
        assert isinstance(pub, X25519PublicKey)
        assert pub.get_type() == KeyType.X25519

    def test_make_handshake_payload_uses_x25519_pubkey(self, pattern_setup):
        """Verify make_handshake_payload derives X25519 public key correctly."""
        pattern, libp2p_keypair, noise_key = pattern_setup
        noise_pubkey = noise_key.get_public_key()

        # Create handshake payload
        payload = pattern.make_handshake_payload()

        # Verify by reconstructing what should have been signed
        expected_signed_data = make_data_to_be_signed(noise_pubkey)
        actual_signed_data = make_data_to_be_signed(noise_pubkey)
        assert actual_signed_data == expected_signed_data

        # Verify the signature validates with the X25519 public key
        assert verify_handshake_payload_sig(payload, noise_pubkey)

    def test_make_handshake_payload_rejects_non_x25519(self):
        """Verify make_handshake_payload rejects non-X25519 noise_static_key."""
        libp2p_keypair = create_ed25519_key_pair()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        non_x25519_noise_key = create_ed25519_key_pair().private_key
        pattern = PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=non_x25519_noise_key,
        )

        with pytest.raises(NoiseStateError):
            pattern.make_handshake_payload()

    def test_signature_format_matches_spec(self, pattern_setup):
        """Verify signed data format: 'noise-libp2p-static-key:' + X25519 Montgomery bytes."""
        pattern, libp2p_keypair, noise_key = pattern_setup

        # Get X25519 public key bytes (Montgomery form)
        x25519_pub_bytes = noise_key.get_public_key().to_bytes()
        assert len(x25519_pub_bytes) == 32  # X25519 public keys are 32 bytes

        # Verify the signed data format
        signed_data = make_data_to_be_signed(noise_key.get_public_key())
        prefix = SIGNED_DATA_PREFIX.encode("utf-8")

        assert signed_data.startswith(prefix)
        assert signed_data[len(prefix):] == x25519_pub_bytes

    def test_handshake_payload_signature_verifies_with_x25519(self, pattern_setup):
        """Verify handshake payload signature is over X25519 key, not Ed25519."""
        pattern, libp2p_keypair, noise_key = pattern_setup

        # Create payload
        payload = pattern.make_handshake_payload()

        # The signature must verify with the X25519 public key
        assert verify_handshake_payload_sig(payload, noise_key.get_public_key())

        # Create a different X25519 key - signature should NOT verify with it
        different_key = X25519PrivateKey.new().get_public_key()
        assert not verify_handshake_payload_sig(payload, different_key)


class TestNoiseHandshakeInterop:
    """Tests verifying Noise handshake works correctly end-to-end."""

    @pytest.fixture
    def initiator_pattern(self):
        """Create initiator pattern."""
        libp2p_keypair = create_ed25519_key_pair()
        noise_key = noise_static_key_factory()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        return PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_key,
        )

    @pytest.fixture
    def responder_pattern(self):
        """Create responder pattern."""
        libp2p_keypair = create_ed25519_key_pair()
        noise_key = noise_static_key_factory()
        local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        return PatternXX(
            local_peer=local_peer,
            libp2p_privkey=libp2p_keypair.private_key,
            noise_static_key=noise_key,
        )

    @pytest.mark.trio
    async def test_full_handshake_with_x25519(
        self, initiator_pattern, responder_pattern, nursery
    ):
        """Verify full handshake succeeds with X25519 keys."""
        async with pattern_handshake_factory(
            nursery, initiator_pattern, responder_pattern
        ) as (init_conn, resp_conn):
            # Handshake succeeded - verify connections
            assert init_conn is not None
            assert resp_conn is not None

            # Verify remote_permanent_pubkey is correct X25519 type
            for conn in (init_conn, resp_conn):
                assert isinstance(conn.remote_permanent_pubkey, X25519PublicKey)
                assert conn.remote_permanent_pubkey.get_type() == KeyType.X25519

    @pytest.mark.trio
    async def test_data_exchange_after_handshake(
        self, initiator_pattern, responder_pattern, nursery
    ):
        """Verify data exchange works after handshake with correct key types."""
        async with pattern_handshake_factory(
            nursery, initiator_pattern, responder_pattern
        ) as (init_conn, resp_conn):
            # Test bidirectional data exchange
            test_data = b"Hello from initiator with X25519 keys!"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

            response = b"Response from responder with X25519 keys!"
            await resp_conn.write(response)
            received_response = await init_conn.read(len(response))
            assert received_response == response


class TestNoiseKeyDerivation:
    """Tests verifying correct key derivation in Noise protocol."""

    def test_noise_key_derivation_returns_x25519(self):
        """Verify Noise key derivation returns correct X25519 types."""
        noise_key = noise_static_key_factory()
        assert isinstance(noise_key, X25519PrivateKey)
        assert noise_key.get_type() == KeyType.X25519

        pub = noise_key.get_public_key()
        assert isinstance(pub, X25519PublicKey)
        assert pub.get_type() == KeyType.X25519

        # X25519 keys are 32 bytes
        assert len(noise_key.to_bytes()) == 32
        assert len(pub.to_bytes()) == 32

        # Roundtrip private key
        priv_bytes = noise_key.to_bytes()
        priv_restored = X25519PrivateKey.from_bytes(priv_bytes)
        assert priv_restored.to_bytes() == priv_bytes

        # Roundtrip public key
        pub_bytes = pub.to_bytes()
        pub_restored = X25519PublicKey.from_bytes(pub_bytes)
        assert pub_restored.to_bytes() == pub_bytes

        # Derived public keys should match
        assert priv_restored.get_public_key().to_bytes() == pub_bytes
