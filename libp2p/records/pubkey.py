import multihash

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.keys import PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.rsa import RSAPublicKey
from libp2p.crypto.secp256k1 import Secp256k1PublicKey
from libp2p.peer.id import ID
from libp2p.records.utils import InvalidRecordType, split_key
from libp2p.records.validator import Validator


class PublicKeyValidator(Validator):
    """
    Validator for public key records.
    """

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate a public key record.

        Uses py-multihash v3 is_valid() for efficient validation without
        exception overhead.

        Args:
            key (str): The key associated with the record.
            value (bytes): The value of the record, expected to be a public key.

        Raises:
            InvalidRecordType: If the namespace is not 'pk', the key
                is not a valid multihash,
                the public key cannot be unmarshaled, the peer ID cannot be derived, or
                the public key does not match the storage key.

        """
        ns, key = split_key(key)
        if ns != "pk":
            raise InvalidRecordType("namespace not 'pk'")

        keyhash = bytes.fromhex(key)
        is_valid = getattr(multihash, "is_valid", None)
        if is_valid is not None:
            if not is_valid(keyhash):
                raise InvalidRecordType("key did not contain valid multihash")
        else:
            # Fallback when py-multihash has no is_valid (e.g. older version)
            try:
                multihash.decode(keyhash)
            except Exception:
                raise InvalidRecordType("key did not contain valid multihash")

        try:
            pubkey = unmarshal_public_key(value)
        except Exception:
            raise InvalidRecordType("Unable to unmarshal public key")

        try:
            peer_id = ID.from_pubkey(pubkey)
        except Exception:
            raise InvalidRecordType("Could not derive peer ID from public key")

        if peer_id.to_bytes() != keyhash:
            raise InvalidRecordType("public key does not match storage key")

    def select(self, key: str, values: list[bytes]) -> int:
        """
        Select a value from a list of public key records.

        Args:
            key (str): The key associated with the records.
            values (list[bytes]): A list of public key values.

        Returns:
            int: Always returns 0 as all public keys are treated identically.

        """
        return 0  # All public keys are treated identical


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
