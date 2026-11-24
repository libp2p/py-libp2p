from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)


def infer_local_type(curve: str) -> ec.EllipticCurve:
    """
    Convert a str representation of some elliptic curve to a
    representation understood by the backend of this module.
    """
    if curve != "P-256":
        raise NotImplementedError("Only P-256 curve is supported")
    return ec.SECP256R1()


class ECCPublicKey(PublicKey):
    def __init__(
        self, impl: ec.EllipticCurvePublicKey, curve: ec.EllipticCurve
    ) -> None:
        self.impl = impl
        self.curve = curve

    def to_bytes(self) -> bytes:
        return self.impl.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    @classmethod
    def from_bytes(cls, data: bytes, curve: str) -> "ECCPublicKey":
        curve_type = infer_local_type(curve)
        impl = ec.EllipticCurvePublicKey.from_encoded_point(curve_type, data)
        return cls(impl, curve_type)

    def get_type(self) -> KeyType:
        return KeyType.ECC_P256

    def verify(self, data: bytes, signature: bytes) -> bool:
        raise NotImplementedError()


class ECCPrivateKey(PrivateKey):
    def __init__(
        self, impl: ec.EllipticCurvePrivateKey, curve: ec.EllipticCurve
    ) -> None:
        self.impl = impl
        self.curve = curve

    @classmethod
    def new(cls, curve: str) -> "ECCPrivateKey":
        curve_type = infer_local_type(curve)
        return cls(ec.generate_private_key(curve_type), curve_type)

    def to_bytes(self) -> bytes:
        return self.impl.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )

    def get_type(self) -> KeyType:
        return KeyType.ECC_P256

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError()

    def get_public_key(self) -> PublicKey:
        return ECCPublicKey(self.impl.public_key(), self.curve)


def create_new_key_pair(curve: str) -> KeyPair:
    """
    Return a new ECC keypair with the requested curve type, e.g.
    "P-256".
    """
    private_key = ECCPrivateKey.new(curve)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
