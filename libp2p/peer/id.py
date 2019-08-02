import hashlib
from typing import Union

import base58

import multihash


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
    def from_pubkey(cls, key: bytes) -> "ID":
        algo = multihash.Func.sha2_256
        mh_digest = multihash.digest(key, algo)
        return cls(mh_digest.encode())


def digest(data: Union[str, bytes]) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf8")
    return hashlib.sha1(data).digest()
