"""
Ed25519 cryptographic key implementation.

This module provides Ed25519 public and private key implementations using
the PyNaCl library. Ed25519 is used for libp2p peer identity signatures.
"""

from nacl.exceptions import (
    BadSignatureError,
)
from nacl.signing import (
    SigningKey as PrivateKeyImpl,
    VerifyKey as PublicKeyImpl,
)

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)


class Ed25519PublicKey(PublicKey):
    """
    Ed25519 public key implementation.

    Provides cryptographic operations for Ed25519 public keys including
    signature verification. Used for libp2p peer identity verification.
    """

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
        try:
            self.impl.verify(data, signature)
        except BadSignatureError:
            return False
        return True


class Ed25519PrivateKey(PrivateKey):
    """
    Ed25519 private key implementation.

    Provides cryptographic operations for Ed25519 private keys including
    signature generation and public key derivation. Used for libp2p peer
    identity signing.
    """

    def __init__(self, impl: PrivateKeyImpl) -> None:
        self.impl = impl

    @classmethod
    def new(cls, seed: bytes | None = None) -> "Ed25519PrivateKey":
        if seed:
            private_key_impl = PrivateKeyImpl(seed)
        else:
            private_key_impl = PrivateKeyImpl.generate()
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
        signed = self.impl.sign(data)
        return signed.signature

    def get_public_key(self) -> PublicKey:
        return Ed25519PublicKey(self.impl.verify_key)


def create_new_key_pair(seed: bytes | None = None) -> KeyPair:
    private_key = Ed25519PrivateKey.new(seed)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
