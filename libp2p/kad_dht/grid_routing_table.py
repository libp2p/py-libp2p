"""
Grid Topology (Kademlia DHT) Routing Table Implementation.

This implements a 256-bucket binary tree structure based on XOR distance metrics,
matching the cpp-libp2p grid topology implementation.

Key features:
- 256 fixed buckets (binary tree structure)
- Common Prefix Length (CPL) based bucket indexing
- MRU (Most Recently Used) peer ordering
- Replaceable peer tracking (temporary vs permanent peers)
- Connection status tracking
"""

from dataclasses import dataclass
import hashlib
import logging
from typing import Any, cast

import multihash

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger(__name__)

GRID_BUCKET_COUNT = 256
DEFAULT_MAX_BUCKET_SIZE = 20


@dataclass
class BucketPeerInfo:
    """Information about a peer in a bucket."""

    peer_id: ID
    peer_info: PeerInfo | None = None
    is_replaceable: bool = False
    is_connected: bool = False


class NodeId:
    """DHT Node ID with SHA256-based hashing and XOR distance calculation."""

    def __init__(self, peer_id: ID):
        """Initialize Node ID from a peer ID."""
        self.peer_id: ID | None = peer_id
        digest = hashlib.sha256(peer_id.to_bytes()).digest()
        mh_bytes = multihash.encode(digest, "sha2-256")
        self.data = multihash.decode(mh_bytes).digest

    @classmethod
    def from_hash(cls, hash_data: bytes) -> "NodeId":
        """Create a NodeId from a pre-computed hash."""
        node_id = cast(NodeId, cls.__new__(cls))
        node_id.peer_id = None
        node_id.data = hash_data
        return node_id

    def distance(self, other: "NodeId") -> bytes:
        """Calculate XOR distance to another NodeId."""
        distance = bytes(a ^ b for a, b in zip(self.data, other.data))
        return distance

    def common_prefix_len(self, other: "NodeId") -> int:
        r"""
        Calculate the number of common prefix bits between two node IDs.

        Returns the number of leading bits that are the same.

        Example:
            0x00 and 0xFF have 0 common prefix bits.
            0xFF and 0xFE have 7 common prefix bits.

        """
        distance = self.distance(other)

        for i, byte in enumerate(distance):
            if byte != 0:
                leading_zeros = 0
                bit = 0x80
                while (byte & bit) == 0:
                    leading_zeros += 1
                    bit >>= 1
                return i * 8 + leading_zeros

        return 256

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, NodeId):
            return self.data == other.data
        return False

    def __repr__(self) -> str:
        return f"NodeId({self.data.hex()[:16]}...)"


