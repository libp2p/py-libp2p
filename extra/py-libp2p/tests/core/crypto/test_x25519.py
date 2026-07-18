import pytest

from libp2p.crypto.keys import (
    KeyType,
)
from libp2p.crypto.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
    create_new_key_pair,
)


def test_x25519_public_key_creation():
    # Create a new X25519 key pair
    key_pair = create_new_key_pair()
    public_key = key_pair.public_key

    # Test that it's an instance of X25519PublicKey
    assert isinstance(public_key, X25519PublicKey)

    # Test key type
    assert public_key.get_type() == KeyType.X25519

    # Test to_bytes and from_bytes roundtrip
    key_bytes = public_key.to_bytes()
    reconstructed_key = X25519PublicKey.from_bytes(key_bytes)
    assert isinstance(reconstructed_key, X25519PublicKey)
    assert reconstructed_key.to_bytes() == key_bytes


def test_x25519_private_key_creation():
    # Create a new private key
    private_key = X25519PrivateKey.new()

    # Test that it's an instance of X25519PrivateKey
    assert isinstance(private_key, X25519PrivateKey)

    # Test key type
    assert private_key.get_type() == KeyType.X25519

    # Test to_bytes and from_bytes roundtrip
    key_bytes = private_key.to_bytes()
    reconstructed_key = X25519PrivateKey.from_bytes(key_bytes)
    assert isinstance(reconstructed_key, X25519PrivateKey)
    assert reconstructed_key.to_bytes() == key_bytes


def test_x25519_key_pair_creation():
    # Create a new key pair
    key_pair = create_new_key_pair()

    # Test that both private and public keys are of correct types
    assert isinstance(key_pair.private_key, X25519PrivateKey)
    assert isinstance(key_pair.public_key, X25519PublicKey)

    # Test that public key matches private key
    assert (
        key_pair.private_key.get_public_key().to_bytes()
        == key_pair.public_key.to_bytes()
    )


def test_x25519_unsupported_operations():
    # Test that signature operations are not supported
    key_pair = create_new_key_pair()

    # Test that public key verify raises NotImplementedError
    with pytest.raises(NotImplementedError, match="X25519 does not support signatures"):
        key_pair.public_key.verify(b"data", b"signature")

    # Test that private key sign raises NotImplementedError
    with pytest.raises(NotImplementedError, match="X25519 does not support signatures"):
        key_pair.private_key.sign(b"data")


def test_x25519_invalid_key_bytes():
    # Test that invalid key bytes raise appropriate exceptions
    with pytest.raises(ValueError, match="An X25519 public key is 32 bytes long"):
        X25519PublicKey.from_bytes(b"invalid_key_bytes")

    with pytest.raises(ValueError, match="An X25519 private key is 32 bytes long"):
        X25519PrivateKey.from_bytes(b"invalid_key_bytes")


def test_x25519_key_serialization():
    # Test key serialization and deserialization
    key_pair = create_new_key_pair()

    # Serialize both keys
    private_bytes = key_pair.private_key.to_bytes()
    public_bytes = key_pair.public_key.to_bytes()

    # Deserialize and verify
    reconstructed_private = X25519PrivateKey.from_bytes(private_bytes)
    reconstructed_public = X25519PublicKey.from_bytes(public_bytes)

    # Verify the reconstructed keys match the original
    assert reconstructed_private.to_bytes() == private_bytes
    assert reconstructed_public.to_bytes() == public_bytes

    # Verify the public key derived from reconstructed private key matches
    assert reconstructed_private.get_public_key().to_bytes() == public_bytes
