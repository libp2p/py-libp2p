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

    _id_str: bytes

    def __init__(self, id_str: bytes) -> None:
        self._id_str = id_str

    def to_bytes(self) -> bytes:
        return self._id_str

    def get_raw_id(self) -> bytes:
        return self._id_str

    def pretty(self) -> str:
        return base58.b58encode(self._id_str).decode()

    def get_xor_id(self) -> int:
        return int(digest(self.get_raw_id()).hex(), 16)

    def __str__(self) -> str:
        pid = self.pretty()
        return pid

    __repr__ = __str__

    def __eq__(self, other: object) -> bool:
        # pylint: disable=protected-access
        if not isinstance(other, ID):
            return NotImplemented
        return self._id_str == other._id_str

    def __hash__(self) -> int:
        return hash(self._id_str)


def id_b58_encode(peer_id: ID) -> str:
    """
    return a b58-encoded string
    """
    # pylint: disable=protected-access
    return base58.b58encode(peer_id.get_raw_id()).decode()


def id_b58_decode(peer_id_str: str) -> ID:
    """
    return a base58-decoded peer ID
    """
    return ID(base58.b58decode(peer_id_str))


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
