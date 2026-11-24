from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)

# The order of the secp256k1 group.
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

# Sign with deterministic nonces (RFC 6979), as libsecp256k1 does, unless the
# OpenSSL which cryptography uses lacks them.
try:
    ECDSA_SHA256 = ec.ECDSA(hashes.SHA256(), deterministic_signing=True)
except UnsupportedAlgorithm:  # pragma: no cover - depends on the OpenSSL build
    ECDSA_SHA256 = ec.ECDSA(hashes.SHA256())


class Secp256k1PublicKey(PublicKey):
    def __init__(self, impl: ec.EllipticCurvePublicKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Secp256k1PublicKey":
        impl = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), data)
        return cls(impl)

    @classmethod
    def deserialize(cls, data: bytes) -> "Secp256k1PublicKey":
        protobuf_key = cls.deserialize_from_protobuf(data)
        return cls.from_bytes(protobuf_key.data)

    def get_type(self) -> KeyType:
        return KeyType.Secp256k1

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            _, s = decode_dss_signature(signature)
        except ValueError:
            return False

        # Like libsecp256k1, only accept the low-S form, so that signatures
        # cannot be altered while remaining valid.
        if s > SECP256K1_ORDER // 2:
            return False

        try:
            self.impl.verify(signature, data, ECDSA_SHA256)
        except InvalidSignature:
            return False
        return True


class Secp256k1PrivateKey(PrivateKey):
    def __init__(self, impl: ec.EllipticCurvePrivateKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls, secret: bytes | None = None) -> "Secp256k1PrivateKey":
        if secret is None:
            return cls(ec.generate_private_key(ec.SECP256K1()))
        return cls.from_bytes(secret)

    def to_bytes(self) -> bytes:
        return self.impl.private_numbers().private_value.to_bytes(32, "big")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Secp256k1PrivateKey":
        impl = ec.derive_private_key(int.from_bytes(data, "big"), ec.SECP256K1())
        return cls(impl)

    @classmethod
    def deserialize(cls, data: bytes) -> "Secp256k1PrivateKey":
        protobuf_key = cls.deserialize_from_protobuf(data)
        return cls.from_bytes(protobuf_key.data)

    def get_type(self) -> KeyType:
        return KeyType.Secp256k1

    def sign(self, data: bytes) -> bytes:
        r, s = decode_dss_signature(self.impl.sign(data, ECDSA_SHA256))

        # Produce the low-S form, which libsecp256k1 requires.
        return encode_dss_signature(r, min(s, SECP256K1_ORDER - s))

    def get_public_key(self) -> PublicKey:
        return Secp256k1PublicKey(self.impl.public_key())


def create_new_key_pair(secret: bytes | None = None) -> KeyPair:
    """
    Returns a new Secp256k1 keypair derived from the provided ``secret``, a
    sequence of bytes corresponding to some integer between 0 and the group
    order.

    A valid secret is created if ``None`` is passed.
    """
    private_key = Secp256k1PrivateKey.new(secret)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
