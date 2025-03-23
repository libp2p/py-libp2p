from Crypto.Hash import (
    SHA256,
)
import Crypto.PublicKey.RSA as RSA
from Crypto.PublicKey.RSA import (
    RsaKey,
)
from Crypto.Signature import (
    pkcs1_15,
)

from libp2p.crypto.exceptions import (
    CryptographyError,
)
from libp2p.crypto.keys import (
    KeyPair,
    KeyType,
    PrivateKey,
    PublicKey,
)

MAX_RSA_KEY_SIZE = 4096


def validate_rsa_key_length(key_length: int) -> None:
    """
    Validate that the RSA key length is positive and within the allowed maximum.

    :param key_length: RSA key size in bits.
    :raises CryptographyError:
        If the key size is not positive or exceeds MAX_RSA_KEY_SIZE.
    """
    if key_length <= 0:
        raise CryptographyError("RSA key size must be positive")
    if key_length > MAX_RSA_KEY_SIZE:
        raise CryptographyError(
            f"RSA key size {key_length} exceeds maximum allowed size {MAX_RSA_KEY_SIZE}"
        )


def validate_rsa_key_size(key: RsaKey) -> None:
    """
    Validate that an RSA key's size is within acceptable bounds.

    :param key: The RSA key to validate.
    :raises CryptographyError: If the key size is invalid.
    """
    key_size = key.size_in_bits()
    validate_rsa_key_length(key_size)


class RSAPublicKey(PublicKey):
    def __init__(self, impl: RsaKey) -> None:
        validate_rsa_key_size(impl)
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.export_key("DER")

    @classmethod
    def from_bytes(cls, key_bytes: bytes) -> "RSAPublicKey":
        rsakey = RSA.import_key(key_bytes)
        validate_rsa_key_size(rsakey)
        return cls(rsakey)

    def get_type(self) -> KeyType:
        return KeyType.RSA

    def verify(self, data: bytes, signature: bytes) -> bool:
        h = SHA256.new(data)
        try:
            pkcs1_15.new(self.impl).verify(h, signature)
        except (ValueError, TypeError):
            return False
        return True


class RSAPrivateKey(PrivateKey):
    def __init__(self, impl: RsaKey) -> None:
        validate_rsa_key_size(impl)
        self.impl = impl

    @classmethod
    def new(cls, bits: int = 2048, e: int = 65537) -> "RSAPrivateKey":
        validate_rsa_key_length(bits)
        private_key_impl = RSA.generate(bits, e=e)
        return cls(private_key_impl)

    def to_bytes(self) -> bytes:
        return self.impl.export_key("DER")

    def get_type(self) -> KeyType:
        return KeyType.RSA

    def sign(self, data: bytes) -> bytes:
        h = SHA256.new(data)
        return pkcs1_15.new(self.impl).sign(h)

    def get_public_key(self) -> PublicKey:
        return RSAPublicKey(self.impl.publickey())


def create_new_key_pair(bits: int = 2048, e: int = 65537) -> KeyPair:
    """
    Returns a new RSA keypair with the requested key size (``bits``) and the
    given public exponent ``e``.

    Sane defaults are provided for both values.
    """
    private_key = RSAPrivateKey.new(bits, e)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
