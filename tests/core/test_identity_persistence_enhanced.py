"""
Additional tests for identity persistence - addressing PR review feedback.

These tests cover edge cases and security requirements:
- File permissions verification
- Corrupted file handling
- RSA key support (via protobuf)
- File overwrite behavior
"""

import os
import stat
import tempfile
from pathlib import Path

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.identity_utils import load_identity, save_identity


def test_save_identity_sets_restrictive_permissions():
    """
    Verify that saved identity files have restrictive permissions (0600).
    
    This is a security requirement to prevent other users from reading
    the private key file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_identity.key"
        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)
        
        # Check file permissions (Unix-like systems only)
        if os.name != "nt":  # Skip on Windows
            mode = filepath.stat().st_mode
            # Should be 0600 (owner read/write only)
            actual_mode = stat.S_IMODE(mode)
            assert actual_mode == 0o600, (
                f"Expected permissions 0600, got {oct(actual_mode)}"
            )


def test_load_corrupted_identity_raises_error():
    """
    Verify that loading a corrupted identity file raises ValueError.
    
    This ensures we don't silently accept invalid key data.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "corrupted.key"
        # Write invalid data
        filepath.write_bytes(b"not a valid private key")
        
        with pytest.raises(ValueError, match="Invalid or corrupted"):
            load_identity(filepath)


def test_load_truncated_file_raises_error():
    """
    Verify that loading a truncated file raises ValueError.
    
    Truncated files could result from interrupted writes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "truncated.key"
        # Write only a few bytes (truncated protobuf)
        filepath.write_bytes(b"\x00\x01\x02")
        
        with pytest.raises(ValueError, match="Invalid or corrupted"):
            load_identity(filepath)


def test_load_empty_file_raises_error():
    """
    Verify that loading an empty file raises ValueError.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "empty.key"
        # Write empty file
        filepath.write_bytes(b"")
        
        with pytest.raises(ValueError, match="Invalid or corrupted"):
            load_identity(filepath)


def test_save_and_load_rsa_identity():
    """
    Test that saving to an existing file overwrites it correctly.
    
    This ensures we can update identity files without errors.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "identity.key"
        
        # Save first identity
        key_pair_1 = create_new_key_pair()
        save_identity(key_pair_1, filepath)
        
        # Overwrite with second identity
        key_pair_2 = create_new_key_pair()
        save_identity(key_pair_2, filepath)
        
        # Load and verify it's the second identity
        loaded_key_pair = load_identity(filepath)
        assert (
            loaded_key_pair.private_key.to_bytes()
            == key_pair_2.private_key.to_bytes()
        )
        assert (
            loaded_key_pair.private_key.to_bytes()
            != key_pair_1.private_key.to_bytes()
        )


def test_save_identity_creates_parent_directories():
    """
    Test that save_identity creates parent directories if they don't exist.
    
    This prevents FileNotFoundError when saving to nested paths.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Use a nested path that doesn't exist
        filepath = Path(tmpdir) / "nested" / "dir" / "identity.key"
        
        # Parent directories don't exist yet
        assert not filepath.parent.exists()
        
        # Save should create them
        key_pair = create_new_key_pair()
        save_identity(key_pair, filepath)
        
        # Verify file was created
        assert filepath.exists()
        assert filepath.parent.exists()
        
        # Verify we can load it
        loaded_key_pair = load_identity(filepath)
        assert (
            loaded_key_pair.private_key.to_bytes()
            == key_pair.private_key.to_bytes()
        )
