import hashlib
from typing import Union

import base58

import multihash

from Crypto.PublicKey.RSA import RsaKey

# MaxInlineKeyLength is the maximum length a key can be for it to be inlined in
# the peer ID.
# * When `len(pubKey.Bytes()) <= MaxInlineKeyLength`, the peer ID is the
#   identity multihash hash of the public key.
# * When `len(pubKey.Bytes()) > MaxInlineKeyLength`, the peer ID is the
#   sha2-256 multihash of the public key.
MAX_INLINE_KEY_LENGTH = 42


class ID:

    _bytes: bytes
    _xor_id: int = None
    _b58_str: str = None

    def __init__(self, peer_id_bytes: bytes) -> None:
        self._bytes = peer_id_bytes

    @property
    def xor_id(self) -> int:
        if not self._xor_id:
            self._xor_id = int(digest(self._bytes).hex(), 16)
        return self._xor_id

    def to_bytes(self) -> bytes:
        return self._bytes

    def to_base58(self) -> str:
        if not self._b58_str:
            self._b58_str = base58.b58encode(self._bytes).decode()
        return self._b58_str

    def __bytes__(self) -> bytes:
        return self._bytes

    __repr__ = __str__ = pretty = to_string = to_base58

    def __eq__(self, other: object) -> bool:
        # pylint: disable=protected-access, no-else-return
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
    def from_pubkey(cls, key: RsaKey) -> "ID":
        # export into binary format
        key_bin = key.exportKey("DER")

        algo: int = multihash.Func.sha2_256
        # TODO: seems identity is not yet supported in pymultihash
        # if len(b) <= MAX_INLINE_KEY_LENGTH:
        #     algo multihash.func.identity

        mh_digest: multihash.Multihash = multihash.digest(key_bin, algo)
        return cls(mh_digest.encode())

    @classmethod
    def from_privkey(cls, key: RsaKey) -> "ID":
        return cls.from_pubkey(key.publickey())


def id_b58_encode(peer_id: ID) -> str:
    """
    return a b58-encoded string
    """
    # pylint: disable=protected-access
    return base58.b58encode(peer_id.to_bytes()).decode()


def id_b58_decode(b58_encoded_peer_id_str: str) -> ID:
    """
    return a base58-decoded peer ID
    """
    return ID(base58.b58decode(b58_encoded_peer_id_str))


def id_from_public_key(key: RsaKey) -> ID:
    # export into binary format
    key_bin = key.exportKey("DER")

    algo: int = multihash.Func.sha2_256
    # TODO: seems identity is not yet supported in pymultihash
    # if len(b) <= MAX_INLINE_KEY_LENGTH:
    #     algo multihash.func.identity

    mh_digest: multihash.Multihash = multihash.digest(key_bin, algo)
    return ID(mh_digest.encode())


def id_from_private_key(key: RsaKey) -> ID:
    return id_from_public_key(key.publickey())


def digest(data: Union[str, bytes]) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf8")
    return hashlib.sha1(data).digest()
