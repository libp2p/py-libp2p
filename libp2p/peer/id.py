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
        """Parse from multibase-encoded string."""
        if not multibase.is_encoded(multibase_str):
            # For test compatibility: raise InvalidMultibaseStringError if not multibase
            raise multibase.InvalidMultibaseStringError("Not a multibase string")
        try:
            peer_id_bytes = multibase.decode(multibase_str)
            return cls(peer_id_bytes)
        except (multibase.InvalidMultibaseStringError, multibase.DecodingError):
            raise
        except Exception as e:
            raise multibase.DecodingError(
                f"Failed to decode multibase data: {e}"
            ) from e

    @classmethod
    def from_string(cls, peer_id_str: str) -> "ID":
        """Smart parser that tries multibase first, then base58."""
        if multibase.is_encoded(peer_id_str):
            try:
                return cls.from_multibase(peer_id_str)
            except (multibase.InvalidMultibaseStringError, multibase.DecodingError):
                # Fallback to base58 for backward compatibility
                return cls.from_base58(peer_id_str)
        else:
            # Assume base58 for backward compatibility
            return cls.from_base58(peer_id_str)

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
            # Decode the multihash to check if it's an identity hash
            mh_decoded = multihash.decode(self._bytes)

            # Identity multihash func code is 0x00
            if mh_decoded.func == IDENTITY_MULTIHASH_CODE:
                # The digest is the serialized public key protobuf
                return deserialize_public_key(mh_decoded.digest)
            else:
                # Not an identity hash, key cannot be extracted
                return None
        except Exception:
            return None


def sha256_digest(data: str | bytes) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf8")
    return hashlib.sha256(data).digest()
