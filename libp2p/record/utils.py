from typing import Tuple

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.keys import PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.rsa import RSAPublicKey
from libp2p.crypto.secp256k1 import Secp256k1PublicKey


def split_key(key: str) -> Tuple[str, str]:
    """
    Split a key into (namespace, remainder).
    Example: "ns/foo" -> ("ns", "foo").
    Replace with the real implementation as needed.
    """
    if "/" not in key:
        raise ValueError("invalid key format")
    ns, rest = key.split("/", 1)
    return ns, rest

def unmarshal_public_key(data: bytes) -> PublicKey:
    """
    Deserialize a public key from its serialized byte representation.
    This function takes a byte sequence representing a serialized public key
    and reconstructs the corresponding `PublicKey` object based on its type.

    Args:
        data (bytes): The serialized byte representation of the public key.

    Returns:
        PublicKey: The deserialized public key object.

    Raises:
        ValueError: If the key type is unsupported or unrecognized.
    Supported Key Types:
        - RSA
        - Ed25519
        - Secp256k1

    """
    proto_key = crypto_pb2.PublicKey.FromString(data)
    key_type = proto_key.key_type
    key_data = proto_key.data

    if key_type == crypto_pb2.KeyType.RSA:
        return RSAPublicKey.from_bytes(key_data)
    elif key_type == crypto_pb2.KeyType.Ed25519:
        return Ed25519PublicKey.from_bytes(key_data)
    elif key_type == crypto_pb2.KeyType.Secp256k1:
        return Secp256k1PublicKey.from_bytes(key_data)
    else:
        raise ValueError(f"Unsupported key type: {key_type}")
