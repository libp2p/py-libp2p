"""
Identity persistence utilities for py-libp2p.

This module provides helper functions for saving, loading, and creating
peer identities. These utilities enable opt-in identity persistence without
changing the default behavior of generating random identities.

Example usage:
    >>> from libp2p.identity_utils import save_identity, load_identity
    >>> from libp2p.crypto.ed25519 import create_new_key_pair
    >>>
    >>> # Create and save an identity
    >>> key_pair = create_new_key_pair()
    >>> save_identity(key_pair, "my_peer.key")
    >>>
    >>> # Load it later
    >>> loaded_key_pair = load_identity("my_peer.key")
"""

import os
from pathlib import Path

from libp2p.crypto.ed25519 import create_new_key_pair as create_new_ed25519_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.serialization import deserialize_private_key


def save_identity(key_pair: KeyPair, filepath: str | Path) -> None:
    """
    Save a keypair to disk for later reuse.

    The private key is serialized using protobuf format and saved to the
    specified file with restrictive permissions (0600). The file is created
    atomically with the correct permissions to prevent security race conditions.

    Args:
        key_pair: The KeyPair to save
        filepath: Path where the private key will be saved

    Raises:
        OSError: If the file cannot be written

    Example:
        >>> from libp2p.crypto.ed25519 import create_new_key_pair
        >>> key_pair = create_new_key_pair()
        >>> save_identity(key_pair, "my_peer_identity.key")

    """
    filepath = Path(filepath)

    # Create parent directories if they don't exist
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Serialize the private key to protobuf format
    # This uses the standardized libp2p protobuf format for interoperability
    private_key_bytes = key_pair.private_key.serialize()

    # Create file with 0600 permissions atomically to prevent race condition
    # where another process could read the file between write and chmod
    fd = os.open(filepath, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, private_key_bytes)
    finally:
        os.close(fd)


def load_identity(filepath: str | Path) -> KeyPair:
    """
    Load a keypair from disk.

    Reads a previously saved private key (in protobuf format) and reconstructs
    the full keypair. Supports Ed25519, RSA, and Secp256k1 keys.

    Args:
        filepath: Path to the saved private key file

    Returns:
        KeyPair loaded from the file

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file contains invalid or corrupted key data

    Example:
        >>> key_pair = load_identity("my_peer_identity.key")
        >>> from libp2p import new_host
        >>> host = new_host(key_pair=key_pair)

    """
    filepath = Path(filepath)

    # Read the private key bytes
    private_key_bytes = filepath.read_bytes()

    # Deserialize from protobuf format with validation
    try:
        private_key = deserialize_private_key(private_key_bytes)
    except Exception as e:
        raise ValueError(
            f"Invalid or corrupted private key file '{filepath}': {e}"
        ) from e

    # Verify the key is valid by deriving the public key
    try:
        public_key = private_key.get_public_key()
        # Additional validation: verify roundtrip serialization works
        _ = public_key.serialize()
    except Exception as e:
        raise ValueError(f"Corrupted private key in file '{filepath}': {e}") from e

    return KeyPair(private_key, public_key)


def create_identity_from_seed(seed: bytes) -> KeyPair:
    """
    Create a deterministic identity from a seed.

    The same seed will always produce the same keypair and peer ID.
    This is useful for testing or when you want a deterministic identity
    without saving keys to disk.

    Args:
        seed: A 32-byte seed for key generation. Must be exactly 32 bytes.

    Returns:
        KeyPair generated deterministically from the seed

    Raises:
        ValueError: If the seed is not 32 bytes or produces an invalid key

    Example:
        >>> seed = b"my_secret_seed_32_bytes_long!!!!"
        >>> key_pair = create_identity_from_seed(seed)
        >>> from libp2p import new_host
        >>> host = new_host(key_pair=key_pair)
        >>> # Same seed always produces same peer ID
        >>> print(host.get_id())

    """
    if len(seed) != 32:
        raise ValueError(
            f"Seed must be exactly 32 bytes, got {len(seed)} bytes. "
            "Consider using hashlib.sha256(your_seed).digest() "
            "to derive a 32-byte seed."
        )

    return create_new_ed25519_key_pair(seed=seed)


def identity_exists(filepath: str | Path) -> bool:
    """
    Check if an identity file exists at the given path.

    Args:
        filepath: Path to check for an existing identity file

    Returns:
        True if the file exists, False otherwise

    Example:
        >>> if identity_exists("my_peer.key"):
        ...     key_pair = load_identity("my_peer.key")
        ... else:
        ...     key_pair = create_new_key_pair()
        ...     save_identity(key_pair, "my_peer.key")

    """
    return Path(filepath).exists()
