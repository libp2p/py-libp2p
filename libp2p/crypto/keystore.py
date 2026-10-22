"""
Filesystem keystore for named peer identities.

Provides an opt-in multi-key store backed by protobuf-serialized private keys
on disk (same format as ``libp2p.identity_utils``). Intended for issue #312
style identity persistence without changing default ``new_host`` behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

from libp2p.crypto.ed25519 import create_new_key_pair as create_new_ed25519_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.identity_utils import load_identity, save_identity

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_key_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("Key name must be a non-empty string")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"Invalid key name: {name!r}")
    if not _SAFE_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid key name {name!r}: use letters, digits, '.', '_', or '-'"
        )
    return name


class FileSystemKeyStore:
    """
    Named identity keystore stored as ``{directory}/{name}.key`` files.

    :param directory: Directory that holds key files. Created if missing.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, name: str) -> Path:
        safe = _validate_key_name(name)
        return self.directory / f"{safe}.key"

    def put(self, name: str, key_pair: KeyPair) -> None:
        """
        Store ``key_pair`` under ``name``, overwriting any existing entry.

        :param name: Logical key name (safe path segment).
        :param key_pair: Identity to persist.
        """
        save_identity(key_pair, self._path_for(name))

    def get(self, name: str) -> KeyPair:
        """
        Load the identity stored under ``name``.

        :param name: Logical key name.
        :return: Loaded ``KeyPair``.
        :raises FileNotFoundError: If no key exists for ``name``.
        :raises ValueError: If the stored key is invalid.
        """
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(
                f"No key named {name!r} in keystore {self.directory}"
            )
        return load_identity(path)

    def has(self, name: str) -> bool:
        """Return ``True`` if a key named ``name`` exists."""
        return self._path_for(name).is_file()

    def delete(self, name: str) -> None:
        """
        Remove the key named ``name`` if present.

        :param name: Logical key name.
        :raises FileNotFoundError: If no key exists for ``name``.
        """
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(
                f"No key named {name!r} in keystore {self.directory}"
            )
        path.unlink()

    def list(self) -> list[str]:
        """Return sorted logical names of keys present in the store."""
        names: list[str] = []
        for path in sorted(self.directory.glob("*.key")):
            if path.is_file():
                names.append(path.stem)
        return names


def provider_from_path(path: str | Path) -> Callable[[], KeyPair]:
    """
    Return a key-pair provider that loads an identity from ``path``.

    :param path: Path to a protobuf identity file.
    :return: Callable suitable for ``new_host(key_pair_provider=...)``.
    """
    identity_path = Path(path)

    def _provider() -> KeyPair:
        return load_identity(identity_path)

    return _provider


def provider_from_keystore(
    store: FileSystemKeyStore, name: str = "default"
) -> Callable[[], KeyPair]:
    r"""
    Return a key-pair provider that loads ``name`` from ``store``.

    :param store: Filesystem keystore instance.
    :param name: Key name to load (default ``"default"``).
    :return: Callable suitable for ``new_host(key_pair_provider=...)``.
    """

    def _provider() -> KeyPair:
        return store.get(name)

    return _provider


def provider_new_ed25519() -> Callable[[], KeyPair]:
    """
    Return a key-pair provider that generates a fresh Ed25519 identity.

    :return: Callable suitable for ``new_host(key_pair_provider=...)``.
    """

    def _provider() -> KeyPair:
        return create_new_ed25519_key_pair()

    return _provider
