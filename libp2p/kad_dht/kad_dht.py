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
from libp2p.custom_types import TProtocol
from libp2p.discovery.random_walk.rt_refresh_manager import RTRefreshManager
from libp2p.kad_dht.utils import maybe_consume_signed_record
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
from libp2p.records.pubkey import PublicKeyValidator
from libp2p.records.validator import NamespacedValidator, Validator
from libp2p.tools.async_service import (
    Service,
)

from .common import (
    ALPHA,
    BUCKET_SIZE,
    PROTOCOL_ID,
    PROTOCOL_PREFIX,
    QUERY_TIMEOUT,
)
from .pb.kademlia_pb2 import (
    Message,
    Record,
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

logger = logging.getLogger(__name__)
# Default parameters
ROUTING_TABLE_REFRESH_INTERVAL = 60  # 1 min in seconds for testing


class DHTMode(Enum):
    """DHT operation modes."""

    CLIENT = "CLIENT"
    SERVER = "SERVER"


# Timestamp validation constants
MAX_TIMESTAMP_AGE = 24 * 60 * 60  # 24 hours in seconds
MAX_TIMESTAMP_FUTURE = 5 * 60  # 5 minutes in the future in seconds


def is_valid_timestamp(ts: float) -> bool:
    """
    Validate if a timestamp is within acceptable bounds.

    Args:
        ts: The timestamp to validate (Unix timestamp in seconds)

    Returns:
        bool: True if timestamp is valid (not too old and not too far in future)

    """
    current_time = time.time()
    # Check if timestamp is not in the future by more than MAX_TIMESTAMP_FUTURE
    if ts > current_time + MAX_TIMESTAMP_FUTURE:
        return False
    # Check if timestamp is not too far in the past
    if current_time - ts > MAX_TIMESTAMP_AGE:
        return False
    return True


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

    def __init__(
        self,
        host: IHost,
        mode: DHTMode,
        enable_random_walk: bool = False,
        validator: NamespacedValidator | None = None,
        validator_changed: bool = False,
        protocol_prefix: TProtocol = PROTOCOL_PREFIX,
        enable_providers: bool = True,
        enable_values: bool = True,
    ):
        """
        Initialize a new Kademlia DHT node.

        :param host: The libp2p host.
        :param mode: The mode of host (Client or Server) - must be DHTMode enum
        :param enable_random_walk: Whether to enable automatic random walk
        """
        super().__init__()

        self.host: IHost = host
        self.local_peer_id = host.get_id()

        # Validate that mode is a DHTMode enum
        if not isinstance(mode, DHTMode):
            raise TypeError(f"mode must be DHTMode enum, got {type(mode)}")

        self.mode = mode
        self.enable_random_walk = enable_random_walk

        # Initialize the routing table
        self.routing_table = RoutingTable(self.local_peer_id, host)

        self.protocol_prefix = protocol_prefix
        self.enable_providers = enable_providers
        self.enable_values = enable_values
        self.validator = validator

        if validator is None:
            self.validator = NamespacedValidator({"pk": PublicKeyValidator()})

        # If true implies that the validator has been changed and that
        # Defaults should not be used
        self.validator_changed = validator_changed

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
        logger.info(f"Starting Kademlia DHT with peer ID {self.local_peer_id}")

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
                logger.debug(f"Cleaned up {expired_values} expired values")

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

    def apply_fallbacks(self) -> None:
        """
        Apply fallback validators if not explicitely changed by the user

        This sets default validators like 'pk' and 'ipns' if they are missing and
        the default validator set hasn't been overridden.
        """
        if not self.validator_changed:
            if not isinstance(self.validator, NamespacedValidator):
                raise ValueError(
                    "Default validator was changed without marking it True"
                )

            if "pk" not in self.validator._validators:
                self.validator._validators["pk"] = PublicKeyValidator()

            # TODO: Do the same thing for ipns, but need to implement first.

    def validate_config(self) -> None:
        """
        Validate the DHT config.
        """
        if self.protocol_prefix != PROTOCOL_PREFIX:
            return  # Skip validation for non-standart prefixes

        for bucket in self.routing_table.buckets:
            if bucket.bucket_size != BUCKET_SIZE:
                raise ValueError(
                    f"{PROTOCOL_PREFIX} prefix must use bucket size {BUCKET_SIZE}"
                )

        if not self.enable_providers:
            raise ValueError(f"{PROTOCOL_PREFIX} prefix must have providers enabled")

        if not self.enable_values:
            raise ValueError(f"{PROTOCOL_PREFIX} prefix must have values enabled")

        if not isinstance(self.validator, NamespacedValidator):
            raise ValueError(
                f"{PROTOCOL_PREFIX} prefix must use a namespace type validator"
            )

        vmap = self.validator._validators

        # TODO: Need to add ipns also in the check
        if set(vmap.keys()) != {"pk"}:
            raise ValueError(f"{PROTOCOL_PREFIX} must have 'pk' and 'ipns' validators")

        pk_validator = vmap.get("pk")
        if not isinstance(pk_validator, PublicKeyValidator):
            raise TypeError("'pk' namesapce must use PublicKeyValidator")

        # TODO: ipns checks

    def set_validator(self, val: NamespacedValidator) -> None:
        """
        Set a custom validator for the DHT config.

        This marks the validator as explicitly changed, so the default
        validators (pk and ipns) will not be automatically applied later.
        """
        self.validator = val
        self.validator_changed = True
        return

    def set_namespace_validator(self, ns: str, val: Validator) -> None:
        """
        Adds a validator under a specofic namespace to the current DHT config.

        Raises an error if the current validator is not a NamespacedValidator
        """
        if not isinstance(self.validator, NamespacedValidator):
            raise TypeError(
                "Can only add namespaced validators to a NamespacedValidator"
            )

        self.validator._validators["ns"] = val

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
                        f"Sent FIND_NODE response with{len(response.closerPeers)} peers"
                    )

                # Handle ADD_PROVIDER message
                elif message.type == Message.MessageType.ADD_PROVIDER:
                    # Process ADD_PROVIDER
                    key = message.key
                    logger.debug(f"Received ADD_PROVIDER for key {key.hex()}")

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
                            logger.warning(f"Failed to process provider info: {e}")

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
                    logger.debug(f"Received GET_PROVIDERS request for key {key.hex()}")

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
                        f"Found {len(providers)} providers for key {key.hex()}"
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

                    value_record = self.value_store.get(key)
                    if value_record:
                        logger.debug(f"Found value for key {key.hex()}")

                        # Create response using protobuf
                        response = Message()
                        response.type = Message.MessageType.GET_VALUE

                        # Create record
                        response.key = key
                        response.record.CopyFrom(value_record)

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

                        # Always validate the key-value pair before storing
                        # Reject keys without registered namespace validators
                        key_str = key.decode("utf-8")
                        if self.validator is None:
                            raise ValueError("Validator is required for DHT operations")
                        self.validator.validate(key_str, value)

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

                        # Create sender_signed_peer_record for the response
                        envelope_bytes, _ = env_to_send_in_RPC(self.host)
                        response.senderRecord = envelope_bytes

                        # Serialize and send response
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

    async def put_value(self, key: str, value: bytes) -> None:
        """
        Store a value in the DHT.

        Args:
            key: String key (will be converted to bytes for storage)
            value: Binary value to store

        Raises:
            InvalidRecordType: If no validator is registered for the key's namespace
            ValueError: If trying to replace a newer value with an older one

        """
        logger.debug(f"Storing value for key {key}")

        # Always validate the key-value pair using the namespaced validator
        # This will raise InvalidRecordType if:
        # - The key is not namespaced (doesn't start with / or has no second /)
        # - No validator is registered for the key's namespace
        # Following Go libp2p behavior where only namespaced keys are allowed
        if self.validator is None:
            raise ValueError("Validator is required for DHT operations")
        self.validator.validate(key, value)

        key_bytes = key.encode("utf-8")
        old_value_record = self.value_store.get(key_bytes)
        if old_value_record is not None and old_value_record.value != value:
            index = self.validator.select(key, [value, old_value_record.value])
            if index != 0:
                raise ValueError("Refusing to replace newer value with the older one")

        # 1. Store locally first
        self.value_store.put(key_bytes, value)
        try:
            decoded_value = value.decode("utf-8")
        except UnicodeDecodeError:
            decoded_value = value.hex()
        logger.debug(f"Stored value locally for key {key} with value {decoded_value}")

        # 2. Get closest peers, excluding self
        closest_peers = [
            peer
            for peer in self.routing_table.find_local_closest_peers(key_bytes)
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
                            peer, key_bytes, value
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

    async def get_value(self, key: str, quorum: int = 0) -> bytes | None:
        """
        Retrieve a value from the DHT.

        Args:
            key: String key (will be converted to bytes for lookup)
            quorum: Minimum number of valid peer responses required for confidence.
            If quorum > 0 and not met, the function still returns the best value
            found (if any) but logs a warning. Set to 0 to disable quorum checking.

        Returns:
            The value if found (best value even if quorum not met), None otherwise.
            Note: When quorum is not met, a warning is logged but the best available
            value is still returned. This allows graceful degradation when the network
            has insufficient peers.

        """
        logger.debug(f"Getting value for key: {key}")

        # Convert string key to bytes for lookup
        key_bytes = key.encode("utf-8")

        # 1. Check local store first
        value_record = self.value_store.get(key_bytes)
        if value_record:
            logger.debug("Found value locally")
            return value_record.value

        # 2. Get closest peers, excluding self
        closest_peers = [
            peer
            for peer in self.routing_table.find_local_closest_peers(key_bytes)
            if peer != self.local_peer_id
        ]
        logger.debug(f"Searching {len(closest_peers)} peers for value")

        # Collect valid records from peers: mapping peer -> Record
        valid_records: list[tuple[ID, Record]] = []

        # 3. Query ALPHA peers at a time in parallel
        # Use list to track mutable state (pyrefly requirement)
        total_responses_list: list[int] = [0]
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]

            async def query_one(peer: ID) -> None:
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        # Fetch the record directly to get timeReceived
                        rec = await self.value_store._get_from_peer(
                            peer, key_bytes, return_record=True
                        )
                        if rec is not None:
                            total_responses_list[0] += 1
                            # Validate the record's value
                            try:
                                if self.validator is None:
                                    raise ValueError("Validator is required")
                                if not isinstance(rec, Record):
                                    raise TypeError("Expected Record type")
                                self.validator.validate(key, rec.value)
                                valid_records.append((peer, rec))
                                logger.debug(f"Found valid record at peer {peer}")
                            except Exception as e:
                                logger.debug(
                                    f"Received invalid record from {peer}, "
                                    f"discarding: {e}"
                                )
                except Exception as e:
                    logger.debug(f"Error querying peer {peer}: {e}")

            async with trio.open_nursery() as nursery:
                for peer in batch:
                    nursery.start_soon(query_one, peer)

            # If quorum is set and we have enough valid records, we can stop early
            # Note: quorum counts valid records, not all responses.
            if quorum and len(valid_records) >= quorum:
                logger.debug(f"Quorum reached ({len(valid_records)} valid records)")
                break

        # 4. Select the best record if any valid records were found
        if valid_records:
            # Check if quorum was met
            if quorum > 0 and len(valid_records) < quorum:
                logger.warning(
                    f"Quorum not met: found {len(valid_records)} valid records, "
                    f"required {quorum}. Returning best value found."
                )

            # Select the best record using the validator
            # Note: Following Go libp2p's approach, we use validator.select() to choose
            # the best value, not timestamps. The timeReceived field is for local
            # bookkeeping only, not for distributed consensus on the "best" record.
            if self.validator is None:
                raise ValueError("Validator is required for record selection")

            values = [rec.value for _p, rec in valid_records]
            best_idx = self.validator.select(key, values)
            logger.debug(
                f"Selected best value at index {best_idx}using validator.select()"
            )

            best_peer, best_rec = valid_records[best_idx]
            best_value = best_rec.value

            # Propagate the best record to peers that have different values
            # This ensures network consistency, following Go libp2p's approach
            outdated_peers: list[ID] = []
            for peer, rec in valid_records:
                # Propagate if the peer has a different value than the best
                if rec.value != best_value:
                    outdated_peers.append(peer)

            if outdated_peers:
                logger.debug(
                    f"Propagating best value to {len(outdated_peers)}"
                    "peers with outdated values"
                )

                async def propagate(peer: ID) -> None:
                    try:
                        with trio.move_on_after(QUERY_TIMEOUT):
                            await self.value_store._store_at_peer(
                                peer, key_bytes, best_value
                            )
                            logger.debug(f"Propagated updated record to peer {peer}")
                    except Exception as e:
                        logger.debug(f"Failed to propagate to peer {peer}: {e}")

                async with trio.open_nursery() as nursery:
                    for p in outdated_peers:
                        nursery.start_soon(propagate, p)

            # Store the best value locally
            self.value_store.put(key_bytes, best_value)
            logger.info("Successfully retrieved value from network")
            return best_value

        # 5. Not found
        logger.warning(f"Value not found for key {key}")
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

    async def provide(self, key: str) -> bool:
        """
        Reference to provider_store.provide for convenience.
        """
        key_bytes = key.encode("utf-8")
        return await self.provider_store.provide(key_bytes)

    async def find_providers(self, key: str, count: int = 20) -> list[PeerInfo]:
        """
        Reference to provider_store.find_providers for convenience.
        """
        key_bytes = key.encode("utf-8")
        return await self.provider_store.find_providers(key_bytes, count)

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

    def register_validator(self, namespace: str, validator: Validator) -> None:
        """
        Register a custom validator for a specific namespace.

        This allows storing and retrieving values with custom namespaced keys
        (e.g., /myapp/key). The validator will be used to validate values
        before storing and after retrieval.

        Args:
            namespace: The namespace string (e.g., "myapp" for keys like /myapp/key)
            validator: A Validator instance with validate() and select() methods

        Example:
            class MyValidator(Validator):
                def validate(self, key: str, value: bytes) -> None:
                    # Custom validation logic
                    pass

                def select(self, key: str, values: list[bytes]) -> int:
                    return 0  # Return index of best value

            dht.register_validator("myapp", MyValidator())
            await dht.put_value("/myapp/my-key", b"my-value")

        """
        if self.validator is None:
            self.validator = NamespacedValidator({namespace: validator})
        else:
            self.validator.add_validator(namespace, validator)

    def is_random_walk_enabled(self) -> bool:
        """
        Check if random walk peer discovery is enabled.

        Returns
        -------
        bool
            True if random walk is enabled, False otherwise.

        """
        return self.enable_random_walk
