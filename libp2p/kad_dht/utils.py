"""
Utility functions for Kademlia DHT implementation.
"""

import logging

import base58
import multihash

from libp2p.abc import IHost
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import create_signed_peer_record

from .pb.kademlia_pb2 import (
    Message,
)

logger = logging.getLogger("kademlia-example.utils")


def maybe_consume_signed_record(
    msg: Message | Message.Peer, host: IHost, peer_id: ID | None = None
) -> bool:
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
                    logger.error("Updating the certified-addr-book was unsuccessful")
            except Exception as e:
                logger.error("Error updating teh certified addr book for peer: %s", e)
                return False
    else:
        if msg.HasField("signedRecord"):
            # TODO: Check in with the Message.Peer id with the record's id
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
            except Exception as e:
                logger.error(
                    "Error updating the certified-addr-book: %s",
                    e,
                )
                return False
    return True


def env_to_send_in_RPC(host: IHost) -> tuple[bytes, bool]:
    listen_addrs_set = {addr for addr in host.get_addrs()}
    local_env = host.get_peerstore().get_local_record()

    if local_env is None:
        # No cached SPR yet -> create one
        return issue_and_cache_local_record(host), True
    else:
        record_addrs_set = local_env._env_addrs_set()
        if record_addrs_set == listen_addrs_set:
            # Perfect match -> reuse cached envelope
            return local_env.marshal_envelope(), False
        else:
            # Addresses changed -> issue a new SPR and cache it
            return issue_and_cache_local_record(host), True


def issue_and_cache_local_record(host: IHost) -> bytes:
    env = create_signed_peer_record(
        host.get_id(),
        host.get_addrs(),
        host.get_private_key(),
    )
    # Cache it for nexxt time use
    host.get_peerstore().set_local_record(env)
    return env.marshal_envelope()


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
