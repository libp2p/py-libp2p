"""
Kademlia DHT implementation for py-libp2p.

This module provides a complete Distributed Hash Table (DHT)
implementation based on the Kademlia algorithm and protocol.
"""

from collections.abc import Awaitable, Callable
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
from libp2p.discovery.random_walk.rt_refresh_manager import RTRefreshManager
from libp2p.kad_dht.utils import maybe_consume_signed_record, sort_peer_ids_by_distance
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.envelope import Envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import env_to_send_in_RPC
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
MIN_PEERS_THRESHOLD = 5  # Configurable minimum for fallback to connected peers


class DHTMode(Enum):
    """DHT operation modes."""

    CLIENT = "CLIENT"
    SERVER = "SERVER"


class KadDHT(Service):
    """
    Kademlia DHT implementation for libp2p.

    This class provides a DHT implementation that combines routing table management,
    peer discovery, content routing, and value storage.

    Optional Random Walk feature enhances peer discovery by automatically
    performing periodic random queries to discover new peers and maintain
    routing table health.

    Example:
        # Basic DHT without random walk (default)
        dht = KadDHT(host, DHTMode.SERVER)

        # DHT with random walk enabled for enhanced peer discovery
        dht = KadDHT(host, DHTMode.SERVER, enable_random_walk=True)

    """

    def __init__(self, host: IHost, mode: DHTMode, enable_random_walk: bool = False):
        """
        Initialize a new Kademlia DHT node.

        :param host: The libp2p host.
        :param mode: The mode of host (Client or Server) - must be DHTMode enum
        :param enable_random_walk: Whether to enable automatic random walk
        """
        super().__init__()
        self.MIN_PEERS_THRESHOLD = (
            5  # Configurable minimum for fallback to connected peers
        )

        self.host = host
        self.local_peer_id = host.get_id()

        # Validate that mode is a DHTMode enum
        if not isinstance(mode, DHTMode):
            raise TypeError(f"mode must be DHTMode enum, got {type(mode)}")

        self.mode = mode
        self.enable_random_walk = enable_random_walk

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

        # Initialize RT Refresh Manager (only if random walk is enabled)
        self.rt_refresh_manager: RTRefreshManager | None = None
        if self.enable_random_walk:
            self.rt_refresh_manager = RTRefreshManager(
                host=self.host,
                routing_table=self.routing_table,
                local_peer_id=self.local_peer_id,
                query_function=self._create_query_function(),
                enable_auto_refresh=True,
            )

        # Set protocol handlers
        host.set_stream_handler(PROTOCOL_ID, self.handle_stream)

    def _create_query_function(self) -> Callable[[bytes], Awaitable[list[ID]]]:
        """
        Create a query function that wraps peer_routing.find_closest_peers_network.

        This function is used by the RandomWalk module to query for peers without
        directly importing PeerRouting, avoiding circular import issues.

        Returns:
            Callable that takes target_key bytes and returns list of peer IDs

        """

        async def query_function(target_key: bytes) -> list[ID]:
            """Query for closest peers to target key."""
            return await self.peer_routing.find_closest_peers_network(target_key)

        return query_function

    async def run(self) -> None:
        """Run the DHT service."""
        logger.info("Starting Kademlia DHT with peer ID %s", self.local_peer_id)

        # Start the RT Refresh Manager in parallel with the main DHT service
        async with trio.open_nursery() as nursery:
            # Start the RT Refresh Manager only if random walk is enabled
            if self.rt_refresh_manager is not None:
                nursery.start_soon(self.rt_refresh_manager.start)
                logger.info("RT Refresh Manager started - Random Walk is now active")
            else:
                logger.info("Random Walk is disabled - RT Refresh Manager not started")

            # Start the main DHT service loop
            nursery.start_soon(self._run_main_loop)

    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        logger.debug("Refreshing routing table")
        await self.peer_routing.refresh_routing_table()

    async def _run_main_loop(self) -> None:
        """Run the main DHT service loop."""
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
                logger.debug("Cleaned up %d expired values", expired_values)

            self.provider_store.cleanup_expired()

            # Wait before next maintenance cycle
            await trio.sleep(ROUTING_TABLE_REFRESH_INTERVAL)

    async def stop(self) -> None:
        """Stop the DHT service and cleanup resources."""
        logger.info("Stopping Kademlia DHT")

        # Stop the RT Refresh Manager only if it was started
        if self.rt_refresh_manager is not None:
            await self.rt_refresh_manager.stop()
            logger.info("RT Refresh Manager stopped")
        else:
            logger.info("RT Refresh Manager was not running (Random Walk disabled)")

    async def switch_mode(self, new_mode: DHTMode) -> DHTMode:
        """
        Switch the DHT mode.

        :param new_mode: The new mode - must be DHTMode enum
        :return: The new mode as DHTMode enum
        """
        # Validate that new_mode is a DHTMode enum
        if not isinstance(new_mode, DHTMode):
            raise TypeError("new_mode must be DHTMode enum, got %s", type(new_mode))

        if new_mode == DHTMode.CLIENT:
            self.routing_table.cleanup_routing_table()
        self.mode = new_mode
        logger.info("Switched to %s mode", new_mode.value)
        return self.mode

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming DHT stream using varint length prefixes.
        """
        if self.mode == DHTMode.CLIENT:
            stream.close
            return
        peer_id = stream.muxed_conn.peer_id
        logger.debug("Received DHT stream from peer %s", peer_id)
        await self.add_peer(peer_id)
        logger.debug("Added peer %s to routing table", peer_id)

        closer_peer_envelope: Envelope | None = None
        provider_peer_envelope: Envelope | None = None

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
                    "Received DHT message from %s, type: %s",
                    peer_id,
                    message.type,
                )

                # Handle FIND_NODE message
                if message.type == Message.MessageType.FIND_NODE:
                    # Get target key directly from protobuf
                    target_key = message.key

                    # Find closest peers to the target key
                    closest_peers = self.routing_table.find_local_closest_peers(
                        target_key, 20
                    )

                    # Fallback to connected peers if
                    # routing table has insufficient peers
                    if len(closest_peers) < self.MIN_PEERS_THRESHOLD:
                        logger.debug(
                            "Routing table has insufficient peers (%d < %d) "
                            "for FIND_NODE in KadDHT, "
                            "using connected peers as fallback",
                            len(closest_peers),
                            self.MIN_PEERS_THRESHOLD,
                        )
                        connected_peers = self.host.get_connected_peers()
                        if connected_peers:
                            # Sort connected peers by distance & use as response
                            fallback_peers = sort_peer_ids_by_distance(
                                target_key, connected_peers
                            )[:20]
                            closest_peers = fallback_peers
                            logger.debug(
                                "Using %d connected peers as FIND_NODE fallback in DHT",
                                len(closest_peers),
                            )

                    logger.debug("Found %d peers close to target", len(closest_peers))

                    # Consume the source signed_peer_record if sent
                    if not maybe_consume_signed_record(message, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, dropping the stream"
                        )
                        await stream.close()
                        return

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

                        # Add the signed-peer-record for each peer in the peer-proto
                        # if cached in the peerstore
                        closer_peer_envelope = (
                            self.host.get_peerstore().get_peer_record(peer)
                        )

                        if closer_peer_envelope is not None:
                            peer_proto.signedRecord = (
                                closer_peer_envelope.marshal_envelope()
                            )

                    # Create sender_signed_peer_record
                    envelope_bytes, _ = env_to_send_in_RPC(self.host)
                    response.senderRecord = envelope_bytes

                    # Serialize and send response
                    response_bytes = response.SerializeToString()
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)
                    logger.debug(
                        "Sent FIND_NODE response with %d peers",
                        len(response.closerPeers),
                    )

                # Handle ADD_PROVIDER message
                elif message.type == Message.MessageType.ADD_PROVIDER:
                    # Process ADD_PROVIDER
                    key = message.key
                    logger.debug("Received ADD_PROVIDER for key %s", key.hex())

                    # Consume the source signed-peer-record if sent
                    if not maybe_consume_signed_record(message, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, dropping the stream"
                        )
                        await stream.close()
                        return

                    # Extract provider information
                    for provider_proto in message.providerPeers:
                        try:
                            # Validate that the provider is the sender
                            provider_id = ID(provider_proto.id)
                            if provider_id != peer_id:
                                logger.warning(
                                    "Provider ID %s doesn't match sender %s, ignoring",
                                    provider_id,
                                    peer_id,
                                )
                                continue

                            # Convert addresses to Multiaddr
                            addrs = []
                            for addr_bytes in provider_proto.addrs:
                                try:
                                    addrs.append(Multiaddr(addr_bytes))
                                except Exception as e:
                                    logger.warning("Failed to parse address: %s", e)

                            # Add to provider store
                            provider_info = PeerInfo(provider_id, addrs)
                            self.provider_store.add_provider(key, provider_info)
                            logger.debug(
                                "Added provider %s for key %s",
                                provider_id,
                                key.hex(),
                            )

                            # Process the signed-records of provider if sent
                            if not maybe_consume_signed_record(
                                provider_proto, self.host
                            ):
                                logger.error(
                                    "Received an invalid-signed-record,"
                                    "dropping the stream"
                                )
                                await stream.close()
                                return
                        except Exception as e:
                            logger.warning("Failed to process provider info: %s", e)

                    # Send acknowledgement
                    response = Message()
                    response.type = Message.MessageType.ADD_PROVIDER
                    response.key = key

                    # Add sender's signed-peer-record
                    envelope_bytes, _ = env_to_send_in_RPC(self.host)
                    response.senderRecord = envelope_bytes

                    response_bytes = response.SerializeToString()
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)
                    logger.debug("Sent ADD_PROVIDER acknowledgement")

                # Handle GET_PROVIDERS message
                elif message.type == Message.MessageType.GET_PROVIDERS:
                    # Process GET_PROVIDERS
                    key = message.key
                    logger.debug("Received GET_PROVIDERS request for key %s", key.hex())

                    # Consume the source signed_peer_record if sent
                    if not maybe_consume_signed_record(message, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, dropping the stream"
                        )
                        await stream.close()
                        return

                    # Find providers for the key
                    providers = self.provider_store.get_providers(key)
                    logger.debug(
                        "Found %d providers for key %s",
                        len(providers),
                        key.hex(),
                    )

                    # Create response
                    response = Message()
                    response.type = Message.MessageType.GET_PROVIDERS
                    response.key = key

                    # Create sender_signed_peer_record for the response
                    envelope_bytes, _ = env_to_send_in_RPC(self.host)
                    response.senderRecord = envelope_bytes

                    # Add provider information to response
                    for provider_info in providers:
                        provider_proto = response.providerPeers.add()
                        provider_proto.id = provider_info.peer_id.to_bytes()
                        provider_proto.connection = Message.ConnectionType.CAN_CONNECT

                        # Add provider signed-records if cached
                        provider_peer_envelope = (
                            self.host.get_peerstore().get_peer_record(
                                provider_info.peer_id
                            )
                        )

                        if provider_peer_envelope is not None:
                            provider_proto.signedRecord = (
                                provider_peer_envelope.marshal_envelope()
                            )

                        # Add addresses if available
                        for addr in provider_info.addrs:
                            provider_proto.addrs.append(addr.to_bytes())

                    # Also include closest peers if we don't have providers
                    if not providers:
                        closest_peers = self.routing_table.find_local_closest_peers(
                            key, 20
                        )

                        # Fallback to connected peers if
                        # routing table has insufficient peers
                        MIN_PEERS_THRESHOLD = 5  # Configurable minimum
                        if len(closest_peers) < MIN_PEERS_THRESHOLD:
                            logger.debug(
                                "Routing table has insufficient peers"
                                " (%d < %d) for provider response, "
                                "using connected peers as fallback",
                                len(closest_peers),
                                MIN_PEERS_THRESHOLD,
                            )
                            connected_peers = self.host.get_connected_peers()
                            if connected_peers:
                                # Sort by distance to target and use as response
                                fallback_peers = sort_peer_ids_by_distance(
                                    key, connected_peers
                                )[:20]
                                closest_peers = fallback_peers
                                logger.debug(
                                    "Using %d connected peers as "
                                    "fallback for provider response",
                                    len(closest_peers),
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

                            # Add the signed-records of closest_peers if cached
                            closer_peer_envelope = (
                                self.host.get_peerstore().get_peer_record(peer)
                            )

                            if closer_peer_envelope is not None:
                                peer_proto.signedRecord = (
                                    closer_peer_envelope.marshal_envelope()
                                )

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

                    # Consume the sender_signed_peer_record
                    if not maybe_consume_signed_record(message, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, dropping the stream"
                        )
                        await stream.close()
                        return

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

                        # Create sender_signed_peer_record
                        envelope_bytes, _ = env_to_send_in_RPC(self.host)
                        response.senderRecord = envelope_bytes

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

                        # Create sender_signed_peer_record for the response
                        envelope_bytes, _ = env_to_send_in_RPC(self.host)
                        response.senderRecord = envelope_bytes

                        # Add closest peers to key
                        closest_peers = self.routing_table.find_local_closest_peers(
                            key, 20
                        )

                        # Fallback to connected peers
                        # if routing table has insufficient peers
                        MIN_PEERS_THRESHOLD = 5  # Configurable minimum
                        if len(closest_peers) < MIN_PEERS_THRESHOLD:
                            logger.debug(
                                "Routing table has insufficient peers"
                                " (%d < %d) for GET_VALUE response, "
                                "using connected peers as fallback",
                                len(closest_peers),
                                MIN_PEERS_THRESHOLD,
                            )
                            connected_peers = self.host.get_connected_peers()
                            if connected_peers:
                                # Sort connected peers by distance to target
                                # and use as response
                                fallback_peers = sort_peer_ids_by_distance(
                                    key, connected_peers
                                )[:20]
                                closest_peers = fallback_peers
                                logger.debug(
                                    "Using %d connected peers as "
                                    "fallback for GET_VALUE response",
                                    len(closest_peers),
                                )

                        logger.debug(
                            "No value found, including %d closest peers",
                            len(closest_peers),
                        )

                        for peer in closest_peers:
                            # Skip if peer is the requester
                            if peer == peer_id:
                                continue

                            peer_proto = response.closerPeers.add()
                            peer_proto.id = peer.to_bytes()
                            peer_proto.connection = Message.ConnectionType.CAN_CONNECT

                            # Add signed-records of closer-peers if cached
                            closer_peer_envelope = (
                                self.host.get_peerstore().get_peer_record(peer)
                            )

                            if closer_peer_envelope is not None:
                                peer_proto.signedRecord = (
                                    closer_peer_envelope.marshal_envelope()
                                )

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

                    # Consume the source signed_peer_record if sent
                    if not maybe_consume_signed_record(message, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, dropping the stream"
                        )
                        await stream.close()
                        return

                    try:
                        if not (key and value):
                            raise ValueError(
                                "Missing key or value in PUT_VALUE message"
                            )

                        self.value_store.put(key, value)
                        logger.debug(
                            "Stored value %s for key %s", value.hex(), key.hex()
                        )
                        success = True
                    except Exception as e:
                        logger.warning(
                            "Failed to store value %s for key %s: %s",
                            value.hex(),
                            key.hex(),
                            str(e),
                        )
                    finally:
                        # Send acknowledgement
                        response = Message()
                        response.type = Message.MessageType.PUT_VALUE
                        if success:
                            response.key = key

                        # Create sender_signed_peer_record for the response
                        envelope_bytes, _ = env_to_send_in_RPC(self.host)
                        response.senderRecord = envelope_bytes

                        # Serialize and send response
                        response_bytes = response.SerializeToString()
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug("Sent PUT_VALUE acknowledgement")

            except Exception as proto_err:
                logger.warning("Failed to parse protobuf message: %s", str(proto_err))

            await stream.close()
        except Exception as e:
            logger.error("Error handling DHT stream: %s", str(e))
            await stream.close()

    # Peer routing methods

    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        """
        Find a peer with the given ID.
        """
        logger.debug("Finding peer: %s", str(peer_id))
        return await self.peer_routing.find_peer(peer_id)

    # Value storage and retrieval methods

    async def put_value(self, key: bytes, value: bytes) -> None:
        """
        Store a value in the DHT.
        """
        logger.debug("Storing value for key %s", key.hex())

        # 1. Store locally first
        self.value_store.put(key, value)
        try:
            decoded_value = value.decode("utf-8")
        except UnicodeDecodeError:
            decoded_value = value.hex()
        logger.debug(
            "Stored value locally for key %s with value %s", key.hex(), decoded_value
        )

        # 2. Get closest peers, excluding self
        routing_table_peers = self.routing_table.find_local_closest_peers(key)

        # Fallback to connected peers if routing table has insufficient peers
        MIN_PEERS_THRESHOLD = 5  # Configurable minimum
        if len(routing_table_peers) < MIN_PEERS_THRESHOLD:
            logger.debug(
                "Routing table has insufficient peers (%d < %d) for put_value, "
                "using connected peers as fallback",
                len(routing_table_peers),
                MIN_PEERS_THRESHOLD,
            )
            connected_peers = self.host.get_connected_peers()
            if connected_peers:
                # Sort connected peers by distance to target and use as fallback
                fallback_peers = sort_peer_ids_by_distance(key, connected_peers)
                routing_table_peers = fallback_peers
                logger.debug(
                    "Using %d connected peers as fallback for put_value",
                    len(routing_table_peers),
                )

        closest_peers = [
            peer for peer in routing_table_peers if peer != self.local_peer_id
        ]
        logger.debug("Found %d peers to store value at", len(closest_peers))

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
                            logger.debug("Stored value at peer %s", str(peer))
                        else:
                            logger.debug("Failed to store value at peer %s", str(peer))
                except Exception as e:
                    logger.debug(
                        "Error storing value at peer %s: %s", str(peer), str(e)
                    )

            async with trio.open_nursery() as nursery:
                for idx, peer in enumerate(batch):
                    nursery.start_soon(store_one, idx, peer)

            stored_count += sum(batch_results)

        logger.info("Successfully stored value at %d peers", stored_count)

    async def get_value(self, key: bytes) -> bytes | None:
        logger.debug("Getting value for key: %s", key.hex())

        # 1. Check local store first
        value = self.value_store.get(key)
        if value:
            logger.debug("Found value locally")
            return value

        # 2. Get closest peers, excluding self
        routing_table_peers = self.routing_table.find_local_closest_peers(key)

        # Fallback to connected peers if routing table has insufficient peers
        MIN_PEERS_THRESHOLD = 5  # Configurable minimum
        if len(routing_table_peers) < MIN_PEERS_THRESHOLD:
            logger.debug(
                "Routing table has insufficient peers (%d < %d) for get_value, "
                "using connected peers as fallback",
                len(routing_table_peers),
                MIN_PEERS_THRESHOLD,
            )
            connected_peers = self.host.get_connected_peers()
            if connected_peers:
                # Sort connected peers by distance to target and use as fallback
                fallback_peers = sort_peer_ids_by_distance(key, connected_peers)
                routing_table_peers = fallback_peers
                logger.debug(
                    "Using %d connected peers as fallback for get_value",
                    len(routing_table_peers),
                )

        closest_peers = [
            peer for peer in routing_table_peers if peer != self.local_peer_id
        ]
        logger.debug("Searching %d peers for value", len(closest_peers))

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
                            logger.debug("Found value at peer %s", str(peer))
                except Exception as e:
                    logger.debug("Error querying peer %s: %s", str(peer), str(e))

            async with trio.open_nursery() as nursery:
                for peer in batch:
                    nursery.start_soon(query_one, peer)

            if found_value is not None:
                self.value_store.put(key, found_value)
                logger.info("Successfully retrieved value from network")
                return found_value

            # 4. Not found
            logger.warning("Value not found for key %s", key.hex())
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

    def is_random_walk_enabled(self) -> bool:
        """
        Check if random walk peer discovery is enabled.

        Returns
        -------
        bool
            True if random walk is enabled, False otherwise.

        """
        return self.enable_random_walk
