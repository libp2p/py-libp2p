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
from .provider_store import ProviderStore, PROVIDER_RECORD_REPUBLISH_INTERVAL
from .utils import create_key_from_binary
from .pb.kademlia_pb2 import Message, Record
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
        
        # Initialize provider store
        self.provider_store = ProviderStore()
        
        # Store bootstrap peers for later use
        self.bootstrap_peers = bootstrap_peers or []
        
        # Track content keys this node is providing
        self._providing_keys: Set[bytes] = set()
        
        # Last time we republished provider records
        self._last_provider_republish = time.time()
        
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
                logger.info("Triggering peer discovery with find_peer %s",self.local_peer_id)
                peers = await self.find_peer(self.local_peer_id)
                logger.info("Peer discovery query completed")
                if peers:
                    logger.info("found peers: %s", peers)
                    for peer in peers:
                        if peer != self.local_peer_id:
                            logger.info("peer id: %s", peer.peer_id)
                            logger.info("peer multiaddress: %s", peer.addrs)
            except Exception as e:
                logger.warning(f"Peer discovery query failed: {e}")
                
            # Check if it's time to republish provider records
            current_time = time.time()
            if current_time - self._last_provider_republish > PROVIDER_RECORD_REPUBLISH_INTERVAL:
                logger.info("Republishing provider records...")
                await self._republish_provider_records()
                self._last_provider_republish = current_time
            
            # Clean up expired values and provider records
            self.value_store.cleanup_expired()
            self.provider_store.cleanup_expired()
            
            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)
            
    async def _republish_provider_records(self) -> None:
        """Republish all provider records for content this node is providing."""
        for key in self._providing_keys:
            logger.info(f"Republishing provider record for key {key.hex()}")
            await self.provide(key)
    
    # Content provider methods
    
    async def provide(self, key: bytes) -> bool:
        """
        Advertise that this node can provide a piece of content.
        
        Finds the k closest peers to the key and sends them ADD_PROVIDER messages.
        
        Args:
            key: The content key (multihash) to advertise
            
        Returns:
            bool: True if the advertisement was successful
        """
        # Add to local provider store
        local_addrs = []
        for addr in self.host.get_addrs():
            local_addrs.append(addr)
        
        local_peer_info = PeerInfo(self.local_peer_id, local_addrs)
        self.provider_store.add_provider(key, local_peer_info)
        
        # Track that we're providing this key
        self._providing_keys.add(key)
        
        # Find the k closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(f"Found {len(closest_peers)} peers close to key {key.hex()} for provider advertisement")
        
        # Send ADD_PROVIDER messages to these peers
        success_count = 0
        for peer_id in closest_peers:
            if peer_id == self.local_peer_id:
                continue
                
            try:
                success = await self._send_add_provider(peer_id, key)
                if success:
                    success_count += 1
            except Exception as e:
                logger.warning(f"Failed to send ADD_PROVIDER to {peer_id}: {e}")
                
        return success_count > 0
        
    async def _send_add_provider(self, peer_id: ID, key: bytes) -> bool:
        """
        Send ADD_PROVIDER message to a specific peer.
        
        Args:
            peer_id: The peer to send the message to
            key: The content key being provided
            
        Returns:
            bool: True if the message was successfully sent and acknowledged
        """
        try:
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            
            try:
                # Get our addresses to include in the message
                addrs = []
                for addr in self.host.get_addrs():
                    addrs.append(addr.to_bytes())
                
                # Create the ADD_PROVIDER message
                message = Message()
                message.type = Message.MessageType.ADD_PROVIDER
                message.key = key
                
                # Add our provider info
                provider = message.providerPeers.add()
                provider.id = self.local_peer_id.to_bytes()
                provider.addrs.extend(addrs)
                
                # Serialize and send the message
                proto_bytes = message.SerializeToString()
                await stream.write(len(proto_bytes).to_bytes(4, byteorder='big'))
                await stream.write(proto_bytes)
                
                # Read response (length prefix)
                length_bytes = await stream.read(4)
                if len(length_bytes) < 4:
                    return False
                    
                response_length = int.from_bytes(length_bytes, byteorder='big')
                
                # Read response data
                response_bytes = await stream.read(response_length)
                if len(response_bytes) < response_length:
                    return False
                    
                # Parse response
                response = Message()
                response.ParseFromString(response_bytes)
                
                # Check response type
                return response.type == Message.MessageType.ADD_PROVIDER
                
            finally:
                await stream.close()
                
        except Exception as e:
            logger.warning(f"Error sending ADD_PROVIDER to {peer_id}: {e}")
            return False
            
    async def find_providers(self, key: bytes, count: int = 20) -> List[PeerInfo]:
        """
        Find content providers for a given key.
        
        Args:
            key: The content key to look for
            count: Maximum number of providers to return
            
        Returns:
            List[PeerInfo]: List of content providers
        """
        # Check local provider store first
        local_providers = self.provider_store.get_providers(key)
        if local_providers:
            logger.info(f"Found {len(local_providers)} providers locally for {key.hex()}")
            return local_providers[:count]
        logger.info("local providers are %s", local_providers)
        # Find the closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(f"Searching {len(closest_peers)} peers for providers of {key.hex()}")
        
        # Query these peers for providers
        all_providers = []
        for peer_id in closest_peers:
            if peer_id == self.local_peer_id:
                continue
                
            try:
                providers = await self._get_providers_from_peer(peer_id, key)
                if providers:
                    # Add providers to our local store
                    for provider in providers:
                        self.provider_store.add_provider(key, provider)
                    
                    # Add to our result list
                    all_providers.extend(providers)
                    
                    # Stop if we've found enough providers
                    if len(all_providers) >= count:
                        break
            except Exception as e:
                logger.warning(f"Failed to get providers from {peer_id}: {e}")
                
        return all_providers[:count]
        
    async def _get_providers_from_peer(self, peer_id: ID, key: bytes) -> List[PeerInfo]:
        """
        Get content providers from a specific peer.
        
        Args:
            peer_id: The peer to query
            key: The content key to look for
            
        Returns:
            List[PeerInfo]: List of provider information
        """
        try:
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            
            try:
                # Create the GET_PROVIDERS message
                message = Message()
                message.type = Message.MessageType.GET_PROVIDERS
                message.key = key
                
                # Serialize and send the message
                proto_bytes = message.SerializeToString()
                await stream.write(len(proto_bytes).to_bytes(4, byteorder='big'))
                await stream.write(proto_bytes)
                
                # Read response (length prefix)
                length_bytes = b""
                remaining = 4
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        return []
                        
                    length_bytes += chunk
                    remaining -= len(chunk)
                    
                response_length = int.from_bytes(length_bytes, byteorder='big')
                
                # Read response data
                response_bytes = b""
                remaining = response_length
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        return []
                        
                    response_bytes += chunk
                    remaining -= len(chunk)
                    
                # Parse response
                response = Message()
                response.ParseFromString(response_bytes)
                
                # Check response type
                if response.type != Message.MessageType.GET_PROVIDERS:
                    return []
                    
                # Extract provider information
                providers = []
                for provider_proto in response.providerPeers:
                    try:
                        # Create peer ID from bytes
                        provider_id = ID(provider_proto.id)
                        
                        # Convert addresses to Multiaddr
                        addrs = []
                        for addr_bytes in provider_proto.addrs:
                            try:
                                addrs.append(Multiaddr(addr_bytes))
                            except:
                                pass  # Skip invalid addresses
                                
                        # Create PeerInfo and add to result
                        providers.append(PeerInfo(provider_id, addrs))
                    except Exception as e:
                        logger.warning(f"Failed to parse provider info: {e}")
                        
                return providers
                
            finally:
                await stream.close()
                
        except Exception as e:
            logger.warning(f"Error getting providers from {peer_id}: {e}")
            return []
            
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
            logger.info(f"Read length prefix1: {length_prefix}")
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
                
            # Try to parse as protobuf first, fall back to JSON if needed
            try:
                # Parse as protobuf
                message = Message()
                message.ParseFromString(msg_bytes)
                logger.info(f"Received DHT protobuf message from {peer_id}, type: {message.type}")
                logger.info("complete message: %s", message)
                
                # Handle FIND_NODE message
                if message.type == Message.MessageType.FIND_NODE:
                    # Get target key directly from protobuf
                    target_key = message.key
                    
                    # Find closest peers to the target key
                    closest_peers = self.routing_table.find_closest_peers(target_key, 20)
                    logger.info(f"Found {len(closest_peers)} peers close to target")
                    
                    # Build response message with protobuf
                    response = Message()
                    response.type = Message.MessageType.FIND_NODE
                    
                    # Add closest peers to response
                    for peer in closest_peers:
                        # Skip if the peer is the requester
                        if peer == peer_id:
                            continue
                        
                        # Add peer to closerPeers field
                        peer_proto = response.closerPeers.add()
                        peer_proto.id = peer.to_bytes()
                        peer_proto.connection = Message.ConnectionType.CAN_CONNECT
                        
                        # Add addresses if available
                        try:
                            addrs = self.host.get_peerstore().addrs(peer)
                            if addrs:
                                for addr in addrs:
                                    peer_proto.addrs.append(addr.to_bytes())
                        except Exception:
                            pass
                    
                    # Serialize and send response
                    response_bytes = response.SerializeToString()
                    await stream.write(len(response_bytes).to_bytes(4, "big"))
                    await stream.write(response_bytes)
                    logger.info(f"Sent protobuf response with {len(response.closerPeers)} peers to {peer_id}")
                
                # Handle ADD_PROVIDER message
                elif message.type == Message.MessageType.ADD_PROVIDER:
                    # Process ADD_PROVIDER
                    key = message.key
                    logger.info(f"Received ADD_PROVIDER for key {key.hex()}")
                    
                    # Extract provider information
                    for provider_proto in message.providerPeers:
                        try:
                            # Validate that the provider is the sender
                            provider_id = ID(provider_proto.id)
                            if provider_id != peer_id:
                                logger.warning(f"Provider ID {provider_id} doesn't match sender {peer_id}, ignoring")
                                continue
                                
                            # Convert addresses to Multiaddr
                            addrs = []
                            for addr_bytes in provider_proto.addrs:
                                try:
                                    addrs.append(Multiaddr(addr_bytes))
                                except Exception as e:
                                    logger.warning(f"Failed to parse address: {e}")
                                    
                            # Add to provider store
                            provider_info = PeerInfo(provider_id, addrs)
                            self.provider_store.add_provider(key, provider_info)
                            logger.info(f"Added provider {provider_id} for key {key.hex()}")
                        except Exception as e:
                            logger.warning(f"Failed to process provider info: {e}")
                            
                    # Send acknowledgement
                    response = Message()
                    response.type = Message.MessageType.ADD_PROVIDER
                    response.key = key
                    
                    response_bytes = response.SerializeToString()
                    await stream.write(len(response_bytes).to_bytes(4, "big"))
                    await stream.write(response_bytes)
                    logger.info(f"Sent ADD_PROVIDER acknowledgement for key {key.hex()}")
                    
                # Handle GET_PROVIDERS message
                elif message.type == Message.MessageType.GET_PROVIDERS:
                    # Process GET_PROVIDERS
                    key = message.key
                    logger.info(f"Received GET_PROVIDERS request for key {key.hex()}")
                    
                    # Find providers for the key
                    providers = self.provider_store.get_providers(key)
                    logger.info(f"Found {len(providers)} providers for key {key.hex()}")
                    
                    # Create response
                    response = Message()
                    response.type = Message.MessageType.GET_PROVIDERS
                    response.key = key
                    
                    # Add provider information to response
                    for provider_info in providers:
                        provider_proto = response.providerPeers.add()
                        provider_proto.id = provider_info.peer_id.to_bytes()
                        provider_proto.connection = Message.ConnectionType.CAN_CONNECT
                        
                        # Add addresses if available
                        for addr in provider_info.addrs:
                            provider_proto.addrs.append(addr.to_bytes())
                            
                    # Also include closest peers if we don't have providers
                    if not providers:
                        closest_peers = self.routing_table.find_closest_peers(key, 20)
                        logger.info(f"No providers found, including {len(closest_peers)} closest peers")
                        
                        for peer in closest_peers:
                            # Skip if peer is the requester
                            if peer == peer_id:
                                continue
                                
                            peer_proto = response.closerPeers.add()
                            peer_proto.id = peer.to_bytes()
                            peer_proto.connection = Message.ConnectionType.CAN_CONNECT
                            
                            # Add addresses if available
                            try:
                                addrs = self.host.get_peerstore().addrs(peer)
                                for addr in addrs:
                                    peer_proto.addrs.append(addr.to_bytes())
                            except Exception:
                                pass
                                
                    # Serialize and send response
                    response_bytes = response.SerializeToString()
                    await stream.write(len(response_bytes).to_bytes(4, "big"))
                    await stream.write(response_bytes)
                    logger.info(f"Sent provider information for key {key.hex()}")
                
                # Handle GET_VALUE message
                elif message.type == Message.MessageType.GET_VALUE:
                    # Process GET_VALUE
                    key = message.key
                    logger.info(f"Received GET_VALUE request for key {key.hex()}")
                    
                    value = self.value_store.get(key)
                    logger.info(f"Retrieved value for key {key.hex()}: {value}")
                    
                    if value:
                        # Create response using protobuf
                        response = Message()
                        response.type = Message.MessageType.GET_VALUE
                        
                        # Create record
                        response.key = key
                        response.record.key = key
                        response.record.value = value
                        response.record.timeReceived = str(time.time())
                        
                        # Serialize and send response
                        response_bytes = response.SerializeToString()
                        await stream.write(len(response_bytes).to_bytes(4, "big"))
                        await stream.write(response_bytes)
                        logger.info(f"Sent value response for key {key.hex()}")
                        
                # Handle PUT_VALUE message
                elif message.type == Message.MessageType.PUT_VALUE and message.HasField('record'):
                    # Process PUT_VALUE
                    key = message.record.key
                    value = message.record.value
                    
                    if key and value:
                        self.value_store.put(key, value)
                        logger.info(f"Stored value for key {key.hex()}")
                        
                        # Send acknowledgement
                        response = Message()
                        response.type = Message.MessageType.PUT_VALUE
                        response.key = key
                        
                        response_bytes = response.SerializeToString()
                        await stream.write(len(response_bytes).to_bytes(4, "big"))
                        await stream.write(response_bytes)
                    else:
                        logger.error("Invalid PUT_VALUE message format")
                        
            except Exception as proto_err:
                logger.warning(f"Failed to parse as protobuf, trying legacy JSON: {proto_err}")
                
                # Fall back to JSON parsing for backward compatibility
                try:
                    message = json.loads(msg_bytes.decode())
                    logger.info(f"Received legacy JSON DHT message from {peer_id}: {message}")
                    
                    # Handle JSON messages (legacy code)
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
                            logger.info(f"Sent JSON response with {len(peer_data)} peers to {peer_id}")
                            
                    elif message.get("type") == "GET_VALUE":
                        # Handle GET_VALUE message (legacy)
                        key = message.get("key")
                        logger.info(f"Received legacy GET_VALUE request for key {key}")
                        if key:
                            value = self.value_store.get(key.encode())
                            logger.info(f"Retrieved value for key {key}: {value}")
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
                                logger.info(f"Sent legacy value response for key {key}")

                    elif message.get("type") == "PUT_VALUE":
                        # Handle PUT_VALUE message (legacy)
                        key = message.get("key")
                        value = message.get("value")
                        if key and value:
                            self.value_store.put(key.encode(), value.encode())
                            logger.info(f"Stored legacy value for key {key}")
                        else:
                            logger.error("Invalid PUT_VALUE message format")
                except Exception as json_err:
                    logger.error(f"Failed to parse message as protobuf or JSON: {json_err}")

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
        try:
            # First check if the peer is in our peerstore
            # try:
            #     addrs = self.host.get_peerstore().addrs(peer_id)
            #     logger.info(f"address of self peer: {addrs}")
            #     if addrs:
            #         logger.debug(f"Found peer {peer_id} in local peerstore")
            #         return PeerInfo(peer_id, addrs)
            # except Exception:
            #     pass
                
            # If not, forward to peer_routing with proper error handling
            
            return await self.peer_routing.find_peer(peer_id)
        except Exception as e:
            logger.warning(f"Error finding peer: {e}")
            return None
    
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
        logger.info("Closest peers for key for retrieving %s: %s", key, closest_peers)
        # 3. Query those peers
        for peer in closest_peers:
            value = await self._get_from_peer(peer, key_bytes)
            logger.info("Found value at peer %s: %s", peer, value)
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
            logger.info(f"Opened stream to peer {peer_id}")

            # Create the PUT_VALUE message with protobuf
            message = Message()
            message.type = Message.MessageType.PUT_VALUE
            
            # Convert key to bytes if it's a string
            key_bytes = key if isinstance(key, bytes) else key.encode()
            
            # Set message fields
            message.key = key_bytes
            message.record.key = key_bytes
            message.record.value = value
            message.record.timeReceived = str(time.time())
            
            # Serialize and send the protobuf message with length prefix
            proto_bytes = message.SerializeToString()
            await stream.write(len(proto_bytes).to_bytes(4, "big"))
            await stream.write(proto_bytes)
            logger.info("Sent PUT_VALUE protobuf message")

            # Read response length (4 bytes)
            length_bytes = await stream.read(4)
            if len(length_bytes) < 4:
                logger.warning("Failed to read response length")
                return False
                
            response_length = int.from_bytes(length_bytes, byteorder='big')
            
            # Read response
            response_bytes = await stream.read(response_length)
            if len(response_bytes) < response_length:
                logger.warning("Failed to read complete response")
                return False
                
            # Parse protobuf response
            response = Message()
            response.ParseFromString(response_bytes)
            
            # Check if response is valid
            if response.type == Message.MessageType.PUT_VALUE:
                logger.debug(f"Successfully stored value at peer {peer_id}")
                return True
                
            return False
            
        except Exception as e:
            logger.warning(f"Failed to store value at peer {peer_id}: {e}")
            return False
            
        finally:
            if stream:
                await stream.close()
            
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
            logger.info(f"Opened stream to peer {peer_id} for GET_VALUE")

            # Create the GET_VALUE message using protobuf
            message = Message()
            message.type = Message.MessageType.GET_VALUE
            
            # Convert key to bytes if it's a string
            key_bytes = key if isinstance(key, bytes) else key.encode()
            message.key = key_bytes
            
            # Serialize and send the protobuf message
            proto_bytes = message.SerializeToString()
            await stream.write(len(proto_bytes).to_bytes(4, "big"))
            await stream.write(proto_bytes)
            
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
                
            # Parse protobuf response
            try:
                response = Message()
                response.ParseFromString(response_bytes)
                logger.info(f"Received protobuf response from peer {peer_id}, type: {response.type}")
                
                # Process protobuf response
                if (response.type == Message.MessageType.GET_VALUE and
                    response.HasField('record') and 
                    response.record.value):
                    logger.debug(f"Received value for key {key_bytes.hex()} from peer {peer_id}")
                    return response.record.value
                    
            except Exception as proto_err:
                # Fall back to JSON for backward compatibility
                logger.warning(f"Failed to parse as protobuf, trying JSON: {proto_err}")
                try:
                    json_response = json.loads(response_bytes.decode())
                    if json_response.get("type") == "VALUE" and "value" in json_response:
                        value = json_response["value"]
                        if isinstance(value, str):
                            value = value.encode()
                        logger.debug(f"Received JSON value for key {key} from peer {peer_id}")
                        return value
                except Exception as json_err:
                    logger.error(f"Failed to parse as JSON too: {json_err}")
                
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
        try:
            # Get addresses from the peerstore if available
            addrs = self.host.get_peerstore().addrs(peer_id)
            if addrs:
                # Create PeerInfo object and add to routing table
                peer_info = PeerInfo(peer_id, addrs)
                return self.routing_table.add_peer(peer_info)
            else:
                logger.warning(f"No addresses found for peer {peer_id}, cannot add to routing table")
                return False
        except Exception as e:
            logger.warning(f"Error adding peer {peer_id} to routing table: {e}")
            return False
        
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