class GridBucket:
    """
    A k-bucket in the grid topology.

    Stores up to k peers, with MRU (Most Recently Used) ordering.
    Uses a list to maintain insertion order (LRU at index 0, MRU at end).
    """

    def __init__(self, max_size: int = DEFAULT_MAX_BUCKET_SIZE):
        """Initialize a grid bucket."""
        self.max_size = max_size
        self.peers: list[BucketPeerInfo] = []

    def size(self) -> int:
        """Get the number of peers in the bucket."""
        return len(self.peers)

    def add_peer(
        self,
        peer_id: ID,
        peer_info: PeerInfo | None = None,
        is_replaceable: bool = False,
        is_connected: bool = False,
    ) -> bool:
        """
        Add a peer to the bucket.

        If the peer already exists, update its status and move to end (MRU).
        If the bucket is full, return False (caller should handle replacement).

        :param peer_id: ID of the peer to add
        :param peer_info: Optional PeerInfo object
        :param is_replaceable: True for temporary peers
        :param is_connected: True if peer is currently connected
        :return: True if peer was added, False if bucket is full
        """
        for i, peer_info_obj in enumerate(self.peers):
            if peer_info_obj.peer_id == peer_id:
                peer_info_obj.is_connected = is_connected
                self.peers.append(self.peers.pop(i))
                return True

        if len(self.peers) < self.max_size:
            self.peers.append(
                BucketPeerInfo(
                    peer_id=peer_id,
                    peer_info=peer_info,
                    is_replaceable=is_replaceable,
                    is_connected=is_connected,
                )
            )
            return True

        return False

    def move_to_front(self, peer_id: ID) -> bool:
        """
        Move a peer to the end (most recently used).

        :param peer_id: ID of the peer to move
        :return: True if peer was found, False otherwise
        """
        for i, peer in enumerate(self.peers):
            if peer.peer_id == peer_id:
                peer.is_connected = True
                self.peers.append(self.peers.pop(i))
                return True
        return False

    def remove_replaceable_peer(self) -> ID | None:
        """
        Remove a replaceable (temporary) peer from the bucket.

        Searches from end to beginning for the first replaceable unconnected peer.

        :return: ID of removed peer, or None if no replaceable peer found
        """
        for i in range(len(self.peers) - 1, -1, -1):
            peer = self.peers[i]
            if peer.is_replaceable and not peer.is_connected:
                removed_id = peer.peer_id
                del self.peers[i]
                return removed_id
        return None

    def remove_peer(self, peer_id: ID) -> bool:
        """
        Remove a specific peer from the bucket.

        :param peer_id: ID of the peer to remove
        :return: True if peer was removed, False if not found
        """
        for i, peer in enumerate(self.peers):
            if peer.peer_id == peer_id:
                del self.peers[i]
                return True
        return False

    def contains(self, peer_id: ID) -> bool:
        """Check if a peer is in the bucket."""
        return any(peer.peer_id == peer_id for peer in self.peers)

    def get_peer_info(self, peer_id: ID) -> PeerInfo | None:
        """Get PeerInfo for a specific peer."""
        for peer in self.peers:
            if peer.peer_id == peer_id:
                return peer.peer_info
        return None

    def peer_ids(self) -> list[ID]:
        """Get all peer IDs in the bucket."""
        return [peer.peer_id for peer in self.peers]

    def peer_infos(self) -> list[BucketPeerInfo]:
        """Get all BucketPeerInfo objects in the bucket."""
        return list(self.peers)

    def truncate(self, limit: int) -> None:
        """Truncate the bucket to a maximum size."""
        while len(self.peers) > limit:
            del self.peers[0]


