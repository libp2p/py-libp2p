"""
Utility functions for Kademlia DHT implementation.
"""

import base58
import multihash

from libp2p.peer.id import (
    ID,
)


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


def bytes_to_base58(data: bytes) -> str:
    """
    Convert bytes to base58 encoded string.

    params: data: Input bytes

    Returns
    -------
        str: Base58 encoded string

    """
    return base58.b58encode(data).decode("utf-8")


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
