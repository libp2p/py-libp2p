"""
Kademlia DHT implementation for py-libp2p.

This module provides a complete Distributed Hash Table (DHT)
implementation based on the Kademlia algorithm and protocol.
"""

import logging
import time
from typing import (
    Optional,
)

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    IHost,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.tools.async_service import (
    Service,
)

from .pb.kademlia_pb2 import (
    Message,
)
from .peer_routing import (
    PeerRouting,
)
from .provider_store import (
    ProviderStore,
)
from .routing_table import (
    RoutingTable,
)
from .value_store import (
    ValueStore,
)

logger = logging.getLogger("libp2p.kademlia.kad_dht")

# Default parameters
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")
ROUTING_TABLE_REFRESH_INTERVAL = 1 * 60  # 1 min in seconds for testing
TTL = 24 * 60 * 60  # 24 hours in seconds


class KadDHT(Service):
    """
    Kademlia DHT implementation for libp2p.

    This class provides a DHT implementation that combines routing table management,
    peer discovery, content routing, and value storage.
    """

    def __init__(self, host: IHost, bootstrap_peers: list[PeerInfo] = None):
        """
        Initialize a new Kademlia DHT node.

        :param host: The libp2p host.
        :param bootstrap_peers: Initial peers to bootstrap the routing table.

        """
        super().__init__()

        self.host = host
        self.local_peer_id = host.get_id()

        # Initialize the routing table
        self.routing_table = RoutingTable(self.local_peer_id, self.host)

        # Initialize peer routing
        self.peer_routing = PeerRouting(host, self.routing_table)

        # Initialize value store
        self.value_store = ValueStore(host=host, local_peer_id=self.local_peer_id)

        # Initialize provider store with host and peer_routing references
        self.provider_store = ProviderStore(host=host, peer_routing=self.peer_routing)

        # Store bootstrap peers for later use
        self.bootstrap_peers = bootstrap_peers or []

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

            # Check if it's time to republish provider records
            current_time = time.time()
            # await self._republish_provider_records()
            self._last_provider_republish = current_time

            # Clean up expired values and provider records
            self.value_store.cleanup_expired()
            self.provider_store.cleanup_expired()

            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming stream.

        Args:
        ----
        stream: The incoming stream.

        Returns
        -------
        None

        """
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Received DHT stream from peer {peer_id}")
        # Call the async method properly with await
        await self.add_peer(peer_id)
        logger.info(f"Added peer {peer_id} to routing table")
        try:
            # Read 4 bytes for the length prefix
            length_prefix = await stream.read(4)
            logger.info(f"Read length prefix1: {length_prefix.decode()}")
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

            try:
                # Parse as protobuf
                message = Message()
                message.ParseFromString(msg_bytes)
                logger.info(
                    f"Received DHT protobuf message"
                    f" from {peer_id}, type: {message.type}"
                )
                logger.info("complete message: %s", message)

                # Handle FIND_NODE message
                if message.type == Message.MessageType.FIND_NODE:
                    # Get target key directly from protobuf
                    target_key = message.key

                    # Find closest peers to the target key
                    closest_peers = self.routing_table.find_local_closest_peers(
                        target_key, 20
                    )
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
                    logger.info(
                        f"Sent protobuf response with"
                        f" {len(response.closerPeers)} peers to {peer_id}"
                    )

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
                                logger.warning(
                                    f"Provider ID {provider_id} doesn't match"
                                    f" sender {peer_id}, ignoring"
                                )
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
                            logger.info(
                                f"Added provider {provider_id} for key {key.hex()}"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to process provider info: {e}")

                    # Send acknowledgement
                    response = Message()
                    response.type = Message.MessageType.ADD_PROVIDER
                    response.key = key

                    response_bytes = response.SerializeToString()
                    await stream.write(len(response_bytes).to_bytes(4, "big"))
                    await stream.write(response_bytes)
                    logger.info(
                        f"Sent ADD_PROVIDER acknowledgement for key {key.hex()}"
                    )

                # Handle GET_PROVIDERS message
                elif message.type == Message.MessageType.GET_PROVIDERS:
                    # Process GET_PROVIDERS
                    key = message.key
                    logger.info(f"Received GET_PROVIDERS request for key {key.hex()}")

                    # Find providers for the key
                    providers = self.provider_store.get_providers(key)
                    logger.info(
                        "Found %d providers for key %s",
                        len(providers),
                        key.hex(),
                    )

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
                        closest_peers = self.routing_table.find_local_closest_peers(
                            key, 20
                        )
                        logger.info(
                            "No providers found, including %d closest peers",
                            len(closest_peers),
                        )

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
                    logger.debug(f"Received GET_VALUE request for key {key.hex()}")

                    value = self.value_store.get(key)
                    logger.debug(f"Retrieved value for key {key.hex()}: {value.hex()}")

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
                elif message.type == Message.MessageType.PUT_VALUE and message.HasField(
                    "record"
                ):
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
                logger.warning(
                    f"Failed to parse as protobuf {proto_err}"
                )

            await stream.close()
        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            await stream.close()
            logger.info(f"Closed stream with peer {peer_id}")

    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        await self.peer_routing.refresh_routing_table()

    # Peer routing methods

    async def find_peer(self, peer_id: ID) -> Optional[PeerInfo]:
        """
        Find a peer with the given ID.

        Args:
        ----
        peer_id: The ID of the peer to find.

        Returns
        -------
        Optional[PeerInfo]
            The peer information if found, None otherwise.

        """
        return await self.peer_routing.find_peer(peer_id)

    # Value storage and retrieval methods

    async def put_value(self, key: bytes, value: bytes) -> None:
        """
        Store a value in the DHT.

        Args:
        ----
        key: The key to store (string or bytes).
        value: The value to store.

        Returns
        -------
        None

        """
        # 1. Find peers closest to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(
            "Closest peers for key for storing %s: %s",
            key,
            closest_peers,
        )

        # 2. Store locally and at those peers
        self.value_store.put(key, value)
        logger.info(f"Stored value for key {key.hex()} locally")

        # 3. Store at remote peers
        for peer in closest_peers:
            await self.value_store._store_at_peer(peer, key, value)

    async def get_value(self, key: bytes) -> Optional[bytes]:
        """
        Retrieve a value from the DHT.

        Args:
        ----
        key: The key to retrieve.

        Returns
        -------
        Optional[bytes]
            The value if found, None otherwise.

        """
        # 1. Check local store first
        local_value = self.value_store.get(key)
        if local_value:
            return local_value

        # 2. Not found locally, search the network
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(
            "Closest peers for key for retrieving %s: %s",
            key,
            closest_peers,
        )
        # 3. Query those peers
        for peer in closest_peers:
            value = await self.value_store._get_from_peer(peer, key)
            logger.info(
                "Found value at peer %s: %s",
                peer,
                value,
            )
            if value:
                # Store for future use
                self.value_store.put(key, value)
                return value
        return None

    # Add these methods in the Utility methods section

    # Utility methods

    async def add_peer(self, peer_id: ID) -> bool:
        """
        Add a peer to the routing table.

        Args:
        ----
        peer_id: The peer ID to add.

        Returns
        -------
        bool
            True if peer was added or updated, False otherwise.

        """
        return await self.routing_table.add_peer(peer_id)

    def get_routing_table_size(self) -> int:
        """
        Get the number of peers in the routing table.

        Returns
        -------
        int
            Number of peers.

        """
        return self.routing_table.size()

    def get_value_store_size(self) -> int:
        """
        Get the number of items in the value store.

        Returns
        -------
        int
            Number of items.

        """
        return self.value_store.size()
