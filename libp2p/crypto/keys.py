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

    def _serialize_to_protobuf(self) -> protobuf.PublicKey:
        """
        Return the protobuf representation of this ``Key``.
        """
        key_type = self.get_type().value
        data = self.to_bytes()
        protobuf_key = protobuf.PublicKey(key_type=key_type, data=data)
        return protobuf_key

    def serialize(self) -> bytes:
        """
        Return the canonical serialization of this ``Key``.
        """
        return self._serialize_to_protobuf().SerializeToString()


class PrivateKey(Key):
    """
    A ``PrivateKey`` represents a cryptographic private key.
    """

    protobuf_constructor = protobuf.PrivateKey

    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        ...

    @abstractmethod
    def get_public_key(self) -> PublicKey:
        ...

    def _serialize_to_protobuf(self) -> protobuf.PrivateKey:
        """
        Return the protobuf representation of this ``Key``.
        """
        key_type = self.get_type().value
        data = self.to_bytes()
        protobuf_key = protobuf.PrivateKey(key_type=key_type, data=data)
        return protobuf_key

    def serialize(self) -> bytes:
        """
        Return the canonical serialization of this ``Key``.
        """
        return self._serialize_to_protobuf().SerializeToString()


@dataclass(frozen=True)
class KeyPair:
    private_key: PrivateKey
    public_key: PublicKey
