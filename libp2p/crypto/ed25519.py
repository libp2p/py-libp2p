from Crypto.Hash import (
    SHA256,
)
from nacl.exceptions import (
    BadSignatureError,
)
from nacl.public import (
    PrivateKey as PrivateKeyImpl,
    PublicKey as PublicKeyImpl,
)
from nacl.signing import (
    SigningKey,
    VerifyKey,
)
import nacl.utils as utils

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)


class Ed25519PublicKey(PublicKey):
    def __init__(self, impl: PublicKeyImpl) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return bytes(self.impl)

    @classmethod
    def from_bytes(cls, key_bytes: bytes) -> "Ed25519PublicKey":
        return cls(PublicKeyImpl(key_bytes))

    def get_type(self) -> KeyType:
        return KeyType.Ed25519

    def verify(self, data: bytes, signature: bytes) -> bool:
        verify_key = VerifyKey(self.to_bytes())
        try:
            verify_key.verify(data, signature)
        except BadSignatureError:
            return False
        return True


class Ed25519PrivateKey(PrivateKey):
    def __init__(self, impl: PrivateKeyImpl) -> None:
        self.impl = impl

    @classmethod
    def new(cls, seed: bytes | None = None) -> "Ed25519PrivateKey":
        if not seed:
            seed = utils.random()

        private_key_impl = PrivateKeyImpl.from_seed(seed)
        return cls(private_key_impl)

    def to_bytes(self) -> bytes:
        return bytes(self.impl)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Ed25519PrivateKey":
        impl = PrivateKeyImpl(data)
        return cls(impl)

    def get_type(self) -> KeyType:
        return KeyType.Ed25519

    def sign(self, data: bytes) -> bytes:
        h = SHA256.new(data)
        signing_key = SigningKey(self.to_bytes())
        return signing_key.sign(h.digest())

    def get_public_key(self) -> PublicKey:
        return Ed25519PublicKey(self.impl.public_key)


def create_new_key_pair(seed: bytes | None = None) -> KeyPair:
    private_key = Ed25519PrivateKey.new(seed)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
