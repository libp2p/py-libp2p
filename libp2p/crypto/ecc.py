from typing import cast

from Crypto.PublicKey import ECC
from Crypto.PublicKey.ECC import EccKey

from libp2p.crypto.keys import KeyPair, KeyType, PrivateKey, PublicKey


class ECCPublicKey(PublicKey):
    def __init__(self, impl: EccKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return cast(bytes, self.impl.export_key(format="DER"))

    @classmethod
    def from_bytes(cls, data: bytes) -> "ECCPublicKey":
        public_key_impl = ECC.import_key(data)
        return cls(public_key_impl)

    def get_type(self) -> KeyType:
        return KeyType.ECC_P256

    def verify(self, data: bytes, signature: bytes) -> bool:
        raise NotImplementedError


class ECCPrivateKey(PrivateKey):
    def __init__(self, impl: EccKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls, curve: str) -> "ECCPrivateKey":
        private_key_impl = ECC.generate(curve=curve)
        return cls(private_key_impl)

    def to_bytes(self) -> bytes:
        return cast(bytes, self.impl.export_key(format="DER"))

    def get_type(self) -> KeyType:
        return KeyType.ECC_P256

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError

    def get_public_key(self) -> PublicKey:
        return ECCPublicKey(self.impl.public_key())


def create_new_key_pair(curve: str) -> KeyPair:
    """
    Return a new ECC keypair with the requested ``curve`` type, e.g. "P-256".
    """
    private_key = ECCPrivateKey.new(curve)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
