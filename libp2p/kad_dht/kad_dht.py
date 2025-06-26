"""
Kademlia DHT implementation for py-libp2p.

This module provides a complete Distributed Hash Table (DHT)
implementation based on the Kademlia algorithm and protocol.
"""

from enum import (
    Enum,
)
import logging
import time

from multiaddr import (
    Multiaddr,
)
import trio
import varint

from libp2p.abc import (
    IHost,
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

from .common import (
    ALPHA,
    PROTOCOL_ID,
    QUERY_TIMEOUT,
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

logger = logging.getLogger("kademlia-example.kad_dht")
# logger = logging.getLogger("libp2p.kademlia")
# Default parameters
ROUTING_TABLE_REFRESH_INTERVAL = 60  # 1 min in seconds for testing


class DHTMode(Enum):
    """DHT operation modes."""

    CLIENT = "CLIENT"
    SERVER = "SERVER"


class KadDHT(Service):
    """
    Kademlia DHT implementation for libp2p.

    This class provides a DHT implementation that combines routing table management,
    peer discovery, content routing, and value storage.
    """

    def __init__(self, host: IHost, mode: DHTMode):
        """
        Initialize a new Kademlia DHT node.

        :param host: The libp2p host.
        :param mode: The mode of host (Client or Server) - must be DHTMode enum
        """
        super().__init__()

        self.host = host
        self.local_peer_id = host.get_id()

        # Validate that mode is a DHTMode enum
        if not isinstance(mode, DHTMode):
            raise TypeError(f"mode must be DHTMode enum, got {type(mode)}")

        self.mode = mode

        # Initialize the routing table
        self.routing_table = RoutingTable(self.local_peer_id, self.host)

        # Initialize peer routing
        self.peer_routing = PeerRouting(host, self.routing_table)

        # Initialize value store
        self.value_store = ValueStore(host=host, local_peer_id=self.local_peer_id)

        # Initialize provider store with host and peer_routing references
        self.provider_store = ProviderStore(host=host, peer_routing=self.peer_routing)

        # Last time we republished provider records
        self._last_provider_republish = time.time()

        # Set protocol handlers
        host.set_stream_handler(PROTOCOL_ID, self.handle_stream)

    async def run(self) -> None:
        """Run the DHT service."""
        logger.info(f"Starting Kademlia DHT with peer ID {self.local_peer_id}")

        # Main service loop
        while self.manager.is_running:
            # Periodically refresh the routing table
            await self.refresh_routing_table()

            # Check if it's time to republish provider records
            current_time = time.time()
            # await self._republish_provider_records()
            self._last_provider_republish = current_time

            # Clean up expired values and provider records
            expired_values = self.value_store.cleanup_expired()
            if expired_values > 0:
                logger.debug(f"Cleaned up {expired_values} expired values")

            self.provider_store.cleanup_expired()

            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)

    async def switch_mode(self, new_mode: DHTMode) -> DHTMode:
        """
        Switch the DHT mode.

        :param new_mode: The new mode - must be DHTMode enum
        :return: The new mode as DHTMode enum
        """
        # Validate that new_mode is a DHTMode enum
        if not isinstance(new_mode, DHTMode):
            raise TypeError(f"new_mode must be DHTMode enum, got {type(new_mode)}")

        if new_mode == DHTMode.CLIENT:
            self.routing_table.cleanup_routing_table()
        self.mode = new_mode
        logger.info(f"Switched to {new_mode.value} mode")
        return self.mode

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming DHT stream using varint length prefixes.
        """
        if self.mode == DHTMode.CLIENT:
            stream.close
            return
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Received DHT stream from peer {peer_id}")
        await self.add_peer(peer_id)
        logger.debug(f"Added peer {peer_id} to routing table")

        try:
            # Read varint-prefixed length for the message
            length_prefix = b""
            while True:
                byte = await stream.read(1)
                if not byte:
                    logger.warning("Stream closed while reading varint length")
                    await stream.close()
                    return
                length_prefix += byte
                if byte[0] & 0x80 == 0:
                    break
            msg_length = varint.decode_bytes(length_prefix)

            # Read the message bytes
            msg_bytes = await stream.read(msg_length)
            if len(msg_bytes) < msg_length:
                logger.warning("Failed to read full message from stream")
                await stream.close()
                return

            try:
                # Parse as protobuf
                message = Message()
                message.ParseFromString(msg_bytes)
                logger.debug(
                    f"Received DHT message from {peer_id}, type: {message.type}"
                )

                # Handle FIND_NODE message
                if message.type == Message.MessageType.FIND_NODE:
                    # Get target key directly from protobuf
                    target_key = message.key

                    # Find closest peers to the target key
                    closest_peers = self.routing_table.find_local_closest_peers(
                        target_key, 20
                    )
                    logger.debug(f"Found {len(closest_peers)} peers close to target")

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
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)
                    logger.debug(
                        f"Sent FIND_NODE response with{len(response.closerPeers)} peers"
                    )

                # Handle ADD_PROVIDER message
                elif message.type == Message.MessageType.ADD_PROVIDER:
                    # Process ADD_PROVIDER
                    key = message.key
                    logger.debug(f"Received ADD_PROVIDER for key {key.hex()}")

                    # Extract provider information
                    for provider_proto in message.providerPeers:
                        try:
                            # Validate that the provider is the sender
                            provider_id = ID(provider_proto.id)
                            if provider_id != peer_id:
                                logger.warning(
                                    f"Provider ID {provider_id} doesn't"
                                    f"match sender {peer_id}, ignoring"
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
                            logger.debug(
                                f"Added provider {provider_id} for key {key.hex()}"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to process provider info: {e}")

                    # Send acknowledgement
                    response = Message()
                    response.type = Message.MessageType.ADD_PROVIDER
                    response.key = key

                    response_bytes = response.SerializeToString()
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)
                    logger.debug("Sent ADD_PROVIDER acknowledgement")

                # Handle GET_PROVIDERS message
                elif message.type == Message.MessageType.GET_PROVIDERS:
                    # Process GET_PROVIDERS
                    key = message.key
                    logger.debug(f"Received GET_PROVIDERS request for key {key.hex()}")

                    # Find providers for the key
                    providers = self.provider_store.get_providers(key)
                    logger.debug(
                        f"Found {len(providers)} providers for key {key.hex()}"
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
                        logger.debug(
                            f"No providers found, including {len(closest_peers)}"
                            "closest peers"
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
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)
                    logger.debug("Sent GET_PROVIDERS response")

                # Handle GET_VALUE message
                elif message.type == Message.MessageType.GET_VALUE:
                    # Process GET_VALUE
                    key = message.key
                    logger.debug(f"Received GET_VALUE request for key {key.hex()}")

                    value = self.value_store.get(key)
                    if value:
                        logger.debug(f"Found value for key {key.hex()}")

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
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug("Sent GET_VALUE response")
                    else:
                        logger.debug(f"No value found for key {key.hex()}")

                        # Create response with closest peers when no value is found
                        response = Message()
                        response.type = Message.MessageType.GET_VALUE
                        response.key = key

                        # Add closest peers to key
                        closest_peers = self.routing_table.find_local_closest_peers(
                            key, 20
                        )
                        logger.debug(
                            "No value found,"
                            f"including {len(closest_peers)} closest peers"
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
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug("Sent GET_VALUE response with closest peers")

                # Handle PUT_VALUE message
                elif message.type == Message.MessageType.PUT_VALUE and message.HasField(
                    "record"
                ):
                    # Process PUT_VALUE
                    key = message.record.key
                    value = message.record.value
                    success = False
                    try:
                        if not (key and value):
                            raise ValueError(
                                "Missing key or value in PUT_VALUE message"
                            )

                        self.value_store.put(key, value)
                        logger.debug(f"Stored value {value.hex()} for key {key.hex()}")
                        success = True
                    except Exception as e:
                        logger.warning(
                            f"Failed to store value {value.hex()} for key "
                            f"{key.hex()}: {e}"
                        )
                    finally:
                        # Send acknowledgement
                        response = Message()
                        response.type = Message.MessageType.PUT_VALUE
                        if success:
                            response.key = key
                        response_bytes = response.SerializeToString()
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug("Sent PUT_VALUE acknowledgement")

            except Exception as proto_err:
                logger.warning(f"Failed to parse protobuf message: {proto_err}")

            await stream.close()
        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            await stream.close()

    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        logger.debug("Refreshing routing table")
        await self.peer_routing.refresh_routing_table()

    # Peer routing methods

    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        """
        Find a peer with the given ID.
        """
        logger.debug(f"Finding peer: {peer_id}")
        return await self.peer_routing.find_peer(peer_id)

    # Value storage and retrieval methods

    async def put_value(self, key: bytes, value: bytes) -> None:
        """
        Store a value in the DHT.
        """
        logger.debug(f"Storing value for key {key.hex()}")

        # 1. Store locally first
        self.value_store.put(key, value)
        try:
            decoded_value = value.decode("utf-8")
        except UnicodeDecodeError:
            decoded_value = value.hex()
        logger.debug(
            f"Stored value locally for key {key.hex()} with value {decoded_value}"
        )

        # 2. Get closest peers, excluding self
        closest_peers = [
            peer
            for peer in self.routing_table.find_local_closest_peers(key)
            if peer != self.local_peer_id
        ]
        logger.debug(f"Found {len(closest_peers)} peers to store value at")

        # 3. Store at remote peers in batches of ALPHA, in parallel
        stored_count = 0
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]
            batch_results = [False] * len(batch)

            async def store_one(idx: int, peer: ID) -> None:
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        success = await self.value_store._store_at_peer(
                            peer, key, value
                        )
                        batch_results[idx] = success
                        if success:
                            logger.debug(f"Stored value at peer {peer}")
                        else:
                            logger.debug(f"Failed to store value at peer {peer}")
                except Exception as e:
                    logger.debug(f"Error storing value at peer {peer}: {e}")

            async with trio.open_nursery() as nursery:
                for idx, peer in enumerate(batch):
                    nursery.start_soon(store_one, idx, peer)

            stored_count += sum(batch_results)

        logger.info(f"Successfully stored value at {stored_count} peers")

    async def get_value(self, key: bytes) -> bytes | None:
        logger.debug(f"Getting value for key: {key.hex()}")

        # 1. Check local store first
        value = self.value_store.get(key)
        if value:
            logger.debug("Found value locally")
            return value

        # 2. Get closest peers, excluding self
        closest_peers = [
            peer
            for peer in self.routing_table.find_local_closest_peers(key)
            if peer != self.local_peer_id
        ]
        logger.debug(f"Searching {len(closest_peers)} peers for value")

        # 3. Query ALPHA peers at a time in parallel
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]
            found_value = None

            async def query_one(peer: ID) -> None:
                nonlocal found_value
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        value = await self.value_store._get_from_peer(peer, key)
                        if value is not None and found_value is None:
                            found_value = value
                            logger.debug(f"Found value at peer {peer}")
                except Exception as e:
                    logger.debug(f"Error querying peer {peer}: {e}")

            async with trio.open_nursery() as nursery:
                for peer in batch:
                    nursery.start_soon(query_one, peer)

            if found_value is not None:
                self.value_store.put(key, found_value)
                logger.info("Successfully retrieved value from network")
                return found_value

        # 4. Not found
        logger.warning(f"Value not found for key {key.hex()}")
        return None

    # Add these methods in the Utility methods section

    # Utility methods

    async def add_peer(self, peer_id: ID) -> bool:
        """
        Add a peer to the routing table.

        params: peer_id: The peer ID to add.

        Returns
        -------
        bool
            True if peer was added or updated, False otherwise.

        """
        return await self.routing_table.add_peer(peer_id)

    async def provide(self, key: bytes) -> bool:
        """
        Reference to provider_store.provide for convenience.
        """
        return await self.provider_store.provide(key)

    async def find_providers(self, key: bytes, count: int = 20) -> list[PeerInfo]:
        """
        Reference to provider_store.find_providers for convenience.
        """
        return await self.provider_store.find_providers(key, count)

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
