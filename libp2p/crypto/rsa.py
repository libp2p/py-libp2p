import Crypto.PublicKey.RSA as RSA
from Crypto.PublicKey.RSA import RsaKey

from libp2p.crypto.keys import KeyPair, KeyType, PrivateKey, PublicKey


class RSAPublicKey(PublicKey):
    def __init__(self, impl: RsaKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.export_key("DER")

    @classmethod
    def from_bytes(cls, key_bytes: bytes) -> "RSAPublicKey":
        rsakey = RSA.import_key(key_bytes)
        return cls(rsakey)

    def get_type(self) -> KeyType:
        return KeyType.RSA

    def verify(self, data: bytes, signature: bytes) -> bool:
        raise NotImplementedError


class RSAPrivateKey(PrivateKey):
    def __init__(self, impl: RsaKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls, bits: int = 2048, e: int = 65537) -> "RSAPrivateKey":
        private_key_impl = RSA.generate(bits, e=e)
        return cls(private_key_impl)

    def to_bytes(self) -> bytes:
        return self.impl.export_key("DER")

    def get_type(self) -> KeyType:
        return KeyType.RSA

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError

    def get_public_key(self) -> PublicKey:
        return RSAPublicKey(self.impl.publickey())


def create_new_key_pair(bits: int = 2048, e: int = 65537) -> KeyPair:
    """
    Returns a new RSA keypair with the requested key size (``bits``) and the given public
    exponent ``e``. Sane defaults are provided for both values.
    """
    private_key = RSAPrivateKey.new(bits, e)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
