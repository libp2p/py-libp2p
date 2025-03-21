import pytest

from libp2p.crypto.exceptions import (
    CryptographyError,
)
from libp2p.crypto.rsa import (
    MAX_RSA_KEY_SIZE,
    RSAPrivateKey,
    validate_rsa_key_size,
)


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
