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

    Args:
        binary_data: The binary data to hash.

    Returns:
        bytes: The resulting key.
    """
    return multihash.digest(binary_data, "sha2-256").digest


def distance(key_one: bytes, key_two: bytes) -> int:
    """
    Calculate the XOR distance between two keys.

    Args:
        key_one: First key
        key_two: Second key

    Returns:
        int: The XOR distance between the keys
    """
    # Ensure keys are the same length by using minimum length
    length = min(len(key_one), len(key_two))
    result = 0

    # Calculate XOR distance
    for i in range(length):
        result = (result << 8) | (key_one[i] ^ key_two[i])

    return result


def bytes_to_base58(data: bytes) -> str:
    """
    Convert bytes to base58 encoded string.

    Args:
        data: Input bytes

    Returns:
        str: Base58 encoded string
    """
    return base58.b58encode(data).decode("utf-8")


def sort_peer_ids_by_distance(target_key: bytes, peer_ids: list[ID]) -> list[ID]:
    """
    Sort a list of peer IDs by their distance to the target key.

    Args:
        target_key: The target key to measure distance from
        peer_ids: List of peer IDs to sort

    Returns:
        List[ID]: Sorted list of peer IDs from closest to furthest
    """
    return sorted(
        peer_ids, key=lambda peer_id: distance(target_key, peer_id.to_bytes())
    )


def shared_prefix_len(first: bytes, second: bytes) -> int:
    """
    Calculate the number of prefix bits shared by two byte sequences.

    Args:
        first: First byte sequence
        second: Second byte sequence

    Returns:
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
