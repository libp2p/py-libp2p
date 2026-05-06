from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.rsa import RSAPublicKey
from libp2p.crypto.secp256k1 import Secp256k1PublicKey


class InvalidRecordType(Exception):
    pass


def _unmarshal_public_key(data: bytes) -> PublicKey:
    """
    Deserialize a ``crypto_pb2.PublicKey`` protobuf into a concrete
    ``PublicKey`` instance.

    Kept private to this module to avoid the circular import that arises
    when importing from ``libp2p.records.pubkey`` (which itself imports
    from this module).
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


def sign_record(
    private_key: PrivateKey, key: bytes, value: bytes
) -> tuple[bytes, bytes]:
    """
    Sign a DHT record using the given private key.

    The signature is computed over "libp2p-record:" + key + value.

    Args:
        private_key: The private key to sign with
        key: The record key
        value: The record value

    Returns:
        tuple[bytes, bytes]: A tuple of (signature, author_public_key_bytes)

    """
    signing_payload = b"libp2p-record:" + key + value
    signature = private_key.sign(signing_payload)
    public_key = private_key.get_public_key()
    # Serialize as a protobuf-wrapped PublicKey so that verify_record (and
    # remote peers) can reconstruct the key without knowing its type in advance.
    author_bytes = public_key.serialize()
    return signature, author_bytes


def verify_record(
    signature: bytes, author_public_key: bytes, key: bytes, value: bytes
) -> bool:
    """
    Verify a signed DHT record.

    Supports all key types that libp2p serialises in a protobuf PublicKey
    envelope (Ed25519, RSA, Secp256k1).  The author field is treated as a
    serialised ``crypto_pb2.PublicKey`` message and dispatched through
    ``unmarshal_public_key`` so that non-Ed25519 peers are not silently
    rejected.

    Args:
        signature: The record signature
        author_public_key: The serialized public key of the author
            (``crypto_pb2.PublicKey`` protobuf bytes)
        key: The record key
        value: The record value

    Returns:
        bool: True if the signature is valid, False otherwise

    """
    try:
        public_key = _unmarshal_public_key(author_public_key)
        signing_payload = b"libp2p-record:" + key + value
        return public_key.verify(signing_payload, signature)
    except Exception:
        return False


def split_key(key: str) -> tuple[str, str]:
    """
    Split a record key into its type and the rest. The key must start with
    '/' and contain another '/' to separate the type. Raises `InvalidRecordType`
    if the key is invalid.

    Args:
        key (str): The record key to split.

    Returns:
        tuple[str, str]: The key type and the rest.

    """
    if not key or key[0] != "/":
        raise InvalidRecordType("Invalid record keytype")

    key = key[1:]

    i = key.find("/")
    if i <= 0:
        raise InvalidRecordType("Invalid record keytype")

    return key[:i], key[i + 1 :]
