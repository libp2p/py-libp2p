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
import time
from typing import Any

import trio

from libp2p.abc import IHost
from libp2p.kad_dht.common import BUCKET_SIZE, PEER_REFRESH_INTERVAL
from libp2p.kad_dht.routing_table import key_to_int, peer_id_to_key
from libp2p.kad_dht.utils import shared_prefix_len, xor_distance
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger(__name__)

GRID_BUCKET_COUNT = 256
DEFAULT_MAX_BUCKET_SIZE = BUCKET_SIZE


@dataclass
class BucketPeerInfo:
    """Information about a peer in a bucket."""

    peer_id: ID
    peer_info: PeerInfo | None = None
    last_seen: float = 0
    is_replaceable: bool = False
    is_connected: bool = False


class NodeId:
    """DHT node key wrapper using the shared Kademlia key helpers."""

    def __init__(self, peer_id: ID):
        """Initialize Node ID from a peer ID."""
        self.peer_id: ID | None = peer_id
        self.data = peer_id_to_key(peer_id)

    @classmethod
    def from_hash(cls, hash_data: bytes) -> "NodeId":
        """Create a NodeId from a pre-computed hash."""
        node_id: NodeId = cls.__new__(cls)  # type: ignore[assignment]
        node_id.peer_id = None
        node_id.data = hash_data
        return node_id

    def distance(self, other: "NodeId") -> bytes:
        """Calculate XOR distance to another NodeId."""
        distance = xor_distance(self.data, other.data)
        return distance.to_bytes(len(self.data), byteorder="big")

    def common_prefix_len(self, other: "NodeId") -> int:
        """Calculate the number of common prefix bits between two node IDs."""
        return shared_prefix_len(self.data, other.data)

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
        current_time = time.time()
        for i, peer_info_obj in enumerate(self.peers):
            if peer_info_obj.peer_id == peer_id:
                if peer_info is not None:
                    peer_info_obj.peer_info = peer_info
                peer_info_obj.is_replaceable = is_replaceable
                peer_info_obj.is_connected = is_connected
                peer_info_obj.last_seen = current_time
                self.peers.append(self.peers.pop(i))
                return True

        if len(self.peers) < self.max_size:
            self.peers.append(
                BucketPeerInfo(
                    peer_id=peer_id,
                    peer_info=peer_info,
                    last_seen=current_time,
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

    def get_stale_peers(self, stale_threshold_seconds: int = 3600) -> list[ID]:
        """Get peers whose last-seen timestamp is older than the threshold."""
        current_time = time.time()
        return [
            peer.peer_id
            for peer in self.peers
            if current_time - peer.last_seen > stale_threshold_seconds
        ]

    def get_oldest_peer(self) -> ID | None:
        """Get the least recently seen peer."""
        if not self.peers:
            return None
        return self.peers[0].peer_id

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

    def __init__(
        self,
        local_id: ID,
        host: IHost | None = None,
        max_bucket_size: int = DEFAULT_MAX_BUCKET_SIZE,
    ):
        """
        Initialize the grid routing table.

        :param local_id: The local peer's ID
        :param max_bucket_size: Maximum peers per bucket (default 20)
        """
        self.local_id = local_id
        self.host = host
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

    async def add_peer(
        self,
        peer_obj: PeerInfo | ID,
        *,
        skip_server_mode_check: bool = False,
        is_permanent: bool = True,
        is_connected: bool = False,
    ) -> bool:
        """
        Update or add a peer to the routing table.

        :param peer_obj: Either PeerInfo object or peer ID to add
        :param skip_server_mode_check: If True, skip the KAD protocol check
        :param is_permanent: True for permanent peers, False for temporary
        :param is_connected: True if peer is currently connected
        :return: True if added/updated, False if bucket full and no replacement
        """
        peer_info = await self._coerce_peer_info(peer_obj)
        if peer_info is None:
            return False

        peer_id = peer_info.peer_id
        if peer_id == self.local_id:
            return False

        if not skip_server_mode_check and not self._peer_supports_kad(peer_id):
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

        oldest_peer_id = bucket.get_oldest_peer()
        if oldest_peer_id is not None and not await self._ping_peer(oldest_peer_id):
            bucket.remove_peer(oldest_peer_id)
            return bucket.add_peer(
                peer_id,
                peer_info=peer_info,
                is_replaceable=not is_permanent,
                is_connected=is_connected,
            )

        logger.debug(f"Bucket {bucket_index} full and no replaceable peers")
        return False

    def update(
        self,
        peer_id: ID,
        peer_info: PeerInfo | None = None,
        is_permanent: bool = True,
        is_connected: bool = False,
    ) -> bool:
        """Synchronously update a bucket for tests and local-only callers."""
        if peer_info is None:
            peer_info = PeerInfo(peer_id, [])
        if peer_id == self.local_id:
            return False

        bucket_index = self._get_bucket_index(NodeId(peer_id))
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
        if removed_id is None:
            return False
        return bucket.add_peer(
            peer_id,
            peer_info=peer_info,
            is_replaceable=not is_permanent,
            is_connected=is_connected,
        )

    def remove_peer(self, peer_id: ID) -> bool:
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

    def remove(self, peer_id: ID) -> bool:
        """Backward-compatible alias for remove_peer."""
        return self.remove_peer(peer_id)

    def find_local_closest_peers(self, key: bytes, count: int = 20) -> list[ID]:
        """Find the closest local routing-table peers to a DHT key."""
        target_hash = hashlib.sha256(key).digest()
        all_peers = self.get_peer_ids()
        all_peers.sort(
            key=lambda peer_id: xor_distance(peer_id_to_key(peer_id), target_hash)
        )
        return all_peers[:count]

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

        result_peers.sort(key=lambda x: key_to_int(x[1]))

        return [peer_id for peer_id, _ in result_peers[:count]]

    def get_all_peers(self) -> list[ID]:
        """Get all peer IDs in the routing table."""
        return self.get_peer_ids()

    def get_peer_ids(self) -> list[ID]:
        """Get all peer IDs in the routing table."""
        peers = []
        for bucket in self.buckets:
            peers.extend(bucket.peer_ids())
        return peers

    def get_peer_info(self, peer_id: ID) -> PeerInfo | None:
        """Get the peer info for a specific peer."""
        if peer_id == self.local_id:
            return None

        bucket_index = self._get_bucket_index(NodeId(peer_id))
        if bucket_index is None:
            return None
        return self.buckets[bucket_index].get_peer_info(peer_id)

    def get_peer_infos(self) -> list[PeerInfo]:
        """Get all PeerInfo objects in the routing table."""
        peer_infos = []
        for bucket in self.buckets:
            peer_infos.extend(
                peer.peer_info for peer in bucket.peer_infos() if peer.peer_info
            )
        return peer_infos

    def contains(self, peer_id: ID) -> bool:
        """Check if a peer is in the routing table."""
        if peer_id == self.local_id:
            return False

        node_id = NodeId(peer_id)
        bucket_index = self._get_bucket_index(node_id)

        if bucket_index is None:
            return False

        return self.buckets[bucket_index].contains(peer_id)

    def peer_in_table(self, peer_id: ID) -> bool:
        """Check if a peer is in the routing table."""
        return self.contains(peer_id)

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

    def get_stale_peers(self, stale_threshold_seconds: int = 3600) -> list[ID]:
        """Get all stale peer IDs from all buckets."""
        stale_peers = []
        for bucket in self.buckets:
            stale_peers.extend(bucket.get_stale_peers(stale_threshold_seconds))
        return stale_peers

    def cleanup_routing_table(self) -> None:
        """Remove all peers from the routing table."""
        self.buckets = [
            GridBucket(self.max_bucket_size) for _ in range(GRID_BUCKET_COUNT)
        ]
        logger.info("Grid routing table cleaned up, all data removed.")

    async def _periodic_peer_refresh(self) -> None:
        """Background task to periodically refresh stale peers."""
        try:
            while True:
                await trio.sleep(PEER_REFRESH_INTERVAL)
                for peer_id in self.get_stale_peers():
                    if await self._ping_peer(peer_id):
                        await self.add_peer(peer_id, skip_server_mode_check=True)
                    else:
                        self.remove_peer(peer_id)
        except trio.Cancelled:
            logger.debug("Grid peer refresh task cancelled")

    async def _coerce_peer_info(self, peer_obj: PeerInfo | ID) -> PeerInfo | None:
        """Resolve a PeerInfo from a PeerInfo object or peerstore-backed peer ID."""
        if isinstance(peer_obj, PeerInfo):
            return peer_obj

        if self.host is None:
            logger.debug("No host available to resolve peer %s, skipping", peer_obj)
            return None

        try:
            addrs = self.host.get_peerstore().addrs(peer_obj)
        except Exception as peerstore_error:
            logger.debug(
                "Peer %s not found in peerstore: %s, skipping",
                peer_obj,
                peerstore_error,
            )
            return None

        if not addrs:
            logger.debug(
                "No addresses found for peer %s in peerstore, skipping",
                peer_obj,
            )
            return None
        return PeerInfo(peer_obj, addrs)

    def _peer_supports_kad(self, peer_id: ID) -> bool:
        """Return False only when identify says the peer lacks KAD support."""
        try:
            from .common import PROTOCOL_ID

            peer_protocols = self.host.get_peerstore().get_protocols(peer_id)
            if peer_protocols is not None and len(peer_protocols) > 0:
                return str(PROTOCOL_ID) in peer_protocols
        except Exception:
            pass
        return True

    async def _ping_peer(self, peer_id: ID) -> bool:
        """Ping a peer using the libp2p ping protocol."""
        from libp2p.host.ping import PingService

        try:
            ping_service = PingService(self.host)
            return bool(await ping_service.ping(peer_id, ping_amt=1))
        except Exception as e:
            logger.debug(f"Failed to ping peer {peer_id} via libp2p ping: {e}")
            return False
