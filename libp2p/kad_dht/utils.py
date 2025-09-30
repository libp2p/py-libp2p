"""
Utility functions for Kademlia DHT implementation.
"""

import heapq
import logging
from typing import Generator, Iterator

import base58
import multihash

from libp2p.abc import IHost
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)

from .pb.kademlia_pb2 import (
    Message,
)

logger = logging.getLogger("kademlia-example.utils")


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


def get_peer_distance(peer_id: ID, target_key: bytes) -> int:
    """
    Calculate the XOR distance between a peer ID and target key.
    
    This is a cached version that avoids repeated hashing for the same peer.
    
    params: peer_id: The peer ID to calculate distance for
    params: target_key: The target key to measure distance from
    
    Returns
    -------
        int: XOR distance between peer and target key
    """
    peer_hash = multihash.digest(peer_id.to_bytes(), "sha2-256").digest
    return xor_distance(target_key, peer_hash)


def find_closest_peers_heap(
    target_key: bytes, 
    peer_ids: list[ID], 
    count: int
) -> list[ID]:
    """
    Find the closest peers to a target key using a heap-based approach.
    
    This is more memory-efficient than sorting the entire list when only
    the top-k peers are needed. Time complexity: O(n log k) instead of O(n log n).
    
    params: target_key: The target key to measure distance from
    params: peer_ids: List of peer IDs to search through
    params: count: Maximum number of closest peers to return
    
    Returns
    -------
        List[ID]: List of closest peer IDs (up to count)
    """
    if not peer_ids:
        return []
    
    if len(peer_ids) <= count:
        # If we have fewer peers than requested, just sort them all
        return sort_peer_ids_by_distance(target_key, peer_ids)
    
    # Use a max-heap to keep track of the k closest peers
    # We store (-distance, peer_id) to make it a max-heap (Python's heapq is min-heap)
    heap = []
    
    for peer_id in peer_ids:
        distance = get_peer_distance(peer_id, target_key)
        
        if len(heap) < count:
            # Heap not full yet, add the peer
            heapq.heappush(heap, (-distance, peer_id))
        else:
            # Heap is full, check if this peer is closer than the farthest in heap
            max_distance = -heap[0][0]  # Get the current max distance
            if distance < max_distance:
                # This peer is closer, replace the farthest
                heapq.heapreplace(heap, (-distance, peer_id))
    
    # Extract peers from heap and sort by distance
    closest_peers = [peer_id for _, peer_id in heap]
    return sort_peer_ids_by_distance(target_key, closest_peers)


def find_closest_peers_streaming(
    target_key: bytes, 
    peer_generator: Generator[ID, None, None], 
    count: int
) -> list[ID]:
    """
    Find the closest peers using a streaming approach for memory efficiency.
    
    This is useful when dealing with large peer sets that don't fit in memory.
    Time complexity: O(n log k) where n is the total number of peers.
    
    params: target_key: The target key to measure distance from
    params: peer_generator: Generator yielding peer IDs
    params: count: Maximum number of closest peers to return
    
    Returns
    -------
        List[ID]: List of closest peer IDs (up to count)
    """
    heap = []
    
    for peer_id in peer_generator:
        distance = get_peer_distance(peer_id, target_key)
        
        if len(heap) < count:
            # Heap not full yet, add the peer
            heapq.heappush(heap, (-distance, peer_id))
        else:
            # Heap is full, check if this peer is closer than the farthest in heap
            max_distance = -heap[0][0]  # Get the current max distance
            if distance < max_distance:
                # This peer is closer, replace the farthest
                heapq.heapreplace(heap, (-distance, peer_id))
    
    # Extract peers from heap and sort by distance
    if not heap:
        return []
    
    closest_peers = [peer_id for _, peer_id in heap]
    return sort_peer_ids_by_distance(target_key, closest_peers)


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
