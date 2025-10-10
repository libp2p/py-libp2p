import multihash

from libp2p.record.validator import Validator
from libp2p.record.utils import (
    split_key,
    unmarshal_public_key
)
from libp2p.record.exceptions import ErrInvalidRecordType
from libp2p.peer.id import ID


class PublicKeyValidator(Validator):
    """
    Validator for public key records.
    """

    def validate(self, key: str, value: bytes) -> None:
        ns, key = split_key(key)
        if ns != "pk":
            raise ErrInvalidRecordType("namespace not 'pk'")

        keyhash = bytes.fromhex(key)
        try:
            _ = multihash.decode(keyhash)
        except Exception:
            raise ErrInvalidRecordType("key did not contain valid multihash")

        try:
            pubkey = unmarshal_public_key(value)
        except Exception:
            raise ErrInvalidRecordType("Unable to unmarshal public key")

        try:
            peer_id = ID.from_pubkey(pubkey)
        except Exception:
            raise ErrInvalidRecordType("Could not derive peer ID from public key")

        if peer_id.to_bytes() != keyhash:
            raise ErrInvalidRecordType("public key does not match storage key")
    
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