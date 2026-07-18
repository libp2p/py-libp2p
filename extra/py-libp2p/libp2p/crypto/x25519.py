from cryptography.hazmat.primitives import (
    serialization,
)
from cryptography.hazmat.primitives.asymmetric import (
    x25519,
)

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)


class X25519PublicKey(PublicKey):
    def __init__(self, impl: x25519.X25519PublicKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "X25519PublicKey":
        return cls(x25519.X25519PublicKey.from_public_bytes(data))

    def get_type(self) -> KeyType:
        # Not in protobuf, but for Noise use only
        return KeyType.X25519  # Or define KeyType.X25519 if you want to extend

    def verify(self, data: bytes, signature: bytes) -> bool:
        raise NotImplementedError("X25519 does not support signatures.")


class X25519PrivateKey(PrivateKey):
    def __init__(self, impl: x25519.X25519PrivateKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls) -> "X25519PrivateKey":
        return cls(x25519.X25519PrivateKey.generate())

    def to_bytes(self) -> bytes:
        return self.impl.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "X25519PrivateKey":
        return cls(x25519.X25519PrivateKey.from_private_bytes(data))

    def get_type(self) -> KeyType:
        return KeyType.X25519

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError("X25519 does not support signatures.")

    def get_public_key(self) -> PublicKey:
        return X25519PublicKey(self.impl.public_key())


def create_new_key_pair() -> KeyPair:
    priv = X25519PrivateKey.new()
    pub = priv.get_public_key()
    return KeyPair(priv, pub)
