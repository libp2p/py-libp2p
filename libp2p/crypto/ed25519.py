from Crypto.Hash import SHA256

from libp2p.crypto.keys import KeyType, PublicKey
from nacl.public import PublicKey as Ed255129PublicKeyImpl
from nacl.signing import BadSignatureError, VerifyKey


class Ed25519PublicKey(PublicKey):
    def __init__(self, impl: Ed255129PublicKeyImpl) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return bytes(self.impl)

    @classmethod
    def from_bytes(cls, key_bytes: bytes) -> "Ed25519PublicKey":
        return cls(Ed255129PublicKeyImpl(key_bytes))

    def get_type(self) -> KeyType:
        return KeyType.Ed25519

    def verify(self, data: bytes, signature: bytes) -> bool:
        verify_key = VerifyKey(self.to_bytes())
        h = SHA256.new(data)
        try:
            verify_key.verify(h, signature)
        except BadSignatureError:
            return False
        return True
