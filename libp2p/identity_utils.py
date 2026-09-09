"""
Identity persistence utilities for py-libp2p.

This module provides helper functions for saving, loading, and creating
peer identities. These utilities enable opt-in identity persistence without
changing the default behavior of generating random identities.

On Unix-like systems, identity files are written with mode ``0600`` (owner
read/write only), including when overwriting an existing file. On Windows,
POSIX modes are not enforced; rely on the process user's default NTFS ACLs
(or OS features such as EFS) for access control.
"""

from __future__ import annotations

import os
from pathlib import Path

from libp2p.crypto.ed25519 import create_new_key_pair as create_new_ed25519_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.serialization import deserialize_private_key


def _write_private_key_bytes(filepath: Path, data: bytes) -> None:
    """
    Write private-key bytes to ``filepath`` with restrictive permissions.

    On Unix-like systems the file mode is forced to ``0600`` on both create and
    overwrite via ``os.fchmod``. On Windows, mode bits are not applied.

    :param filepath: Destination path for the private key bytes.
    :param data: Serialized private key bytes to write.
    :raises OSError: If the file cannot be written.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(filepath, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        if os.name != "nt":
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
        os.write(fd, data)
    finally:
        os.close(fd)


def save_identity(key_pair: KeyPair, filepath: str | Path) -> None:
    """
    Save a keypair to disk for later reuse.

    The private key is serialized using the libp2p protobuf format and written
    to the specified file. On Unix-like systems the file mode is ``0600``
    (including on overwrite). On Windows, POSIX modes are not enforced.

    :param key_pair: The ``KeyPair`` to save.
    :param filepath: Path where the private key will be saved.
    :raises OSError: If the file cannot be written.

    Example::

        >>> from libp2p.crypto.ed25519 import create_new_key_pair
        >>> key_pair = create_new_key_pair()
        >>> save_identity(key_pair, "my_peer_identity.key")
    """
    filepath = Path(filepath)
    private_key_bytes = key_pair.private_key.serialize()
    _write_private_key_bytes(filepath, private_key_bytes)


def load_identity(filepath: str | Path) -> KeyPair:
    """
    Load a keypair from disk.

    Reads a previously saved private key (in protobuf format) and reconstructs
    the full keypair. Supports Ed25519, RSA, and Secp256k1 keys.

    :param filepath: Path to the saved private key file.
    :return: ``KeyPair`` loaded from the file.
    :raises FileNotFoundError: If the file does not exist.
    :raises ValueError: If the file contains invalid or corrupted key data.

    Example::

        >>> key_pair = load_identity("my_peer_identity.key")
        >>> from libp2p import new_host
        >>> host = new_host(key_pair=key_pair)
    """
    filepath = Path(filepath)
    private_key_bytes = filepath.read_bytes()

    try:
        private_key = deserialize_private_key(private_key_bytes)
    except Exception as e:
        raise ValueError(
            f"Invalid or corrupted private key file '{filepath}': {e}"
        ) from e

    try:
        public_key = private_key.get_public_key()
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

    :param seed: A 32-byte seed for key generation. Must be exactly 32 bytes.
    :return: ``KeyPair`` generated deterministically from the seed.
    :raises ValueError: If the seed is not 32 bytes or produces an invalid key.

    Example::

        >>> seed = b"my_secret_seed_32_bytes_long!!!!"
        >>> key_pair = create_identity_from_seed(seed)
        >>> from libp2p import new_host
        >>> host = new_host(key_pair=key_pair)
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

    :param filepath: Path to check for an existing identity file.
    :return: ``True`` if the file exists, ``False`` otherwise.

    Example::

        >>> if identity_exists("my_peer.key"):
        ...     key_pair = load_identity("my_peer.key")
        ... else:
        ...     from libp2p.crypto.ed25519 import create_new_key_pair
        ...     key_pair = create_new_key_pair()
        ...     save_identity(key_pair, "my_peer.key")
    """
    return Path(filepath).exists()
