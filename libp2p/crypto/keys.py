from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, unique

from .pb import crypto_pb2 as protobuf


@unique
class KeyType(Enum):
    RSA = 0
    Ed25519 = 1
    Secp256k1 = 2
    ECDSA = 3


class Key(ABC):
    """
    A ``Key`` represents a cryptographic key.
    """

    @abstractmethod
    def to_bytes(self) -> bytes:
        """
        Returns the byte representation of this key.
        """
        ...

    @abstractmethod
    def get_type(self) -> KeyType:
        """
        Returns the ``KeyType`` for ``self``.
        """
        ...


class PublicKey(Key):
    """
    A ``PublicKey`` represents a cryptographic public key.
    """

    @abstractmethod
    def verify(self, data: bytes, signature: bytes) -> bool:
        """
        Verify that ``signature`` is the cryptographic signature of the hash of ``data``.
        """
        ...

    def serialize_to_protobuf(self) -> protobuf.PublicKey:
        _type = self.get_type()
        data = self.to_bytes()
        protobuf_key = protobuf.PublicKey()
        protobuf_key.key_type = _type.value
        protobuf_key.data = data
        return protobuf_key


class PrivateKey(Key):
    """
    A ``PrivateKey`` represents a cryptographic private key.
    """

    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        ...

    @abstractmethod
    def get_public_key(self) -> PublicKey:
        ...

    def serialize_to_protobuf(self) -> protobuf.PrivateKey:
        _type = self.get_type()
        data = self.to_bytes()
        protobuf_key = protobuf.PrivateKey()
        protobuf_key.key_type = _type.value
        protobuf_key.data = data
        return protobuf_key


@dataclass(frozen=True)
class KeyPair:
    private_key: PrivateKey
    public_key: PublicKey
