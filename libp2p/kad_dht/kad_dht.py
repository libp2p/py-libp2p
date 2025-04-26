"""
Kademlia DHT implementation for py-libp2p.

This module provides a complete Distributed Hash Table (DHT)
implementation based on the Kademlia algorithm and protocol.
"""

import logging
import time
from typing import Dict, List, Optional, Set, Union

import trio
from multiaddr import Multiaddr

from libp2p.abc import IPeerRouting, IContentRouting
from libp2p.abc import IHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.async_service import Service

from .content_routing import ContentRouting
from .peer_routing import PeerRouting
from .routing_table import RoutingTable
from .value_store import ValueStore
from .utils import create_key_from_binary

logger = logging.getLogger("libp2p.kademlia.kad_dht")

# Default parameters
PROTOCOL_ID = "/ipfs/kad/1.0.0"
ROUTING_TABLE_REFRESH_INTERVAL = 1 * 60 * 60  # 1 hour in seconds


class KadDHT(Service):
    """
    Kademlia DHT implementation for libp2p.
    
    This class provides a DHT implementation that combines routing table management,
    peer discovery, content routing, and value storage.
    """
    
    def __init__(self, host: IHost, bootstrap_peers: List[PeerInfo] = None):
        """
        Initialize a new Kademlia DHT node.
        
        Args:
            host: The libp2p host
            bootstrap_peers: Initial peers to bootstrap the routing table
        """
        super().__init__()
        
        self.host = host
        self.local_peer_id = host.get_id()
        
        # Initialize the routing table
        self.routing_table = RoutingTable(self.local_peer_id)
        
        # Initialize peer routing
        self.peer_routing = PeerRouting(host, self.routing_table)
        
        # Initialize content routing
        self.content_routing = ContentRouting(host, self.routing_table)
        
        # Initialize value store
        self.value_store = ValueStore()
        
        # Store bootstrap peers for later use
        self.bootstrap_peers = bootstrap_peers or []
        
        # Set protocol handlers
        host.set_stream_handler(PROTOCOL_ID, self.handle_stream)
        
    async def run(self) -> None:
        """Run the DHT service."""
        logger.info(f"Starting Kademlia DHT with peer ID {self.local_peer_id}")
        
        # Bootstrap the routing table
        if self.bootstrap_peers:
            await self.peer_routing.bootstrap(self.bootstrap_peers)
            
        # Main service loop
        while self.manager.is_running:
            # Periodically refresh the routing table
            await self.refresh_routing_table()
            
            # Republish provider records
            await self.content_routing.republish_providers()
            
            # Clean up expired values
            self.value_store.cleanup_expired()
            
            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)
            
    async def handle_stream(self, stream) -> None:
        """
        Handle an incoming stream.
        
        Args:
            stream: The incoming stream
        """
        # In a complete implementation, this would handle DHT protocol messages
        # For now, just log the incoming connection
        peer_id = stream.conn_id.peer_id
        logger.debug(f"Received DHT stream from peer {peer_id}")
        
        try:
            # This would normally read and process DHT messages
            # For now, just close the stream
            await stream.close()
        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            
    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        await self.peer_routing.refresh_routing_table()
        
    # Peer routing methods
    
    async def find_peer(self, peer_id: ID) -> Optional[PeerInfo]:
        """
        Find a peer with the given ID.
        
        Args:
            peer_id: The ID of the peer to find
            
        Returns:
            Optional[PeerInfo]: The peer information if found, None otherwise
        """
        return await self.peer_routing.find_peer(peer_id)
        
    # Content routing methods
    
    def provide(self, cid: bytes, announce: bool = True) -> None:
        """
        Advertise that this node can provide content with the given CID.
        
        Args:
            cid: The content identifier
            announce: Whether to announce to the network
        """
        self.content_routing.provide(cid, announce)
        
    def find_providers(self, cid: bytes, count: int = 20) -> List[PeerInfo]:
        """
        Find providers for a given content ID.
        
        Args:
            cid: The content identifier
            count: Maximum number of providers to return
            
        Returns:
            List[PeerInfo]: List of provider information
        """
        return list(self.content_routing.find_provider_iter(cid, count))
        
    # Value store methods
    
    def put_value(self, key: bytes, value: bytes, ttl: Optional[int] = None) -> None:
        """
        Store a value in the DHT.
        
        Args:
            key: The key to store the value under
            value: The value to store
            ttl: Time to live in seconds, or None for no expiration
        """
        self.value_store.put(key, value, ttl)
        
    def get_value(self, key: bytes) -> Optional[bytes]:
        """
        Retrieve a value from the DHT.
        
        Args:
            key: The key to look up
            
        Returns:
            Optional[bytes]: The stored value, or None if not found or expired
        """
        local_value = self.value_store.get(key)
        if local_value:
            return local_value
            
        # In a complete implementation, we would query the network here
        return None
        
    # Utility methods
    
    def add_peer(self, peer_id: ID) -> bool:
        """
        Add a peer to the routing table.
        
        Args:
            peer_id: The peer ID to add
            
        Returns:
            bool: True if peer was added or updated, False otherwise
        """
        return self.routing_table.add_peer(peer_id)
        
    def get_routing_table_size(self) -> int:
        """
        Get the number of peers in the routing table.
        
        Returns:
            int: Number of peers
        """
        return self.routing_table.size()
        
    def get_value_store_size(self) -> int:
        """
        Get the number of items in the value store.
        
        Returns:
            int: Number of items
        """
        return self.value_store.size()