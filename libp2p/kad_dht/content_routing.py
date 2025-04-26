"""
Content routing implementation for Kademlia DHT.

This module provides functionality to advertise and find content providers
in a distributed network using Kademlia's algorithm.
"""

import logging
import time
from typing import Dict, Iterable, List, Optional, Set

import trio

from libp2p.abc import IContentRouting, IHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from .routing_table import RoutingTable
from .utils import create_key_from_binary

logger = logging.getLogger("libp2p.kademlia.content_routing")

# Constants
PROVIDER_RECORD_TTL = 24 * 60 * 60  # 24 hours in seconds
REPUBLISH_INTERVAL = 12 * 60 * 60  # 12 hours in seconds
MAX_PROVIDERS_PER_KEY = 20


class ProviderRecord:
    """A record of a provider for a given content ID."""
    
    def __init__(self, provider_id: ID, timestamp: float = None):
        """
        Initialize a provider record.
        
        Args:
            provider_id: ID of the provider peer
            timestamp: Time when the record was created or updated
        """
        self.provider_id = provider_id
        self.timestamp = timestamp or time.time()
        
    def is_expired(self) -> bool:
        """Check if this provider record has expired."""
        return time.time() > self.timestamp + PROVIDER_RECORD_TTL
        
    def touch(self) -> None:
        """Update the timestamp of this record."""
        self.timestamp = time.time()


class ContentRouting(IContentRouting):
    """
    Implementation of content routing for Kademlia DHT.
    
    This class provides methods to advertise and find content providers
    in the distributed network.
    """
    
    def __init__(self, host: IHost, routing_table: RoutingTable):
        """
        Initialize the content routing service.
        
        Args:
            host: The libp2p host
            routing_table: The Kademlia routing table
        """
        self.host = host
        self.routing_table = routing_table
        self.local_peer_id = host.get_id()
        
        # Mapping from content ID to set of provider records
        self.providers: Dict[bytes, Dict[ID, ProviderRecord]] = {}
        
        # Set of content IDs that we are providing
        self.providing: Set[bytes] = set()
        
        # Protocol identifier for provider messages
        self.protocol_id = "/ipfs/kad/1.0.0"
    
    def provide(self, cid: bytes, announce: bool = True) -> None:
        """
        Advertise that this node can provide content with the given CID.
        
        Args:
            cid: The content identifier
            announce: Whether to announce to the network
        """
        logger.debug(f"Providing content {cid.hex()[:8]}...")
        
        # Store locally that we're providing this content
        self.providing.add(cid)
        
        # Add ourselves to the local providers list
        if cid not in self.providers:
            self.providers[cid] = {}
            
        self.providers[cid][self.local_peer_id] = ProviderRecord(self.local_peer_id)
        
        # If announce is True, we'd normally broadcast to the network here
        if announce:
            # This would normally trigger a background task to announce to the network
            logger.debug(f"Announcing provider for {cid.hex()[:8]}...")
    
    def find_provider_iter(self, cid: bytes, count: int) -> Iterable[PeerInfo]:
        """
        Find providers for a given content ID.
        
        Args:
            cid: The content identifier
            count: Maximum number of providers to return
            
        Returns:
            Iterable[PeerInfo]: Iterator of provider information
        """
        # Check local providers first
        local_providers = self._get_local_providers(cid, count)
        yield from local_providers
        
        # If we got enough local providers, we're done
        if len(local_providers) >= count:
            return
            
        # In a complete implementation, we would query the network here
        
    def _get_local_providers(self, cid: bytes, max_count: int) -> List[PeerInfo]:
        """
        Get providers from our local provider store.
        
        Args:
            cid: The content identifier
            max_count: Maximum number of providers to return
            
        Returns:
            List[PeerInfo]: List of provider information
        """
        providers_list = []
        
        if cid in self.providers:
            provider_records = self.providers[cid]
            
            # Clean up expired providers
            expired = [pid for pid, record in provider_records.items() 
                      if record.is_expired()]
            for pid in expired:
                del provider_records[pid]
                
            # Convert provider IDs to PeerInfo objects
            for provider_id in list(provider_records.keys())[:max_count]:
                # Skip if we don't have the peer's addresses
                try:
                    addrs = self.host.get_peerstore().addrs(provider_id)
                    if addrs:
                        providers_list.append(PeerInfo(provider_id, addrs))
                except Exception:
                    pass
                    
        return providers_list
        
    def add_provider(self, cid: bytes, provider_id: ID) -> None:
        """
        Add a provider for a content ID.
        
        Args:
            cid: The content identifier
            provider_id: ID of the provider peer
        """
        if cid not in self.providers:
            self.providers[cid] = {}
            
        # If we have too many providers, remove the oldest one
        if len(self.providers[cid]) >= MAX_PROVIDERS_PER_KEY:
            oldest_id = None
            oldest_time = float('inf')
            
            for pid, record in self.providers[cid].items():
                if record.timestamp < oldest_time:
                    oldest_time = record.timestamp
                    oldest_id = pid
                    
            if oldest_id:
                del self.providers[cid][oldest_id]
                
        # Add or update the provider record
        self.providers[cid][provider_id] = ProviderRecord(provider_id)
        
    async def republish_providers(self) -> None:
        """Republish all content that this node is providing."""
        logger.debug(f"Republishing {len(self.providing)} provider records")
        
        for cid in self.providing:
            self.provide(cid, announce=True)
            
        # In a real implementation, we would wait for REPUBLISH_INTERVAL
        # and call this method again
        
    def stop_providing(self, cid: bytes) -> None:
        """
        Stop providing content with the given CID.
        
        Args:
            cid: The content identifier to stop providing
        """
        if cid in self.providing:
            self.providing.remove(cid)
            
        if cid in self.providers and self.local_peer_id in self.providers[cid]:
            del self.providers[cid][self.local_peer_id]