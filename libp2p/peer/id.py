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
        """
        Create a deterministic peer ID from a public key.

        This method generates a peer ID by hashing the serialized public key.
        The same public key will ALWAYS produce the same peer ID, which is
        fundamental for identity persistence in libp2p.

        For small keys (≤42 bytes, like Ed25519), the key is embedded directly
        in the peer ID using an identity multihash. For larger keys (like RSA),
        a SHA-256 hash is used.

        :param key: The public key to generate a peer ID from
        :return: A deterministic peer ID derived from the public key

        Example:
            >>> from libp2p.crypto.ed25519 import create_new_key_pair
            >>> from libp2p.peer.id import ID
            >>> kp1 = create_new_key_pair()
            >>> kp2 = create_new_key_pair()
            >>> # Same keypair produces same peer ID
            >>> ID.from_pubkey(kp1.public_key) == ID.from_pubkey(kp1.public_key)
            True
            >>> # Different keypairs produce different peer IDs
            >>> ID.from_pubkey(kp1.public_key) == ID.from_pubkey(kp2.public_key)
            False

        """
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
