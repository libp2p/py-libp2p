from cryptography.exceptions import (
    InvalidSignature,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey as CryptoEd25519PrivateKey,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey as CryptoEd25519PublicKey,
)

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)


class Ed25519PublicKey(PublicKey):
    def __init__(self, impl: CryptoEd25519PublicKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.public_bytes_raw()

    @classmethod
    def from_bytes(cls, key_bytes: bytes) -> "Ed25519PublicKey":
        return cls(CryptoEd25519PublicKey.from_public_bytes(key_bytes))

    def get_type(self) -> KeyType:
        return KeyType.Ed25519

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self.impl.verify(signature, data)
            return True
        except InvalidSignature:
            return False


class Ed25519PrivateKey(PrivateKey):
    def __init__(self, impl: CryptoEd25519PrivateKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls, seed: bytes = None) -> "Ed25519PrivateKey":
        if not seed:
            return cls(CryptoEd25519PrivateKey.generate())
        return cls(CryptoEd25519PrivateKey.from_private_bytes(seed[:32]))

    def to_bytes(self) -> bytes:
        return self.impl.private_bytes_raw()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Ed25519PrivateKey":
        return cls(CryptoEd25519PrivateKey.from_private_bytes(data))

    def get_type(self) -> KeyType:
        return KeyType.Ed25519

    def sign(self, data: bytes) -> bytes:
        return self.impl.sign(data)

    def get_public_key(self) -> PublicKey:
        return Ed25519PublicKey(self.impl.public_key())


def create_new_key_pair(seed: bytes = None) -> KeyPair:
    private_key = Ed25519PrivateKey.new(seed)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
