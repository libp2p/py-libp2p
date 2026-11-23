import sys

from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)

if sys.platform != "win32":
    import inspect
    from typing import Any

    from fastecdsa import (
        curve as curve_types,
        keys,
        point,
    )
    from fastecdsa.encoding.sec1 import SEC1Encoder

    _SEC1_ENCODER: Any
    if "self" in inspect.signature(SEC1Encoder.encode_public_key).parameters:
        _SEC1_ENCODER = SEC1Encoder()
    else:
        _SEC1_ENCODER = SEC1Encoder

    _PEM_ENCODER: Any
    try:
        from fastecdsa.encoding.pem import PEMEncoder as _PEM_ENCODER
    except ImportError:
        _PEM_ENCODER = None
else:
    from coincurve import (
        PrivateKey as CPrivateKey,
        PublicKey as CPublicKey,
    )


if sys.platform != "win32":

    def infer_local_type(curve: str) -> curve_types.Curve:
        """
        Convert a str representation of some elliptic curve to a
        representation understood by the backend of this module.
        """
        if curve != "P-256":
            raise NotImplementedError("Only P-256 curve is supported")
        return curve_types.P256
else:

    def infer_local_type(curve: str) -> str:
        """
        Convert a str representation of some elliptic curve to a
        representation understood by the backend of this module.
        """
        if curve != "P-256":
            raise NotImplementedError("Only P-256 curve is supported")
        return "P-256"  # coincurve only supports P-256


if sys.platform != "win32":

    class ECCPublicKey(PublicKey):
        def __init__(self, impl: point.Point, curve: curve_types.Curve) -> None:
            self.impl = impl
            self.curve = curve

        def to_bytes(self) -> bytes:
            return _SEC1_ENCODER.encode_public_key(self.impl, compressed=False)

        @classmethod
        def from_bytes(cls, data: bytes, curve: str) -> "ECCPublicKey":
            curve_type = infer_local_type(curve)
            public_key_impl = _SEC1_ENCODER.decode_public_key(data, curve_type)
            return cls(public_key_impl, curve_type)

        def get_type(self) -> KeyType:
            return KeyType.ECC_P256

        def verify(self, data: bytes, signature: bytes) -> bool:
            raise NotImplementedError()

    class ECCPrivateKey(PrivateKey):
        def __init__(self, impl: int, curve: curve_types.Curve) -> None:
            self.impl = impl
            self.curve = curve

        @classmethod
        def new(cls, curve: str) -> "ECCPrivateKey":
            curve_type = infer_local_type(curve)
            private_key_impl = keys.gen_private_key(curve_type)
            return cls(private_key_impl, curve_type)

        def to_bytes(self) -> bytes:
            export_key = getattr(keys, "export_key", None)
            if export_key is not None:
                key_str = export_key(
                    self.impl, self.curve, encoder=getattr(keys, "PEMEncoder")
                )
                if key_str is None:
                    raise Exception("Key not found")
                return key_str.encode()
            if _PEM_ENCODER is None:
                raise RuntimeError("fastecdsa PEMEncoder is unavailable")
            return _PEM_ENCODER().encode_private_key(self.impl, self.curve)

        def get_type(self) -> KeyType:
            return KeyType.ECC_P256

        def sign(self, data: bytes) -> bytes:
            raise NotImplementedError()

        def get_public_key(self) -> PublicKey:
            public_key_impl = keys.get_public_key(self.impl, self.curve)
            return ECCPublicKey(public_key_impl, self.curve)

else:

    class ECCPublicKey(PublicKey):
        def __init__(self, impl: CPublicKey, curve: str) -> None:
            self.impl = impl
            self.curve = curve

        def to_bytes(self) -> bytes:
            return self.impl.format(compressed=False)

        @classmethod
        def from_bytes(cls, data: bytes, curve: str) -> "ECCPublicKey":
            curve_type = infer_local_type(curve)
            return cls(CPublicKey(data), curve_type)  # type: ignore[arg-type]

        def get_type(self) -> KeyType:
            return KeyType.ECC_P256

        def verify(self, data: bytes, signature: bytes) -> bool:
            raise NotImplementedError()

    class ECCPrivateKey(PrivateKey):
        def __init__(self, impl: CPrivateKey, curve: str) -> None:
            self.impl = impl
            self.curve = curve

        @classmethod
        def new(cls, curve: str) -> "ECCPrivateKey":
            curve_type = infer_local_type(curve)
            return cls(CPrivateKey(), curve_type)  # type: ignore[arg-type]

        def to_bytes(self) -> bytes:
            return self.impl.secret

        def get_type(self) -> KeyType:
            return KeyType.ECC_P256

        def sign(self, data: bytes) -> bytes:
            raise NotImplementedError()

        def get_public_key(self) -> PublicKey:
            return ECCPublicKey(self.impl.public_key, self.curve)


def create_new_key_pair(curve: str) -> KeyPair:
    """
    Return a new ECC keypair with the requested curve type, e.g.
    "P-256".
    """
    private_key = ECCPrivateKey.new(curve)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
