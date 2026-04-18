from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.keys import PrivateKey


class InvalidRecordType(Exception):
    pass


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
    author_bytes = public_key.to_bytes()
    return signature, author_bytes


def verify_record(
    signature: bytes, author_public_key: bytes, key: bytes, value: bytes
) -> bool:
    """
    Verify a signed DHT record.

    Args:
        signature: The record signature
        author_public_key: The serialized public key of the author
        key: The record key
        value: The record value

    Returns:
        bool: True if the signature is valid, False otherwise

    """
    try:
        public_key = Ed25519PublicKey.from_bytes(author_public_key)
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
