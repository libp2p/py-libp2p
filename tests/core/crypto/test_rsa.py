import pytest

from libp2p.crypto.exceptions import (
    CryptographyError,
)
from libp2p.crypto.rsa import (
    MAX_RSA_KEY_SIZE,
    RSAPrivateKey,
    create_new_key_pair,
    validate_rsa_key_size,
)
from libp2p.crypto.serialization import deserialize_private_key


def test_validate_rsa_key_size():
    # Test valid key size
    key = RSAPrivateKey.new(2048)
    validate_rsa_key_size(key.impl)

    # Test key size too large
    with pytest.raises(
        CryptographyError, match=f".*exceeds maximum allowed size {MAX_RSA_KEY_SIZE}"
    ):
        RSAPrivateKey.new(MAX_RSA_KEY_SIZE + 1)

    # Test negative key size (this would be caught when creating the key)
    with pytest.raises(CryptographyError, match="RSA key size must be positive"):
        RSAPrivateKey.new(-1)

    # Test zero key size
    with pytest.raises(CryptographyError, match="RSA key size must be positive"):
        RSAPrivateKey.new(0)


def test_rsa_private_key_from_bytes_roundtrip() -> None:
    original = RSAPrivateKey.new(2048)
    restored = RSAPrivateKey.from_bytes(original.to_bytes())
    assert restored.to_bytes() == original.to_bytes()
    assert restored.get_public_key().to_bytes() == original.get_public_key().to_bytes()


def test_rsa_protobuf_serialize_deserialize_roundtrip() -> None:
    key_pair = create_new_key_pair(bits=2048)
    restored = deserialize_private_key(key_pair.private_key.serialize())
    assert restored.to_bytes() == key_pair.private_key.to_bytes()
    assert restored.get_public_key().to_bytes() == key_pair.public_key.to_bytes()


def test_rsa_private_key_from_bytes_rejects_public_key() -> None:
    key_pair = create_new_key_pair(bits=2048)
    with pytest.raises(ValueError, match="private key"):
        RSAPrivateKey.from_bytes(key_pair.public_key.to_bytes())
