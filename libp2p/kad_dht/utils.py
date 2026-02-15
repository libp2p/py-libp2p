"""
Utility functions for Kademlia DHT implementation.
"""

import logging

import base58
import multibase
import multihash

from libp2p.abc import IHost
from libp2p.encoding_config import get_default_encoding
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)

from .pb.kademlia_pb2 import (
    Message,
)

logger = logging.getLogger(__name__)


def maybe_consume_signed_record(
    msg: Message | Message.Peer, host: IHost, peer_id: ID | None = None
) -> bool:
    """
    Attempt to parse and store a signed-peer-record (Envelope) received during
    DHT communication. If the record is invalid, the peer-id does not match, or
    updating the peerstore fails, the function logs an error and returns False.

    Parameters
    ----------
    msg : Message | Message.Peer
        The protobuf message received during DHT communication. Can either be a
        top-level `Message` containing `senderRecord` or a `Message.Peer`
        containing `signedRecord`.
    host : IHost
        The local host instance, providing access to the peerstore for storing
        verified peer records.
    peer_id : ID | None, optional
        The expected peer ID for record validation. If provided, the peer ID
        inside the record must match this value.

    Returns
    -------
    bool
        True if a valid signed peer record was successfully consumed and stored,
        False otherwise.

    """
    if isinstance(msg, Message):
        if msg.HasField("senderRecord"):
            try:
                # Convert the signed-peer-record(Envelope) from
                # protobuf bytes
                envelope, record = consume_envelope(
                    msg.senderRecord,
                    "libp2p-peer-record",
                )
                if not (isinstance(peer_id, ID) and record.peer_id == peer_id):
                    return False
                # Use the default  TTL of 2 hours (7200 seconds)
                if not host.get_peerstore().consume_peer_record(envelope, 7200):
                    logger.error("Failed to update the Certified-Addr-Book")
                    return False
            except Exception as e:
                logger.error("Failed to update the Certified-Addr-Book: %s", e)
                return False
    else:
        if msg.HasField("signedRecord"):
            try:
                # Convert the signed-peer-record(Envelope) from
                # protobuf bytes
                envelope, record = consume_envelope(
                    msg.signedRecord,
                    "libp2p-peer-record",
                )
                if not record.peer_id.to_bytes() == msg.id:
                    return False
                # Use the default TTL of 2 hours (7200 seconds)
                if not host.get_peerstore().consume_peer_record(envelope, 7200):
                    logger.error("Failed to update the Certified-Addr-Book")
                    return False
            except Exception as e:
                logger.error(
                    "Failed to update the Certified-Addr-Book: %s",
                    e,
                )
                return False
    return True


def create_key_from_binary(binary_data: bytes) -> bytes:
    """
    Creates a key for the DHT by hashing binary data with SHA-256.

    params: binary_data: The binary data to hash.

    Returns
    -------
    bytes: The resulting key.

    """
    return multihash.digest(binary_data, "sha2-256").digest


def xor_distance(key1: bytes, key2: bytes) -> int:
    """
    Calculate the XOR distance between two keys.

    params: key1: First key (bytes)
    params: key2: Second key (bytes)

    Returns
    -------
        int: The XOR distance between the keys

    """
    # Ensure the inputs are bytes
    if not isinstance(key1, bytes) or not isinstance(key2, bytes):
        raise TypeError("Both key1 and key2 must be bytes objects")

    # Convert to integers
    k1 = int.from_bytes(key1, byteorder="big")
    k2 = int.from_bytes(key2, byteorder="big")

    # Calculate XOR distance
    return k1 ^ k2


def bytes_to_multibase(data: bytes, encoding: str | None = None) -> str:
    """
    Convert bytes to multibase-encoded string.

    :param data: Bytes to encode
    :param encoding: Encoding to use. When *None* the process-wide default
        from :mod:`libp2p.encoding_config` is used.
    :return: Multibase-encoded string
    """
    if encoding is None:
        encoding = get_default_encoding()
    return multibase.encode(encoding, data).decode()


def multibase_to_bytes(multibase_str: str) -> bytes:
    """
    Convert multibase-encoded string to bytes.

    Args:
        multibase_str: Multibase-encoded string
    Returns:
        Decoded bytes
    Raises:
        multibase.InvalidMultibaseStringError: If string is not valid multibase
        multibase.DecodingError: If decoding fails

    """
    if not multibase.is_encoded(multibase_str):
        # Fallback to base58 for backward compatibility
        return base58.b58decode(multibase_str)
    result = multibase.decode(multibase_str)
    # py-multibase may return bytes or (encoding, bytes) depending on
    # version — handle both.
    return result[1] if isinstance(result, tuple) else result


# Keep old function for backward compatibility
def bytes_to_base58(data: bytes) -> str:
    """Deprecated: Use bytes_to_multibase instead."""
    return base58.b58encode(data).decode()


def sort_peer_ids_by_distance(target_key: bytes, peer_ids: list[ID]) -> list[ID]:
    """
    Sort a list of peer IDs by their distance to the target key.

    params: target_key: The target key to measure distance from
    params: peer_ids: List of peer IDs to sort

    Returns
    -------
        List[ID]: Sorted list of peer IDs from closest to furthest

    """

    def get_distance(peer_id: ID) -> int:
        # Hash the peer ID bytes to get a key for distance calculation
        peer_hash = multihash.digest(peer_id.to_bytes(), "sha2-256").digest
        return xor_distance(target_key, peer_hash)

    return sorted(peer_ids, key=get_distance)


def shared_prefix_len(first: bytes, second: bytes) -> int:
    """
    Calculate the number of prefix bits shared by two byte sequences.

    params: first: First byte sequence
    params: second: Second byte sequence

    Returns
    -------
        int: Number of shared prefix bits

    """
    # Compare each byte to find the first bit difference
    common_length = 0
    for i in range(min(len(first), len(second))):
        byte_first = first[i]
        byte_second = second[i]

        if byte_first == byte_second:
            common_length += 8
        else:
            # Find specific bit where they differ
            xor = byte_first ^ byte_second
            # Count leading zeros in the xor result
            for j in range(7, -1, -1):
                if (xor >> j) & 1 == 1:
                    return common_length + (7 - j)

            # This shouldn't be reached if xor != 0
            return common_length + 8

    return common_length
