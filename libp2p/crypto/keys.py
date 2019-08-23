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
    ECC_P256 = 4


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

    def __eq__(self, other: "Key") -> bool:
        return self.impl == other.impl


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

    @classmethod
    def deserialize_from_protobuf(cls, protobuf_data: bytes) -> protobuf.PublicKey:
        protobuf_key = protobuf.PublicKey()
        protobuf_key.ParseFromString(protobuf_data)
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

    def _protobuf_from_serialization(self, data: bytes) -> protobuf.PrivateKey:
        """
        Return the protobuf representation of this ``Key``.
        """
        key_type = self.get_type().value
        data = self.to_bytes()
        protobuf_key = protobuf.PrivateKey(key_type=key_type, data=data)
        return protobuf_key

    @classmethod
    def deserialize_from_protobuf(cls, protobuf_data: bytes) -> protobuf.PrivateKey:
        protobuf_key = protobuf.PrivateKey()
        protobuf_key.ParseFromString(protobuf_data)
        return protobuf_key


@dataclass(frozen=True)
class KeyPair:
    private_key: PrivateKey
    public_key: PublicKey
