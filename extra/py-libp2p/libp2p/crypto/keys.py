"""Key types and interfaces."""

from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import (
    dataclass,
)
from enum import (
    Enum,
    unique,
)
from typing import (
    cast,
)

from libp2p.crypto.pb import (
    crypto_pb2,
)


@unique
class KeyType(Enum):
    RSA = crypto_pb2.KeyType.RSA
    Ed25519 = crypto_pb2.KeyType.Ed25519
    Secp256k1 = crypto_pb2.KeyType.Secp256k1
    ECDSA = crypto_pb2.KeyType.ECDSA
    ECC_P256 = crypto_pb2.KeyType.ECC_P256
    # X25519 is added for Noise protocol
    X25519 = cast(crypto_pb2.KeyType.ValueType, 5)


class Key(ABC):
    """A ``Key`` represents a cryptographic key."""

    @abstractmethod
    def to_bytes(self) -> bytes:
        """Returns the byte representation of this key."""
        ...

    @abstractmethod
    def get_type(self) -> KeyType:
        """Returns the ``KeyType`` for ``self``."""
        ...

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Key):
            return NotImplemented
        return self.to_bytes() == other.to_bytes()


class PublicKey(Key):
    """A ``PublicKey`` represents a cryptographic public key."""

    @abstractmethod
    def verify(self, data: bytes, signature: bytes) -> bool:
        """
        Verify that ``signature`` is the cryptographic signature of the hash
        of ``data``.
        """
        ...

    def _serialize_to_protobuf(self) -> crypto_pb2.PublicKey:
        """Return the protobuf representation of this ``Key``."""
        key_type = self.get_type().value
        data = self.to_bytes()
        protobuf_key = crypto_pb2.PublicKey(key_type=key_type, data=data)
        return protobuf_key

    def serialize(self) -> bytes:
        """Return the canonical serialization of this ``Key``."""
        return self._serialize_to_protobuf().SerializeToString()

    @classmethod
    def deserialize_from_protobuf(cls, protobuf_data: bytes) -> crypto_pb2.PublicKey:
        return crypto_pb2.PublicKey.FromString(protobuf_data)


class PrivateKey(Key):
    """A ``PrivateKey`` represents a cryptographic private key."""

    @abstractmethod
    def sign(self, data: bytes) -> bytes: ...

    @abstractmethod
    def get_public_key(self) -> PublicKey: ...

    def _serialize_to_protobuf(self) -> crypto_pb2.PrivateKey:
        """Return the protobuf representation of this ``Key``."""
        key_type = self.get_type().value
        data = self.to_bytes()
        protobuf_key = crypto_pb2.PrivateKey(key_type=key_type, data=data)
        return protobuf_key

    def serialize(self) -> bytes:
        """Return the canonical serialization of this ``Key``."""
        return self._serialize_to_protobuf().SerializeToString()

    @classmethod
    def deserialize_from_protobuf(cls, protobuf_data: bytes) -> crypto_pb2.PrivateKey:
        return crypto_pb2.PrivateKey.FromString(protobuf_data)


@dataclass(frozen=True)
class KeyPair:
    private_key: PrivateKey
    public_key: PublicKey
