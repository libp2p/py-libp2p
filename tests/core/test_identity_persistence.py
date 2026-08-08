"""
Tests for identity persistence functionality.

These tests verify that peer identity can be persisted and reused across
sessions, enabling stable peer IDs without changing default behavior.
"""

from pathlib import Path
import tempfile

import pytest

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.identity_utils import (
    create_identity_from_seed,
    identity_exists,
    load_identity,
    save_identity,
)
from libp2p.peer.id import ID


def test_same_keypair_produces_same_peer_id():
    """
    Test that reusing the same keypair produces the same peer ID.

    This is fundamental for identity persistence - if we save and reload
    a keypair, we should get the same peer ID.
    """
    # Create a keypair
    key_pair = create_new_key_pair()

    # Generate peer IDs from the same keypair
    peer_id_1 = ID.from_pubkey(key_pair.public_key)
    peer_id_2 = ID.from_pubkey(key_pair.public_key)

    # They should be identical
    assert peer_id_1 == peer_id_2
    assert str(peer_id_1) == str(peer_id_2)


def test_no_keypair_produces_different_peer_ids():
    """
    Test that default behavior generates unique peer IDs.

    This ensures we haven't broken the default random identity generation.
    """
    # Create two different keypairs
    key_pair_1 = create_new_key_pair()
    key_pair_2 = create_new_key_pair()

    # Generate peer IDs
    peer_id_1 = ID.from_pubkey(key_pair_1.public_key)
    peer_id_2 = ID.from_pubkey(key_pair_2.public_key)

    # They should be different
    assert peer_id_1 != peer_id_2
    assert str(peer_id_1) != str(peer_id_2)


def test_identity_from_seed_is_deterministic():
    """
    Test that the same seed produces the same identity.

    This enables deterministic identity generation without file I/O.
    """
    seed = b"my_test_seed_is_32bytes_long!!!!"  # Exactly 32 bytes

    # Create two identities from the same seed
    key_pair_1 = create_identity_from_seed(seed)
    key_pair_2 = create_identity_from_seed(seed)

    # Private keys should be identical
    assert key_pair_1.private_key.to_bytes() == key_pair_2.private_key.to_bytes()

    # Public keys should be identical
    assert key_pair_1.public_key.to_bytes() == key_pair_2.public_key.to_bytes()

    # Peer IDs should be identical
    peer_id_1 = ID.from_pubkey(key_pair_1.public_key)
    peer_id_2 = ID.from_pubkey(key_pair_2.public_key)
    assert peer_id_1 == peer_id_2


def test_different_seeds_produce_different_identities():
    """Test that different seeds produce different identities."""
    seed_1 = b"seed_one_is_32_bytes_long!!!!!!!"
    seed_2 = b"seed_two_is_32_bytes_long!!!!!!!"

    key_pair_1 = create_identity_from_seed(seed_1)
    key_pair_2 = create_identity_from_seed(seed_2)

    # Keys should be different
    assert key_pair_1.private_key.to_bytes() != key_pair_2.private_key.to_bytes()
    assert key_pair_1.public_key.to_bytes() != key_pair_2.public_key.to_bytes()

    # Peer IDs should be different
    peer_id_1 = ID.from_pubkey(key_pair_1.public_key)
    peer_id_2 = ID.from_pubkey(key_pair_2.public_key)
    assert peer_id_1 != peer_id_2


def test_seed_must_be_32_bytes():
    """Test that create_identity_from_seed validates seed length."""
    # Too short
    with pytest.raises(ValueError, match="must be exactly 32 bytes"):
        create_identity_from_seed(b"too_short")

    # Too long
    with pytest.raises(ValueError, match="must be exactly 32 bytes"):
        create_identity_from_seed(
            b"this_seed_is_way_too_long_for_ed25519_key_generation"
        )


def test_save_and_load_identity():
    """
    Test saving and loading identity from disk.

    This is the primary use case for identity persistence.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_identity.key"

        # Create and save an identity
        original_key_pair = create_new_key_pair()
        save_identity(original_key_pair, filepath)

        # Verify file was created
        assert filepath.exists()

        # Load the identity
        loaded_key_pair = load_identity(filepath)

        # Verify the loaded keypair matches the original
        assert (
            loaded_key_pair.private_key.to_bytes()
            == original_key_pair.private_key.to_bytes()
        )
        assert (
            loaded_key_pair.public_key.to_bytes()
            == original_key_pair.public_key.to_bytes()
        )

        # Verify peer IDs match
        original_peer_id = ID.from_pubkey(original_key_pair.public_key)
        loaded_peer_id = ID.from_pubkey(loaded_key_pair.public_key)
        assert original_peer_id == loaded_peer_id


def test_save_identity_with_string_path():
    """Test that save_identity accepts string paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = f"{tmpdir}/test_identity.key"  # String, not Path

        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)

        assert Path(filepath).exists()


def test_load_identity_with_string_path():
    """Test that load_identity accepts string paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = f"{tmpdir}/test_identity.key"  # String, not Path

        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)

        loaded_key_pair = load_identity(filepath)
        assert loaded_key_pair.private_key.to_bytes() == key_pair.private_key.to_bytes()


def test_load_nonexistent_identity_raises_error():
    """Test that loading a nonexistent identity raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_identity("/nonexistent/path/to/identity.key")


def test_identity_exists():
    """Test the identity_exists helper function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_identity.key"

        # File doesn't exist yet
        assert not identity_exists(filepath)

        # Create and save identity
        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)

        # Now it exists
        assert identity_exists(filepath)


def test_identity_exists_with_string_path():
    """Test that identity_exists accepts string paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = f"{tmpdir}/test_identity.key"

        assert not identity_exists(filepath)

        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)

        assert identity_exists(filepath)


@pytest.mark.trio
async def test_host_with_saved_identity():
    """
    Test creating a host with a saved identity.

    This is an integration test showing the complete workflow.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "peer_identity.key"

        # Create and save identity
        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)
        original_peer_id = ID.from_pubkey(key_pair.public_key)

        # Load identity and create host
        loaded_key_pair = load_identity(filepath)
        host = new_host(key_pair=loaded_key_pair)

        # Verify the host has the same peer ID
        assert host.get_id() == original_peer_id


@pytest.mark.trio
async def test_host_with_seed_identity():
    """
    Test creating a host with a deterministic seed-based identity.

    This shows how to use seed-based identity for testing or deterministic setups.
    """
    seed = b"test_seed_32_bytes_long!!!!!!!!!"

    # Create two hosts with the same seed
    key_pair_1 = create_identity_from_seed(seed)
    key_pair_2 = create_identity_from_seed(seed)

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)

    # They should have the same peer ID
    assert host_1.get_id() == host_2.get_id()


@pytest.mark.trio
async def test_default_host_generates_random_identity():
    """
    Test that default behavior still generates random identities.

    This ensures backward compatibility - we haven't broken existing behavior.
    """
    host_1 = new_host()
    host_2 = new_host()

    # Different hosts should have different peer IDs
    assert host_1.get_id() != host_2.get_id()
