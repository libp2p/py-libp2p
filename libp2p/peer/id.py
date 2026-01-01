import functools
import hashlib

import base58
import multihash

from libp2p.crypto.keys import (
    PublicKey,
)
from libp2p.crypto.serialization import deserialize_public_key

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

    # Note: FuncReg is not available in pymultihash 0.8.2
    # Identity hash is handled manually in from_pubkey method


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
        # Use identity hash (no hashing) for small keys, otherwise use SHA2-256
        if ENABLE_INLINING and len(serialized_key) <= MAX_INLINE_KEY_LENGTH:
            # Identity multihash: just encode the key directly with code 0x00
            mh_bytes = multihash.encode(serialized_key, IDENTITY_MULTIHASH_CODE)
        else:
            # SHA2-256: hash first, then encode
            digest = hashlib.sha256(serialized_key).digest()
            mh_bytes = multihash.encode(digest, "sha2-256")
        return cls(mh_bytes)

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
