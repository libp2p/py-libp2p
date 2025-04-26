"""
Kademlia DHT routing table implementation.
"""

from collections import defaultdict, OrderedDict
import logging
import time
from typing import Dict, List, Optional, Set, Tuple

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from .utils import distance, shared_prefix_len, sort_peer_ids_by_distance

logger = logging.getLogger("libp2p.kademlia.routing_table")

# Default parameters
BUCKET_SIZE = 20  # k in the Kademlia paper
REPLACEMENT_CACHE_SIZE = 5


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
        self.peers: OrderedDict[ID, float] = OrderedDict()
        self.replacement_cache: OrderedDict[ID, float] = OrderedDict()
        
    def peer_ids(self) -> List[ID]:
        """Get all peer IDs in the bucket."""
        return list(self.peers.keys())
    
    def add_peer(self, peer_id: ID) -> bool:
        """
        Add a peer to the bucket. Returns True if the peer was added or updated,
        False if the bucket is full and the peer was added to the replacement cache.
        """
        current_time = time.time()
        
        # If peer is already in the bucket, move it to the end (most recently seen)
        if peer_id in self.peers:
            self.peers.move_to_end(peer_id)
            self.peers[peer_id] = current_time
            return True
            
        # If bucket has space, add the peer
        if len(self.peers) < self.bucket_size:
            self.peers[peer_id] = current_time
            return True
            
        # Bucket is full, add to replacement cache
        self.replacement_cache[peer_id] = current_time
        if len(self.replacement_cache) > REPLACEMENT_CACHE_SIZE:
            # Remove oldest from replacement cache if it's full
            self.replacement_cache.popitem(last=False)
        return False
    
    def remove_peer(self, peer_id: ID) -> bool:
        """
        Remove a peer from the bucket.
        Returns True if the peer was in the bucket, False otherwise.
        """
        if peer_id in self.peers:
            del self.peers[peer_id]
            
            # Try to promote a peer from the replacement cache
            if self.replacement_cache and len(self.peers) < self.bucket_size:
                # Get oldest peer in the replacement cache (first item)
                replacement_id, timestamp = next(iter(self.replacement_cache.items()))
                self.peers[replacement_id] = timestamp
                del self.replacement_cache[replacement_id]
            
            return True
        return False
        
    def has_peer(self, peer_id: ID) -> bool:
        """Check if the peer is in the bucket."""
        return peer_id in self.peers
    
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
        bucket_size: int = BUCKET_SIZE,
        max_replacement_size: int = REPLACEMENT_CACHE_SIZE
    ):
        """
        Initialize a new routing table.
        
        Args:
            local_peer_id: The ID of the local peer
            bucket_size: Maximum size for each k-bucket
            max_replacement_size: Maximum size for each replacement cache
        """
        self.local_peer_id = local_peer_id
        self.local_key = local_peer_id.to_bytes()
        self.bucket_size = bucket_size
        self.buckets: Dict[int, KBucket] = defaultdict(lambda: KBucket(bucket_size))
    
    def add_peer(self, peer_id: ID) -> bool:
        """
        Add a peer to the routing table.
        
        Args:
            peer_id: The peer ID to add
            
        Returns:
            bool: True if peer was added or updated, False otherwise
        """
        if peer_id == self.local_peer_id:
            return False  # Don't add yourself
            
        peer_key = peer_id.to_bytes()
        prefix_length = shared_prefix_len(self.local_key, peer_key)
        return self.buckets[prefix_length].add_peer(peer_id)
    
    def remove_peer(self, peer_id: ID) -> bool:
        """Remove a peer from the routing table."""
        if peer_id == self.local_peer_id:
            return False
            
        peer_key = peer_id.to_bytes()
        prefix_length = shared_prefix_len(self.local_key, peer_key)
        return self.buckets[prefix_length].remove_peer(peer_id)
    
    def find_closest_peers(self, target_key: bytes, count: int) -> List[ID]:
        """
        Find the closest peers to a target key.
        
        Args:
            target_key: The target key to find neighbors for
            count: The maximum number of peers to return
            
        Returns:
            List[ID]: The closest peers, sorted by distance to the target key
        """
        # Collect all peers from the routing table
        all_peers = []
        for bucket in self.buckets.values():
            all_peers.extend(bucket.peer_ids())
            
        # Sort by distance to the target key and return the closest ones
        return sort_peer_ids_by_distance(target_key, all_peers)[:count]
    
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