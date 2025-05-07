"""
Kademlia DHT routing table implementation.
"""

from collections import defaultdict, OrderedDict
import logging
import time
from typing import Dict, List, Optional, Set, Tuple, Mapping

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from .utils import distance, shared_prefix_len, sort_peer_ids_by_distance

logger = logging.getLogger("libp2p.kademlia.routing_table")

# Default parameters
BUCKET_SIZE = 20  # k in the Kademlia paper
MAXIMUM_BUCKETS = 256  # Maximum number of buckets (for 256-bit keys)


class KBucket:
    """
    A k-bucket implementation for the Kademlia DHT.
    
    Each k-bucket stores up to k (BUCKET_SIZE) peers, sorted by least-recently seen.
    """
    
    def __init__(self, bucket_size: int = BUCKET_SIZE):
        """
        Initialize a new k-bucket.
        
        Args:
            bucket_size: Maximum number of peers to store in the bucket
        """
        self.bucket_size = bucket_size
        # Store PeerInfo objects along with last-seen timestamp
        self.peers: OrderedDict[ID, Tuple[PeerInfo, float]] = OrderedDict()
        
    def peer_ids(self) -> List[ID]:
        """Get all peer IDs in the bucket."""
        return list(self.peers.keys())
    
    def peer_infos(self) -> List[PeerInfo]:
        """Get all PeerInfo objects in the bucket."""
        return [info for info, _ in self.peers.values()]
    
    def add_peer(self, peer_info: PeerInfo) -> bool:
        """
        Add a peer to the bucket. Returns True if the peer was added or updated,
        False if the bucket is full.
        """
        current_time = time.time()
        peer_id = peer_info.peer_id
        
        # If peer is already in the bucket, move it to the end (most recently seen)
        if peer_id in self.peers:
            self.peers.move_to_end(peer_id)
            self.peers[peer_id] = (peer_info, current_time)
            return True
            
        # If bucket has space, add the peer
        if len(self.peers) < self.bucket_size:
            self.peers[peer_id] = (peer_info, current_time)
            return True
            
        return False
    
    def remove_peer(self, peer_id: ID) -> bool:
        """
        Remove a peer from the bucket.
        Returns True if the peer was in the bucket, False otherwise.
        """
        if peer_id in self.peers:
            del self.peers[peer_id]
            return True
        return False
        
    def has_peer(self, peer_id: ID) -> bool:
        """Check if the peer is in the bucket."""
        return peer_id in self.peers
    
    def get_peer_info(self, peer_id: ID) -> Optional[PeerInfo]:
        """Get the PeerInfo for a given peer ID if it exists in the bucket."""
        if peer_id in self.peers:
            return self.peers[peer_id][0]
        return None
    
    def get_oldest_peer(self) -> Optional[ID]:
        """Get the least-recently seen peer."""
        if not self.peers:
            return None
        return next(iter(self.peers.keys()))
    
    def size(self) -> int:
        """Get the number of peers in the bucket."""
        return len(self.peers)