class GridRoutingTable:
    """
    256-bucket grid topology routing table for Kademlia DHT.

    Uses a fixed array of 256 buckets indexed by common prefix length (CPL).
    Bucket index = 255 - CPL(local_id, peer_id)
    """

    def __init__(self, local_id: ID, max_bucket_size: int = DEFAULT_MAX_BUCKET_SIZE):
        """
        Initialize the grid routing table.

        :param local_id: The local peer's ID
        :param max_bucket_size: Maximum peers per bucket (default 20)
        """
        self.local_id = local_id
        self.local_node_id = NodeId(local_id)
        self.max_bucket_size = max_bucket_size

        self.buckets: list[GridBucket] = [
            GridBucket(max_bucket_size) for _ in range(GRID_BUCKET_COUNT)
        ]

        logger.debug(
            f"Initialized grid routing table with {GRID_BUCKET_COUNT} buckets, "
            f"max_bucket_size={max_bucket_size}"
        )

    def _get_bucket_index(self, node_id: NodeId) -> int | None:
        """
        Calculate the bucket index for a node ID.

        Bucket index = 255 - common_prefix_len(local_id, node_id)

        Returns None if the node ID is the same as local ID.

        :param node_id: The node ID to get bucket for
        :return: Bucket index (0-255) or None if node is self
        """
        if node_id == self.local_node_id:
            return None

        cpl = self.local_node_id.common_prefix_len(node_id)
        bucket_index = 255 - cpl
        return bucket_index

    def update(
        self,
        peer_id: ID,
        peer_info: PeerInfo | None = None,
        is_permanent: bool = True,
        is_connected: bool = False,
    ) -> bool:
        """
        Update or add a peer to the routing table.

        :param peer_id: ID of the peer to add/update
        :param peer_info: Optional PeerInfo object
        :param is_permanent: True for permanent peers, False for temporary
        :param is_connected: True if peer is currently connected
        :return: True if added/updated, False if bucket full and no replacement
        """
        if peer_id == self.local_id:
            return False

        node_id = NodeId(peer_id)
        bucket_index = self._get_bucket_index(node_id)

        if bucket_index is None:
            return False

        bucket = self.buckets[bucket_index]

        if bucket.add_peer(
            peer_id,
            peer_info=peer_info,
            is_replaceable=not is_permanent,
            is_connected=is_connected,
        ):
            return True

        removed_id = bucket.remove_replaceable_peer()
        if removed_id is not None:
            bucket.add_peer(
                peer_id,
                peer_info=peer_info,
                is_replaceable=not is_permanent,
                is_connected=is_connected,
            )
            logger.debug(
                f"Replaced peer {removed_id} with {peer_id} in bucket {bucket_index}"
            )
            return True

        logger.debug(f"Bucket {bucket_index} full and no replaceable peers")
        return False

    def remove(self, peer_id: ID) -> bool:
        """
        Remove a peer from the routing table.

        :param peer_id: ID of the peer to remove
        :return: True if peer was removed, False if not found
        """
        if peer_id == self.local_id:
            return False

        node_id = NodeId(peer_id)
        bucket_index = self._get_bucket_index(node_id)

        if bucket_index is None:
            return False

        return self.buckets[bucket_index].remove_peer(peer_id)

    def get_nearest_peers(self, target_key: bytes, count: int) -> list[ID]:
        """
        Find the nearest peers to a target key.

        Implements Kademlia's nearest peer lookup algorithm:
        1. Start with the bucket corresponding to the target key
        2. Expand search to adjacent buckets based on XOR distance
        3. Sort all results by XOR distance
        4. Return top `count` peers

        :param target_key: The target key (bytes)
        :param count: Maximum number of peers to return
        :return: List of peer IDs, sorted by distance to target key
        """
        target_node = NodeId.from_hash(target_key)

        cpl = self.local_node_id.common_prefix_len(target_node)
        bucket_index = 255 - cpl

        result_peers: list[tuple[ID, bytes]] = []  # (peer_id, distance)

        def bit_set(distance: bytes, i: int) -> bool:
            j = 255 - i
            byte_idx = j // 8
            bit_idx = 7 - (j % 8)
            return ((distance[byte_idx] >> bit_idx) & 1) != 0

        target_distance = self.local_node_id.distance(target_node)

        if 0 <= bucket_index < GRID_BUCKET_COUNT:
            for peer_info in self.buckets[bucket_index].peer_infos():
                peer_node = NodeId(peer_info.peer_id)
                distance = peer_node.distance(target_node)
                result_peers.append((peer_info.peer_id, distance))

            i = bucket_index
            while i > 0 and len(result_peers) < count:
                i -= 1
                if bit_set(target_distance, i):
                    for peer_info in self.buckets[i].peer_infos():
                        peer_node = NodeId(peer_info.peer_id)
                        distance = peer_node.distance(target_node)
                        result_peers.append((peer_info.peer_id, distance))

        if bucket_index != 0:
            for peer_info in self.buckets[0].peer_infos():
                peer_node = NodeId(peer_info.peer_id)
                distance = peer_node.distance(target_node)
                result_peers.append((peer_info.peer_id, distance))

        for i in range(1, GRID_BUCKET_COUNT):
            if i < bucket_index or (i == bucket_index):
                continue
            if not bit_set(target_distance, i):
                for peer_info in self.buckets[i].peer_infos():
                    peer_node = NodeId(peer_info.peer_id)
                    distance = peer_node.distance(target_node)
                    result_peers.append((peer_info.peer_id, distance))

        result_peers.sort(key=lambda x: int.from_bytes(x[1], byteorder="big"))

        return [peer_id for peer_id, _ in result_peers[:count]]

    def get_all_peers(self) -> list[ID]:
        """Get all peer IDs in the routing table."""
        peers = []
        for bucket in self.buckets:
            peers.extend(bucket.peer_ids())
        return peers

    def contains(self, peer_id: ID) -> bool:
        """Check if a peer is in the routing table."""
        if peer_id == self.local_id:
            return False

        node_id = NodeId(peer_id)
        bucket_index = self._get_bucket_index(node_id)

        if bucket_index is None:
            return False

        return self.buckets[bucket_index].contains(peer_id)

    def size(self) -> int:
        """Get the total number of peers in the routing table."""
        total = 0
        for bucket in self.buckets:
            total += bucket.size()
        return total

    def get_bucket(self, index: int) -> GridBucket | None:
        """Get a specific bucket by index."""
        if 0 <= index < GRID_BUCKET_COUNT:
            return self.buckets[index]
        return None

    def get_bucket_stats(self) -> dict[str, Any]:
        """Get statistics about bucket distribution."""
        stats = {
            "total_peers": self.size(),
            "total_buckets": GRID_BUCKET_COUNT,
            "non_empty_buckets": sum(1 for b in self.buckets if b.size() > 0),
            "bucket_distribution": [b.size() for b in self.buckets],
        }
        return stats
