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
            logger.info(f"Read length prefix: {length_prefix}")
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
                logger.info(f"Received GET_VALUE request for key {key}")
                if key:
                    value = self.value_store.get(key)
                    if value:
                        response = {
                            "type": "VALUE",
                            "key": key,
                            "value": value.decode(),
                        }
                        response_bytes = json.dumps(response).encode()
                        # Send length prefix SEPARATELY from data
                        await stream.write(len(response_bytes).to_bytes(4, "big"))
                        await stream.write(response_bytes)
                        logger.info(f"Sent value response for key {key}")

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
            
        
    async def put_value(self, key: Union[str, bytes], value: bytes) -> None:
        """
        Store a value in the DHT.
        
        Args:
            key: The key to store (string or bytes)
            value: The value to store
        """
        # Check key type and convert if needed
        key_bytes = key if isinstance(key, bytes) else key.encode()
        
        # 1. Find peers closest to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key_bytes)
        logger.info(f"Closest peers for key for storing {key}: {closest_peers}")

        # 2. Store locally and at those peers
        self.value_store.put(key, value)
        logger.info(f"Stored value for key {key} locally1")
        
        # 3. Store at remote peers
        for peer in closest_peers:
            await self._store_at_peer(peer, key, value)
            
    async def get_value(self, key: str) -> Optional[bytes]:
        """Retrieve a value from the DHT."""

        # Check key type and convert if needed
        key_bytes = key if isinstance(key, bytes) else key.encode()

        # 1. Check local store first
        local_value = self.value_store.get(key_bytes)
        if local_value:
            return local_value
            
        # 2. Not found locally, search the network
        closest_peers = await self.peer_routing.find_closest_peers_network(key_bytes)
        
        # 3. Query those peers
        for peer in closest_peers:
            value = await self._get_from_peer(peer, key_bytes)
            if value:
                # Store for future use
                self.value_store.put(key_bytes, value)
                return value
                
    # Add these methods in the Utility methods section

    async def _store_at_peer(self, peer_id: ID, key: str, value: bytes) -> bool:
        """
        Store a value at a specific peer.
        
        Args:
            peer_id: The ID of the peer to store the value at
            key: The key to store
            value: The value to store
            
        Returns:
            bool: True if the value was successfully stored, False otherwise
        """
        try:
            # Don't try to store at ourselves
            if peer_id == self.local_peer_id:
                return True
                
            logger.info(f"Storing value for key {key} at peer {peer_id}")
            
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            logger.info(f"Opened stream to peer1 {peer_id}")

            # Create the PUT_VALUE message
            message = {
            "type": "PUT_VALUE",
            "key": key.hex() if isinstance(key, bytes) else key,  # Convert bytes key to hex string
            "value": value.decode() if isinstance(value, bytes) else value
            }
            message_bytes = json.dumps(message).encode()
            
            # Send the message
            await stream.write(len(message_bytes).to_bytes(4, "big"))
            await stream.write(message_bytes)
            logger.info("Sent PUT_VALUE message")

            # Close the stream
            await stream.close()
            logger.debug(f"Successfully stored value at peer {peer_id}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to store value at peer {peer_id}: {e}")
            return False
            
    async def _get_from_peer(self, peer_id: ID, key: str) -> Optional[bytes]:
        """
        Retrieve a value from a specific peer.
        
        Args:
            peer_id: The ID of the peer to retrieve the value from
            key: The key to retrieve
            
        Returns:
            Optional[bytes]: The value if found, None otherwise
        """
        stream = None
        try:
            # Don't try to get from ourselves
            if peer_id == self.local_peer_id:
                return None
                
            logger.info(f"Getting value for key {key} from peer {peer_id}")
            
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            
            # Create the GET_VALUE message
            message = {
                "type": "GET_VALUE",
                "key": key
            }
            message_bytes = json.dumps(message).encode()
            
            # Send the message
            await stream.write(len(message_bytes).to_bytes(4, "big"))
            await stream.write(message_bytes)
            
            # Read response length (4 bytes)
            length_bytes = b""
            remaining = 4
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(f"Connection closed by peer {peer_id} while reading length")
                    return None
                    
                length_bytes += chunk
                remaining -= len(chunk)
                
            response_length = int.from_bytes(length_bytes, byteorder='big')
            
            # Read response data
            response_bytes = b""
            remaining = response_length
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(f"Connection closed by peer {peer_id} while reading data")
                    return None
                    
                response_bytes += chunk
                remaining -= len(chunk)
                
            # Parse response
            response = json.loads(response_bytes.decode())
            logger.info(f"Received response from peer {peer_id}: {response}")

            # Process response
            if response.get("type") == "VALUE" and "value" in response:
                value = response["value"]
                if isinstance(value, str):
                    value = value.encode()
                logger.debug(f"Received value for key {key} from peer {peer_id}")
                return value
                
            return None
            
        except Exception as e:
            logger.warning(f"Failed to get value from peer {peer_id}: {e}")
            return None
            
        finally:
            if stream:
                await stream.close()
        
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