class RoutingTable:
    """
    Kademlia DHT routing table implementation.
    
    The routing table consists of k-buckets, where each bucket holds peers
    that share a specific prefix length with the local peer ID.
    """
    
    def __init__(
        self, 
        local_peer_id: ID, 
        bucket_size: int = BUCKET_SIZE
    ):
        """
        Initialize a new routing table.
        
        Args:
            local_peer_id: The ID of the local peer
            bucket_size: Maximum size for each k-bucket
        """
        self.local_peer_id = local_peer_id
        self.local_key = local_peer_id.to_bytes()
        self.bucket_size = bucket_size
        self.buckets: Dict[int, KBucket] = defaultdict(lambda: KBucket(bucket_size))
    
    def add_peer(self, peer_info: PeerInfo) -> bool:
        """
        Add a peer to the routing table.
        
        Args:
            peer_info: The PeerInfo object to add
            
        Returns:
            bool: True if peer was added or updated, False otherwise
        """
        peer_id = peer_info.peer_id
        if peer_id == self.local_peer_id:
            return False
            
        peer_key = peer_id.to_bytes()
        prefix_length = shared_prefix_len(self.local_key, peer_key)
        return self.buckets[prefix_length].add_peer(peer_info)
    
    def remove_peer(self, peer_id: ID) -> bool:
        """Remove a peer from the routing table."""
        if peer_id == self.local_peer_id:
            return False
            
        peer_key = peer_id.to_bytes()
        prefix_length = shared_prefix_len(self.local_key, peer_key)
        return self.buckets[prefix_length].remove_peer(peer_id)
    
    def find_closest_peers(self, target_key: bytes, count: int = 20) -> List[ID]:
        """
        Find the closest peers to a target key.
        
        Args:
            target_key: The target key to find neighbors for
            count: The maximum number of peers to return
            
        Returns:
            List[ID]: The closest peers, sorted by distance to the target key
        """
        # Special case: if the target key is the same as our local key
        if target_key == self.local_key:
            # When searching for our own ID, start with the highest bucket (255)
            # and work downward until we find enough peers
            collected_peers = []
            max_bucket_idx = MAXIMUM_BUCKETS - 1  # Typically 255 for 32-byte keys
            
            logger.info("max bucket index: %d", max_bucket_idx)
            # Start from max bucket index and move downward
            for bucket_idx in range(max_bucket_idx, -1, -1):
                if bucket_idx in self.buckets:
                    collected_peers.extend(self.buckets[bucket_idx].peer_ids())
                    
                # Stop if we've collected enough peers
                if len(collected_peers) >= count:
                    break
                    
            logger.info("collected peers: %s", collected_peers)
            # Return the closest peers, up to the requested count
            return sort_peer_ids_by_distance(target_key, collected_peers)[:count]
        
        # First determine which bucket the target would belong to
        target_bucket_idx = shared_prefix_len(self.local_key, target_key)
        
        # Start with peers from the target bucket
        collected_peers = []
        if target_bucket_idx in self.buckets:
            collected_peers.extend(self.buckets[target_bucket_idx].peer_ids())
        
        # If we need more peers, expand outward (+1/-1) from the target bucket
        if len(collected_peers) < count:
            # Maximum bucket index is the bit length of the key (typically 256 bits for Kademlia)
            max_bucket_idx = len(self.local_key) * 8 - 1  # Typically 255 for 32-byte keys
            
            # Expand outward one step at a time
            distance = 1
            while len(collected_peers) < count and distance <= max_bucket_idx:
                # Try bucket with index (target_bucket_idx + distance)
                higher_bucket_idx = target_bucket_idx + distance
                if higher_bucket_idx <= max_bucket_idx and higher_bucket_idx in self.buckets:
                    collected_peers.extend(self.buckets[higher_bucket_idx].peer_ids())
                
                # Try bucket with index (target_bucket_idx - distance)
                lower_bucket_idx = target_bucket_idx - distance
                if lower_bucket_idx >= 0 and lower_bucket_idx in self.buckets:
                    collected_peers.extend(self.buckets[lower_bucket_idx].peer_ids())
                
                # Increase distance for next iteration
                distance += 1
                
                # If we've collected enough peers, stop expanding
                if len(collected_peers) >= count:
                    break
        
        # Sort all collected peers by XOR distance to the target key and return up to count
        return sort_peer_ids_by_distance(target_key, collected_peers)[:count]
    
    def find_closest_peer_infos(self, target_key: bytes, count: int = 20) -> List[PeerInfo]:
        """
        Find the closest peers to a target key and return their PeerInfo objects.
        
        Args:
            target_key: The target key to find neighbors for
            count: The maximum number of peers to return
            
        Returns:
            List[PeerInfo]: The closest peers' PeerInfo objects, sorted by distance to the target key
        """
        closest_peer_ids = self.find_closest_peers(target_key, count)
        result = []
        
        for peer_id in closest_peer_ids:
            # Find which bucket this peer belongs to
            peer_key = peer_id.to_bytes()
            prefix_length = shared_prefix_len(self.local_key, peer_key)
            
            # Get the PeerInfo
            peer_info = self.buckets[prefix_length].get_peer_info(peer_id)
            if peer_info:
                result.append(peer_info)
                
        return result
    
    def get_peer_info(self, peer_id: ID) -> Optional[PeerInfo]:
        """
        Get the PeerInfo for a specific peer ID if it exists in the routing table.
        
        Args:
            peer_id: The ID of the peer to look for
            
        Returns:
            Optional[PeerInfo]: The PeerInfo if found, None otherwise
        """
        peer_key = peer_id.to_bytes()
        prefix_length = shared_prefix_len(self.local_key, peer_key)
        
        if prefix_length in self.buckets:
            return self.buckets[prefix_length].get_peer_info(peer_id)
        return None
    
    def size(self) -> int:
        """Get the total number of peers in the routing table."""
        return sum(bucket.size() for bucket in self.buckets.values())
    
    def get_bucket_sizes(self) -> Dict[int, int]:
        """Get the size of each bucket (for diagnostics)."""
        return {prefix: bucket.size() for prefix, bucket in self.buckets.items()}
    
    def get_peer_ids(self) -> List[ID]:
        """Get all peer IDs in the routing table."""
        all_peers = []
        for bucket in self.buckets.values():
            all_peers.extend(bucket.peer_ids())
        return all_peers
        
    def get_peer_infos(self) -> List[PeerInfo]:
        """Get all PeerInfo objects in the routing table."""
        all_peer_infos = []
        for bucket in self.buckets.values():
            all_peer_infos.extend(bucket.peer_infos())
        return all_peer_infos