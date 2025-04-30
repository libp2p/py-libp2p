"""
Kademlia DHT implementation for py-libp2p.

This module provides a complete Distributed Hash Table (DHT)
implementation based on the Kademlia algorithm and protocol.
"""

import logging
import time
import json
from typing import Dict, List, Optional, Set, Union

import trio
from multiaddr import Multiaddr

from libp2p.abc import IHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.async_service import Service

from .peer_routing import PeerRouting
from .routing_table import RoutingTable
from .value_store import ValueStore
from .utils import create_key_from_binary
from libp2p.network.stream.net_stream import (
    INetStream,
)

logger = logging.getLogger("libp2p.kademlia.kad_dht")

# Default parameters
PROTOCOL_ID = "/ipfs/kad/1.0.0"
ROUTING_TABLE_REFRESH_INTERVAL = 1 * 60 # 1 min in seconds for testing


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

            # Connect to all known peers
            logger.info("Connecting to all known peers...")
            await self.connect_to_all_known_peers()

            # Actively trigger peer discovery by querying for our own ID
            try:
                logger.info("Triggering peer discovery with find_peer(self.local_peer_id)")
                await self.find_peer(self.local_peer_id)
            except Exception as e:
                logger.warning(f"Peer discovery query failed: {e}")
            
            # Clean up expired values
            self.value_store.cleanup_expired()
            
            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)
            
    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming stream.

        Args:
            stream: The incoming stream
        """

        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Received DHT stream from peer {peer_id}")
        self.add_peer(peer_id)
        logger.info(f"Added peer {peer_id} to routing table")
        try:
            # Read 4 bytes for the length prefix
            length_prefix = await stream.read(4)
            if len(length_prefix) < 4:
                logger.error("Failed to read length prefix from stream")
                await stream.close()
                return
            msg_length = int.from_bytes(length_prefix, "big")
            # Read the message bytes
            msg_bytes = await stream.read(msg_length)
            if len(msg_bytes) < msg_length:
                logger.error("Failed to read full message from stream")
                await stream.close()
                return
            # Decode the message (assuming JSON)
            try:
                message = json.loads(msg_bytes.decode())
                logger.info(f"Received DHT message from {peer_id}: {message}")
                # Here you could add further processing of the message
            except Exception as decode_err:
                logger.error(f"Failed to decode DHT message: {decode_err}")
            
            if message.get("type") == "FIND_NODE":
                # Handle FIND_NODE message
                target = message.get("target")
                if target:
                    # Convert hex target to bytes
                    target_key = bytes.fromhex(target)
                    # Find closest peers to the target key
                    closest_peers = self.routing_table.find_closest_peers(target_key, 20)
                    
                    # Format response with peer information
                    peer_data = []
                    for peer in closest_peers:
                        # Skip if the peer is the requester
                        if peer == peer_id:
                            continue
                            
                        peer_info = {
                            "id": peer.to_bytes().hex()
                        }
                        
                        # Add addresses if available
                        try:
                            addrs = self.host.get_peerstore().addrs(peer)
                            if addrs:
                                peer_info["addrs"] = [str(addr) for addr in addrs]
                        except Exception:
                            pass
                            
                        peer_data.append(peer_info)
                    
                    # Create and send response
                    response = {
                        "type": "FIND_NODE_RESPONSE",
                        "peers": peer_data
                    }
                    response_bytes = json.dumps(response).encode()
                    await stream.write(len(response_bytes).to_bytes(4, "big"))
                    await stream.write(response_bytes)
                    logger.info(f"Sent {len(peer_data)} closest peers to {peer_id}")
                    
            elif message.get("type") == "GET_VALUE":
                # Handle GET_VALUE message
                key = message.get("key")
                if key:
                    value = self.value_store.get(key)
                    if value:
                        response = {
                            "type": "VALUE",
                            "key": key,
                            "value": value.decode(),
                        }
                        response_bytes = json.dumps(response).encode()
                        await stream.write(len(response_bytes).to_bytes(4, "big") + response_bytes)
                    else:
                        logger.info(f"Value for key {key} not found")

            elif message.get("type") == "PUT_VALUE":
                # Handle PUT_VALUE message
                key = message.get("key")
                value = message.get("value")
                if key and value:
                    self.value_store.put(key.encode(), value.encode())
                    logger.info(f"Stored value for key {key}")
                else:
                    logger.error("Invalid PUT_VALUE message format")

            await stream.close()
        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            await stream.close()
            logger.info(f"Closed stream with peer {peer_id}")

    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        logger.info("Refreshing routing table1...")
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
    
    async def connect_to_all_known_peers(self):
        """
        Attempt to connect to all peers currently in the routing table.
        """
        logger.info("Connecting to all known peers method...")
        peer_ids = self.routing_table.get_peer_ids()
        for peer_id in peer_ids:
            if peer_id == self.local_peer_id:
                continue
            try:
                # Try to get PeerInfo from the peerstore
                peerstore = getattr(self.host, "get_peerstore", None)
                if peerstore:
                    addrs = self.host.get_peerstore().addrs(peer_id)
                    if addrs:
                        peer_info = PeerInfo(peer_id, addrs)
                        await self.host.connect(peer_info)
                        logger.info(f"Connected to discovered peer: {peer_id.pretty()}")
            except Exception as e:
                logger.debug(f"Failed to connect to peer {peer_id}: {e}")
            
        

        
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