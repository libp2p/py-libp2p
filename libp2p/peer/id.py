import functools
import hashlib

import base58
import multibase
import multihash

from libp2p.crypto.keys import (
    PublicKey,
)
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.encoding_config import get_default_encoding

# NOTE: On inlining...
# See: https://github.com/libp2p/specs/issues/138
# NOTE: enabling to be interoperable w/ the Go implementation
ENABLE_INLINING = True
MAX_INLINE_KEY_LENGTH = 42

IDENTITY_MULTIHASH_CODE = 0x00

if ENABLE_INLINING:

    class IdentityHash:
        _digest: bytes

        def __init__(self) -> None:
            self._digest = b""

        def update(self, input: bytes) -> None:
            self._digest += input

        def digest(self) -> bytes:
            return self._digest

    # Register identity hash function if FuncReg is available
    if hasattr(multihash, "FuncReg"):
        multihash.FuncReg.register(
            IDENTITY_MULTIHASH_CODE, "identity", hash_new=lambda: IdentityHash()
        )


class ID:
    _bytes: bytes

    def __init__(self, peer_id_bytes: bytes) -> None:
        self._bytes = peer_id_bytes

    @functools.cached_property
    def xor_id(self) -> int:
        return int(sha256_digest(self._bytes).hex(), 16)

    @functools.cached_property
    def base58(self) -> str:
        return base58.b58encode(self._bytes).decode()

    def to_bytes(self) -> bytes:
        return self._bytes

    def to_base58(self) -> str:
        return self.base58

    def to_multibase(self, encoding: str | None = None) -> str:
        """
        Return multibase-encoded peer ID.

        Parameters
        ----------
        encoding : str | None
            Multibase encoding to use.  When *None* (the default) the
            process-wide default from :mod:`libp2p.encoding_config` is
            used.

        """
        if encoding is None:
            encoding = get_default_encoding()
        return multibase.encode(encoding, self._bytes).decode()

    @classmethod
    def from_multibase(cls, multibase_str: str) -> "ID":
        """
        Parse a peer ID from a multibase-encoded string.

        Parameters
        ----------
        multibase_str : str
            A multibase-encoded string (e.g. ``"zQm…"`` for base58btc,
            ``"bafz…"`` for base32).

        Raises
        ------
        multibase.InvalidMultibaseStringError
            If *multibase_str* is not a valid multibase-encoded string.
        multibase.DecodingError
            If the multibase prefix is recognised but the payload cannot
            be decoded.

        """
        if not multibase.is_encoded(multibase_str):
            raise multibase.InvalidMultibaseStringError(
                f"Not a valid multibase string: {multibase_str!r}"
            )
        try:
            result = multibase.decode(multibase_str)
            # py-multibase may return ``bytes`` or ``(encoding, bytes)``
            # depending on version — handle both.
            peer_id_bytes = result[1] if isinstance(result, tuple) else result
            return cls(peer_id_bytes)
        except (multibase.InvalidMultibaseStringError, multibase.DecodingError):
            raise
        except Exception as e:
            raise multibase.DecodingError(
                f"Failed to decode multibase peer ID: {e}"
            ) from e

    @classmethod
    def from_string(cls, peer_id_str: str) -> "ID":
        """
        Decode a peer ID string that may be multibase or base58.

        Follows the same logic as go-libp2p's ``peer.Decode()``:

        * Strings starting with ``"Qm"`` or ``"1"`` are treated as legacy
          base58-encoded peer IDs (SHA-256 and identity multihashes
          respectively).
        * Everything else is tried as multibase first.  If multibase
          decoding succeeds **and** the result is a valid multihash the
          peer ID is returned.  Otherwise we fall back to base58.

        Parameters
        ----------
        peer_id_str : str
            A peer ID encoded as either a multibase string or a legacy
            base58 string.

        Raises
        ------
        ValueError
            If *peer_id_str* cannot be decoded as either multibase or
            base58.

        """
        # Legacy base58: "Qm" = SHA-256 multihash, "1" = identity multihash.
        if peer_id_str.startswith("Qm") or peer_id_str.startswith("1"):
            try:
                return cls.from_base58(peer_id_str)
            except Exception as e:
                raise ValueError(
                    f"Failed to decode peer ID {peer_id_str!r} as base58: {e}"
                ) from e

        if multibase.is_encoded(peer_id_str):
            try:
                pid = cls.from_multibase(peer_id_str)
                multihash.decode(pid._bytes)
                return pid
            except (
                multibase.InvalidMultibaseStringError,
                multibase.DecodingError,
                ValueError,
            ):
                pass  # fall through to base58

        # Fallback to base58.
        try:
            return cls.from_base58(peer_id_str)
        except Exception as e:
            raise ValueError(
                f"Failed to decode peer ID {peer_id_str!r}: not valid "
                f"multibase or base58: {e}"
            ) from e

    def __repr__(self) -> str:
        return f"<libp2p.peer.id.ID ({self!s})>"

    __str__ = pretty = to_string = to_base58

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.to_base58() == other
        elif isinstance(other, bytes):
            return self._bytes == other
        elif isinstance(other, ID):
            return self._bytes == other._bytes
        else:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self._bytes)

    @classmethod
    def from_base58(cls, b58_encoded_peer_id_str: str) -> "ID":
        peer_id_bytes = base58.b58decode(b58_encoded_peer_id_str)
        pid = ID(peer_id_bytes)
        return pid

    @classmethod
    def from_pubkey(cls, key: PublicKey) -> "ID":
        serialized_key = key.serialize()
        algo = multihash.Func.sha2_256
        if ENABLE_INLINING and len(serialized_key) <= MAX_INLINE_KEY_LENGTH:
            algo = IDENTITY_MULTIHASH_CODE
        mh_digest = multihash.digest(serialized_key, algo)
        return cls(mh_digest.encode())

    def extract_public_key(self) -> PublicKey | None:
        """
        Extract the public key from this peer ID if it uses an identity multihash.

        For Ed25519 and other small keys, the public key is embedded directly
        in the peer ID using an identity multihash. For larger keys like RSA,
        the peer ID uses a SHA-256 hash and the key cannot be extracted.

        Returns:
            The public key if it can be extracted, None otherwise.

        """
        try:
            mh_decoded = multihash.decode(self._bytes)
            if mh_decoded.func == IDENTITY_MULTIHASH_CODE:
                return deserialize_public_key(mh_decoded.digest)
            return None
        except Exception:
            return None


def sha256_digest(data: str | bytes) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf8")
    return hashlib.sha256(data).digest()
