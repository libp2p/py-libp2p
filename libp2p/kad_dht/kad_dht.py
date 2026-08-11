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
import multihash
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
from libp2p.records.ipns import IPNSValidator
from libp2p.records.pubkey import PublicKeyValidator
from libp2p.records.validator import NamespacedValidator, Validator
from libp2p.tools.anyio_service import (
    Service,
)

from .common import (
    ALPHA,
    BUCKET_SIZE,
    MAX_PROVIDERS_PER_MSG,
    MAX_RECORD_AGE,
    MAX_RECORD_SIZE,
    PROTOCOL_ID,
    PROTOCOL_PREFIX,
    QUERY_TIMEOUT,
    format_time_rfc3339,
    is_cid_like_key,
    is_reserved_or_private_addr,
    parse_time_received,
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
# 10 minutes in seconds (per spec: "default: 10 minutes")
ROUTING_TABLE_REFRESH_INTERVAL = 600


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


def clean_record(record: Record) -> Record:
    """
    Strip TimeReceived from incoming record to prevent timestamp forgery.

    Per go-libp2p, the receiver sets its own TimeReceived timestamp.
    This prevents malicious peers from forging the receive timestamp.
    """
    cleaned = Record()
    cleaned.key = record.key
    cleaned.value = record.value
    cleaned.author = record.author
    cleaned.signature = record.signature
    # Do NOT copy timeReceived - let the receiver set it
    return cleaned


def get_connection_type(host: IHost, peer_id: ID) -> Message.ConnectionType:
    """
    Get the actual connection type for a peer based on connection state.

    Per spec, we should report actual connection capability:
    - CONNECTED: Currently connected
    - CAN_CONNECT: Has known addresses and was recently connected
    - CANNOT_CONNECT: Has addresses but connection attempts failed
    - NOT_CONNECTED: No known addresses
    """
    try:
        # Check if currently connected
        connected_peers = host.get_connected_peers()
        if peer_id in connected_peers:
            return Message.ConnectionType.CONNECTED

        # Check if has addresses (can potentially connect)
        addrs = host.get_peerstore().addrs(peer_id)
        if addrs:
            # Has addresses but not connected - report CAN_CONNECT
            # (we can't easily detect failed connection attempts)
            return Message.ConnectionType.CAN_CONNECT

        return Message.ConnectionType.NOT_CONNECTED
    except Exception:
        return Message.ConnectionType.NOT_CONNECTED


class KadDhtEvent:
    peer_id: str

    inbound: bool = False
    find_node: bool = False
    get_value: bool = False
    put_value: bool = False
    get_providers: bool = False
    add_provider: bool = False


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
        strict_validation: bool = False,
        persist_dir: str | None = None,
    ):
        """
        Initialize a new Kademlia DHT node.

        :param host: The libp2p host.
        :param mode: The mode of host (Client or Server) - must be DHTMode enum
        :param enable_random_walk: Whether to enable automatic random walk
        :param validator: Custom NamespacedValidator for DHT records
        :param validator_changed: If True, indicates the validator was explicitly set
            and defaults should not be used
        :param protocol_prefix: Protocol prefix (default: /ipfs)
        :param enable_providers: Enable provider record support
        :param enable_values: Enable value record support
        :param strict_validation: If True, enforce strict namespace validation for all
            records. Only namespaced keys (e.g., /pk/, /ipns/, /myapp/) with registered
            validators will be accepted. If False (default), non-namespaced keys will
            be accepted without validation for backward compatibility.

            Setting this to True aligns behavior with go-libp2p and rust-libp2p where:
            - All DHT records MUST have a registered validator for their namespace
            - Keys without a matching namespace validator are rejected
            - This enforces permissioned keyspaces for security and correctness

        Example with strict validation:
            # Create validator with custom namespace
            validator = NamespacedValidator({
                "pk": PublicKeyValidator(),
                "myapp": MyAppValidator(),
            }, strict_validation=True)
            dht = KadDHT(
                host, DHTMode.SERVER, validator=validator, strict_validation=True
            )

            # Only namespaced keys are allowed:
            await dht.put_value("/myapp/key", b"value")  # OK
            await dht.put_value("/pk/...", pubkey)       # OK
            await dht.put_value("plain-key", b"value")   # Raises InvalidRecordType
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
        self._strict_validation = strict_validation
        self.validator = validator

        if self.validator is None:
            self.validator = NamespacedValidator(
                {"pk": PublicKeyValidator()},
                strict_validation=strict_validation,
            )

        # Keep strict_validation synchronized with the active validator.
        self.strict_validation = strict_validation

        # If true implies that the validator has been changed and that
        # Defaults should not be used
        self.validator_changed = validator_changed

        # Initialize peer routing
        self.peer_routing = PeerRouting(host, self.routing_table)

        # Initialize value store
        self.value_store = ValueStore(
            host=host,
            local_peer_id=self.local_peer_id,
            persist_path=f"{persist_dir}/values.json" if persist_dir else None,
        )

        # Initialize provider store with host and peer_routing references
        self.provider_store = ProviderStore(
            host=host,
            peer_routing=self.peer_routing,
            persist_path=f"{persist_dir}/providers.json" if persist_dir else None,
        )

        # Rate limiter for ADD_PROVIDER: maps peer_id -> (timestamp, count)
        self._provider_rate_limits: dict[str, tuple[float, int]] = {}
        self._provider_rate_window = 10.0  # seconds
        self._provider_rate_max = 10  # max ADD_PROVIDER messages per window

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

        # Set protocol handlers — only in server mode per spec:
        # "Server mode nodes accept incoming streams using the KAD protocol.
        #  Client mode nodes do not offer the KAD protocol for incoming streams."
        if self.mode == DHTMode.SERVER:
            host.set_stream_handler(PROTOCOL_ID, self.handle_stream)

    @property
    def strict_validation(self) -> bool:
        """
        Return strict validation mode.

        The validator is the source of truth when it supports
        ``strict_validation`` at runtime.
        """
        validator = self.validator
        if isinstance(validator, NamespacedValidator):
            return validator.strict_validation
        return self._strict_validation

    @strict_validation.setter
    def strict_validation(self, value: bool) -> None:
        """Set strict validation mode and synchronize with validator."""
        self._strict_validation = value
        validator = self.validator
        if isinstance(validator, NamespacedValidator):
            validator.strict_validation = value

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

            # Start periodic stale peer refresh for routing table buckets
            self.routing_table.start_periodic_refresh(nursery)

            # Start the main DHT service loop
            nursery.start_soon(self._run_main_loop)

    async def _run_main_loop(self) -> None:
        """Run the main DHT service loop."""
        # Main service loop
        while self.manager.is_running:
            try:
                # Periodically refresh the routing table
                await self.refresh_routing_table()

                # Check if it's time to republish provider records
                current_time = time.time()
                await self.provider_store._republish_provider_records()
                self._last_provider_republish = current_time

                # Republish locally-stored value records
                await self.value_store._republish_records(self.peer_routing)

                # Clean up expired values and provider records
                expired_values = self.value_store.cleanup_expired()
                if expired_values > 0:
                    logger.debug(f"Cleaned up {expired_values} expired values")

                self.provider_store.cleanup_expired()
            except Exception as e:
                logger.error(f"Error in DHT maintenance loop: {e}")

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
            # Ensure validator is a NamespacedValidator (cannot be None at this point)
            if not isinstance(self.validator, NamespacedValidator):
                raise ValueError(
                    "Default validator was changed without marking it True"
                )

            # Use a local variable to help type checker narrow the type
            validator = self.validator

            # Add missing default validators
            if "pk" not in validator._validators:
                validator._validators["pk"] = PublicKeyValidator()
            if "ipns" not in validator._validators:
                validator._validators["ipns"] = IPNSValidator()

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

        # Check that both pk and ipns validators are present.
        # Additional namespaces beyond these two are deliberately allowed
        # so users can register custom validators for extensibility.
        required_validators = {"pk", "ipns"}
        if not required_validators.issubset(set(vmap.keys())):
            missing = required_validators - set(vmap.keys())
            raise ValueError(f"{PROTOCOL_PREFIX} must include validators for {missing}")

        pk_validator = vmap.get("pk")
        if not isinstance(pk_validator, PublicKeyValidator):
            raise TypeError("'pk' namespace must use PublicKeyValidator")

        ipns_validator = vmap.get("ipns")
        if not isinstance(ipns_validator, IPNSValidator):
            raise TypeError("'ipns' namespace must use IPNSValidator")

    def set_validator(self, val: NamespacedValidator) -> None:
        """
        Set a custom validator for the DHT config.

        This marks the validator as explicitly changed, so the default
        validators (pk and ipns) will not be automatically applied later.
        """
        self.validator = val
        # Keep the new validator in sync with current strict mode.
        self.validator.strict_validation = self._strict_validation
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

        self.validator._validators[ns] = val

    async def switch_mode(self, new_mode: DHTMode) -> DHTMode:
        """
        Switch the DHT mode.

        Per spec: "Server mode nodes accept incoming streams using the KAD
        protocol. Client mode nodes do not offer the KAD protocol for
        incoming streams."

        :param new_mode: The new mode - must be DHTMode enum
        :return: The new mode as DHTMode enum
        """
        # Validate that new_mode is a DHTMode enum
        if not isinstance(new_mode, DHTMode):
            raise TypeError(f"new_mode must be DHTMode enum, got {type(new_mode)}")

        old_mode = self.mode
        self.mode = new_mode

        # Register/unregister KAD stream handler based on mode
        if new_mode == DHTMode.SERVER and old_mode == DHTMode.CLIENT:
            self.host.set_stream_handler(PROTOCOL_ID, self.handle_stream)
            logger.debug("Registered KAD stream handler (switched to server mode)")
        elif new_mode == DHTMode.CLIENT and old_mode == DHTMode.SERVER:
            self.host.remove_stream_handler(PROTOCOL_ID)
            logger.debug("Removed KAD stream handler (switched to client mode)")
            self.routing_table.cleanup_routing_table()

        logger.info(f"Switched to {new_mode.value} mode")
        return self.mode

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming DHT stream using varint length prefixes.
        """
        if self.mode == DHTMode.CLIENT:
            await stream.close()
            return
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Received DHT stream from peer {peer_id}")
        # Peer initiated a KAD stream, so they MUST support KAD server mode
        await self.add_peer(peer_id, skip_server_mode_check=True)
        logger.debug(f"Added peer {peer_id} to routing table")

        closer_peer_envelope: Envelope | None = None
        provider_peer_envelope: Envelope | None = None

        # Per spec: "On any error, the stream is reset."
        should_reset = False

        try:
            while True:
                # Read varint-prefixed length for the message
                length_prefix = b""
                max_varint_bytes = 10  # varint max is 10 bytes for uint64
                eof = False
                while True:
                    byte = await stream.read(1)
                    if not byte:
                        logger.debug("Stream closed (EOF), exiting message loop")
                        eof = True
                        break
                    length_prefix += byte
                    if byte[0] & 0x80 == 0:
                        break
                    if len(length_prefix) >= max_varint_bytes:
                        logger.warning("Varint length exceeds maximum bytes")
                        eof = True
                        break
                if eof:
                    break

                msg_length = varint.decode_bytes(length_prefix)

                # Sanity check message size to prevent OOM
                max_message_size = 4 * 1024 * 1024  # 4 MB
                if msg_length > max_message_size:
                    logger.warning(
                        "DHT message too large: %s bytes (max %s)",
                        msg_length,
                        max_message_size,
                    )
                    break

                # Read the message bytes
                msg_bytes = b""
                remaining = msg_length
                read_failed = False
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        logger.debug("Failed to read full message from stream, exiting")
                        read_failed = True
                        break
                    msg_bytes += chunk
                    remaining -= len(chunk)
                if read_failed:
                    break

                try:
                    # Parse as protobuf
                    message = Message()
                    message.ParseFromString(msg_bytes)
                    logger.debug(
                        f"Received DHT message from {peer_id}, type: {message.type}"
                    )

                    event = KadDhtEvent()
                    event.peer_id = peer_id.pretty()
                    event.inbound = True

                    # Handle FIND_NODE message
                    if message.type == Message.MessageType.FIND_NODE:
                        # Consume the source signed_peer_record if sent (validate first)
                        if not maybe_consume_signed_record(message, self.host, peer_id):
                            logger.error(
                                "Received an invalid-signed-record, dropping the stream"
                            )
                            should_reset = True
                            break

                        # Get target key directly from protobuf
                        target_key = message.key

                        # Per spec: "key must be set to the binary PeerId"
                        if not target_key:
                            logger.warning("FIND_NODE with empty key, ignoring")
                            should_reset = True
                            break

                        # Validate key is a valid PeerId
                        # Accept raw multihash (common) or any reasonable-length
                        # key for backward compatibility with CID-encoded PeerIds
                        valid_peer_id = False
                        try:
                            multihash.decode(target_key)
                            valid_peer_id = True
                        except Exception:
                            # Accept any reasonable-length key for
                            # backward compatibility
                            if 2 <= len(target_key) <= 50:
                                valid_peer_id = True

                        if not valid_peer_id:
                            logger.warning(
                                f"FIND_NODE key is not a valid PeerId "
                                f"({len(target_key)} bytes), ignoring"
                            )
                            should_reset = True
                            break

                        # Find closest peers to the target key
                        closest_peers = self.routing_table.find_local_closest_peers(
                            target_key, BUCKET_SIZE
                        )
                        logger.debug(f"Found {len(closest_peers)} close peers")

                        # Metrics Event
                        event.find_node = True

                        # Build response message with protobuf
                        response = Message()
                        response.type = Message.MessageType.FIND_NODE

                        target = ID(target_key)

                        # Per spec: FIND_PEER has a special exception where the
                        # target peer MUST be included in the response (if present
                        # in peerstore), even if it is self, the requester, or not
                        # a DHT server. go-libp2p always prepends the target, but
                        # then filters by addresses (len(pi.Addrs) > 0). We
                        # achieve the same result by only prepending if the target
                        # is known (has addresses) or is self.
                        try:
                            target_known = bool(self.host.get_peerstore().addrs(target))
                        except Exception:
                            target_known = False
                        if not target_known and target == self.host.get_id():
                            target_known = True
                        if target_known:
                            closest_peers = [target] + [
                                p for p in closest_peers if p != target
                            ]

                        # Add closest peers to response
                        for peer in closest_peers:
                            # Skip if the peer is the requester
                            if peer == peer_id:
                                continue

                            # Add peer to closerPeers field
                            peer_proto = response.closerPeers.add()
                            peer_proto.id = peer.to_bytes()
                            peer_proto.connection = get_connection_type(self.host, peer)

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
                            "Sent FIND_NODE response with %s peers",
                            len(response.closerPeers),
                        )

                    # Handle PING message
                    elif message.type == Message.MessageType.PING:
                        logger.debug(f"Received PING from {peer_id}")

                        # Send PING response
                        response = Message()
                        response.type = Message.MessageType.PING
                        response_bytes = response.SerializeToString()
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug(f"Sent PING response to {peer_id}")

                    # Handle ADD_PROVIDER message
                    elif message.type == Message.MessageType.ADD_PROVIDER:
                        # Process ADD_PROVIDER
                        key = message.key
                        logger.debug(f"Received ADD_PROVIDER for key {key.hex()}")

                        # Per spec: check key length (80 bytes max)
                        if len(key) > 80 or len(key) == 0:
                            logger.warning(
                                f"ADD_PROVIDER key length invalid: {len(key)}, ignoring"
                            )
                            should_reset = True
                            break

                        # Per spec: "The target node verifies key is a valid CID"
                        # Log a warning if key doesn't look like a CID,
                        # but don't reject (backward compatibility)
                        if not is_cid_like_key(key):
                            logger.debug("ADD_PROVIDER key does not look like a CID")

                        # Consume the source signed_peer_record if sent
                        if not maybe_consume_signed_record(message, self.host, peer_id):
                            logger.error(
                                "Received an invalid-signed-record, dropping the stream"
                            )
                            should_reset = True
                            break

                        # Rate limit check
                        if not self._check_provider_rate_limit(peer_id):
                            should_reset = True
                            break

                        # Metrics Event
                        event.add_provider = True

                        # Cap the number of providers per message
                        provider_count = 0
                        for provider_proto in message.providerPeers:
                            if provider_count >= MAX_PROVIDERS_PER_MSG:
                                logger.warning(
                                    f"Too many providers in ADD_PROVIDER "
                                    f"message (>{MAX_PROVIDERS_PER_MSG}), "
                                    "ignoring rest"
                                )
                                break
                            try:
                                # Validate that the provider is the sender
                                provider_id = ID(provider_proto.id)
                                if provider_id != peer_id:
                                    logger.warning(
                                        f"Provider ID {provider_id} doesn't "
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

                                # Validate provider has at least one address
                                if not addrs:
                                    logger.warning(
                                        f"Provider {provider_id} "
                                        "has no addresses, skipping"
                                    )
                                    continue

                                # Validate addresses are public and not reserved
                                valid_addrs = []
                                for addr in addrs:
                                    addr_str = str(addr)
                                    if is_reserved_or_private_addr(addr_str):
                                        logger.debug(
                                            "Skipping reserved address "
                                            f"{addr_str} for provider "
                                            f"{provider_id}"
                                        )
                                        continue
                                    valid_addrs.append(addr)

                                # Require at least one valid public address
                                if not valid_addrs:
                                    logger.warning(
                                        f"Provider {provider_id} "
                                        "has no public addresses, skipping"
                                    )
                                    continue

                                # Add to provider store
                                provider_info = PeerInfo(provider_id, valid_addrs)
                                self.provider_store.add_provider(key, provider_info)
                                provider_count += 1
                                logger.debug(
                                    f"Added provider {provider_id} for key {key.hex()}"
                                )

                                # Process the signed-records of provider if sent
                                if not maybe_consume_signed_record(
                                    provider_proto, self.host
                                ):
                                    logger.error(
                                        "Received an invalid-signed-record,"
                                        "skipping provider"
                                    )
                                    continue
                            except Exception as e:
                                logger.warning(f"Failed to process provider info: {e}")

                        # Per spec: ADD_PROVIDER echoes the request to confirm success.
                        # If verification fails, the server MUST close the stream
                        # without sending a response.
                        response = Message()
                        response.type = Message.MessageType.ADD_PROVIDER
                        response.key = key
                        response_bytes = response.SerializeToString()
                        await stream.write(varint.encode(len(response_bytes)))
                        await stream.write(response_bytes)
                        logger.debug("ADD_PROVIDER processed, sent echo response")

                    # Handle GET_PROVIDERS message
                    elif message.type == Message.MessageType.GET_PROVIDERS:
                        # Process GET_PROVIDERS
                        key = message.key
                        logger.debug(f"GET_PROVIDERS request key {key.hex()}")

                        # Consume the source signed_peer_record if sent
                        if not maybe_consume_signed_record(message, self.host, peer_id):
                            logger.error(
                                "Received an invalid-signed-record, dropping the stream"
                            )
                            should_reset = True
                            break

                        # Validate key is not empty
                        if not key:
                            logger.warning("GET_PROVIDERS with empty key, ignoring")
                            should_reset = True
                            break

                        # Validate key length (per go-libp2p, max ~128 bytes)
                        if len(key) > 128:
                            logger.warning(
                                f"GET_PROVIDERS key too long "
                                f"({len(key)} bytes), ignoring"
                            )
                            should_reset = True
                            break

                        # Per spec: key is set to a CID
                        # Log a warning if key doesn't look like a CID,
                        # but don't reject (backward compatibility)
                        if not is_cid_like_key(key):
                            logger.debug("GET_PROVIDERS key does not look like a CID")

                        # Metrics event
                        event.get_providers = True

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
                            provider_proto.connection = get_connection_type(
                                self.host, provider_info.peer_id
                            )

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

                        # Also include closest peers (always, per IPFS spec)
                        closest_peers = self.routing_table.find_local_closest_peers(
                            key, BUCKET_SIZE
                        )
                        logger.debug(
                            f"Including {len(closest_peers)} closest peers"
                            " in GET_PROVIDERS response"
                        )

                        for peer in closest_peers:
                            # Skip if peer is the requester
                            if peer == peer_id:
                                continue

                            peer_proto = response.closerPeers.add()
                            peer_proto.id = peer.to_bytes()
                            peer_proto.connection = get_connection_type(self.host, peer)

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
                            should_reset = True
                            break

                        # Validate key is not empty
                        if not key:
                            logger.warning("GET_VALUE with empty key, ignoring")
                            should_reset = True
                            break

                        # Validate key size (max 128 bytes per go-libp2p)
                        if len(key) > 128:
                            logger.warning(
                                f"GET_VALUE key too long ({len(key)} bytes), ignoring"
                            )
                            should_reset = True
                            break

                        # Metrics Event
                        event.get_value = True

                        value_record = self.value_store.get(key)
                        if value_record:
                            # Check record age - delete and don't serve
                            # expired records
                            time_received = parse_time_received(
                                value_record.timeReceived
                            )
                            if time_received is not None:
                                if time.time() - time_received > MAX_RECORD_AGE:
                                    logger.debug(
                                        f"Record for key {key.hex()} "
                                        "expired, deleting and not serving"
                                    )
                                    self.value_store.remove(key)
                                    value_record = None

                            # Validate signature before serving
                            if value_record and value_record.signature:
                                from libp2p.records.utils import verify_record

                                if not verify_record(
                                    value_record.signature,
                                    value_record.author,
                                    key,
                                    value_record.value,
                                ):
                                    logger.debug(
                                        f"Record for key {key.hex()} "
                                        "has invalid signature, removing"
                                    )
                                    self.value_store.remove(key)
                                    value_record = None
                            # If timeReceived is unparseable, serve the
                            # record anyway (backwards compatibility)

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

                            # Include closerPeers per spec even when value is found
                            closest_peers = self.routing_table.find_local_closest_peers(
                                key, BUCKET_SIZE
                            )
                            for peer in closest_peers:
                                if peer == peer_id:
                                    continue
                                peer_proto = response.closerPeers.add()
                                peer_proto.id = peer.to_bytes()
                                peer_proto.connection = get_connection_type(
                                    self.host, peer
                                )
                                closer_peer_envelope = (
                                    self.host.get_peerstore().get_peer_record(peer)
                                )
                                if closer_peer_envelope is not None:
                                    peer_proto.signedRecord = (
                                        closer_peer_envelope.marshal_envelope()
                                    )
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
                            logger.debug(
                                "Sent GET_VALUE response with record and closer peers"
                            )
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
                                key, BUCKET_SIZE
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
                                peer_proto.connection = get_connection_type(
                                    self.host, peer
                                )

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
                    elif (
                        message.type == Message.MessageType.PUT_VALUE
                        and message.HasField("record")
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
                            should_reset = True
                            break

                        # Validate record key matches the message key
                        if message.key != key:
                            logger.warning(
                                "PUT_VALUE record key does not match message key"
                            )
                            should_reset = True
                            break

                        # Validate key is not empty
                        if not key:
                            logger.warning("PUT_VALUE with empty key, ignoring")
                            should_reset = True
                            break

                        event.put_value = True

                        try:
                            if not (key and value):
                                raise ValueError(
                                    "Missing key or value in PUT_VALUE message"
                                )

                            # Validate record size
                            record_bytes = message.record.SerializeToString()
                            if len(record_bytes) > MAX_RECORD_SIZE:
                                raise ValueError("Record too large")

                            # Clean the record to prevent timestamp forgery
                            cleaned_record = clean_record(message.record)
                            cleaned_record.timeReceived = format_time_rfc3339()

                            # Validate the key-value pair before storing
                            key_str = key.decode("utf-8")
                            if self.validator is None:
                                raise ValueError("Validator required for DHT ops")
                            self.validator.validate(key_str, value)

                            # Verify signature if present (py-libp2p record format)
                            if cleaned_record.signature and cleaned_record.author:
                                from libp2p.records.utils import verify_record

                                if not verify_record(
                                    cleaned_record.signature,
                                    cleaned_record.author,
                                    key,
                                    value,
                                ):
                                    raise ValueError("Record sig verification failed")

                            # Compare against existing record using Validator.Select
                            existing_record = self.value_store.get(key)
                            if existing_record is not None:
                                try:
                                    best_idx = self.validator.select(
                                        key_str, [existing_record.value, value]
                                    )
                                    # best_idx=0 means existing is better, reject new
                                    if best_idx == 0:
                                        logger.debug(
                                            f"Rejecting PUT_VALUE for {key.hex()}: "
                                            "existing record is better"
                                        )
                                        # Still send acknowledgement per spec
                                        success = False
                                    else:
                                        # New record is better, store it
                                        self.value_store.put_record(key, cleaned_record)
                                        logger.debug(
                                            f"Stored value for key {key.hex()} "
                                            "(new record preferred)"
                                        )
                                        success = True
                                except Exception:
                                    # Per spec: if validation fails, do NOT store
                                    # the record and close the stream
                                    logger.warning(
                                        f"validator.select() failed for key "
                                        f"{key.hex()}, rejecting PUT_VALUE"
                                    )
                                    success = False
                            else:
                                # No existing record, store the new one
                                self.value_store.put_record(key, cleaned_record)
                                logger.debug(f"Stored value for key {key.hex()}")
                                success = True

                            # Per spec: Sliding window PUT_VALUE propagation
                            # When a value is stored, propagate it to the k
                            # closest peers (entry correction)
                            if success:
                                try:
                                    await self._propagate_to_closest_peers(
                                        key, value, cleaned_record
                                    )
                                except Exception as e:
                                    logger.debug(f"Failed to propagate value: {e}")

                        except Exception as e:
                            logger.warning(
                                f"Failed to store value {value.hex()} for key "
                                f"{key.hex()}: {e}"
                            )
                            should_reset = True

                        # Per spec: only echo the request if validation
                        # succeeds
                        if success:
                            response = Message()
                            response.type = Message.MessageType.PUT_VALUE
                            response.key = key
                            # Echo the cleaned record back per spec
                            response.record.CopyFrom(cleaned_record)

                            # Create sender_signed_peer_record
                            envelope_bytes, _ = env_to_send_in_RPC(self.host)
                            response.senderRecord = envelope_bytes

                            # Serialize and send response
                            response_bytes = response.SerializeToString()
                            await stream.write(varint.encode(len(response_bytes)))
                            await stream.write(response_bytes)
                            logger.debug("Sent PUT_VALUE acknowledgement")
                        else:
                            # Per spec: if validation fails, reset the stream
                            should_reset = True
                            break

                    # Handle PUT_VALUE without record field
                    # Per spec: if verification fails, close the stream without
                    # sending a response.
                    elif message.type == Message.MessageType.PUT_VALUE:
                        logger.warning(f"PUT_VALUE w/o record from {peer_id}")
                        should_reset = True
                        break

                except Exception as proto_err:
                    logger.warning(f"Failed to parse protobuf message: {proto_err}")
                    should_reset = True
                    break

                # Send KAD-DHT event to Metrics
                if stream.metric_send_channel is not None:
                    await stream.metric_send_channel.send(event)

        except Exception as e:
            logger.error(f"Error handling DHT stream: {e}")
            # Per spec: "On any error, the stream is reset."
            try:
                await stream.reset()
            except Exception:
                await stream.close()
        else:
            # Per spec: On any error in the handler, the stream is reset.
            # Only close gracefully if the handler completed without errors.
            if should_reset:
                try:
                    await stream.reset()
                except Exception:
                    await stream.close()
            else:
                await stream.close()

    def _check_provider_rate_limit(self, peer_id: ID) -> bool:
        """
        Check if a peer is within the ADD_PROVIDER rate limit.

        Returns True if the request should be allowed, False if rate limited.
        """
        now = time.time()
        peer_key = str(peer_id)

        if peer_key in self._provider_rate_limits:
            last_time, count = self._provider_rate_limits[peer_key]
            if now - last_time < self._provider_rate_window:
                if count >= self._provider_rate_max:
                    logger.debug(
                        f"Rate limiting ADD_PROVIDER from peer {peer_id} "
                        f"({count} in {now - last_time:.1f}s)"
                    )
                    return False
                self._provider_rate_limits[peer_key] = (last_time, count + 1)
            else:
                self._provider_rate_limits[peer_key] = (now, 1)
        else:
            self._provider_rate_limits[peer_key] = (now, 1)

        return True

    async def refresh_routing_table(self) -> None:
        """Refresh the routing table."""
        logger.debug("Refreshing routing table")
        if getattr(self, "rt_refresh_manager", None) is not None:
            await self.rt_refresh_manager._do_refresh(force=True)  # type: ignore
        else:
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
            raise ValueError("Validator required for DHT operations")
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

        # 2. Get closest peers via network lookup (not just local routing table)
        closest_peers = [
            peer
            for peer in await self.peer_routing.find_closest_peers_network(key_bytes)
            if peer != self.local_peer_id
        ]
        logger.debug(f"Found {len(closest_peers)} peers to store value at")

        # 3. Store at remote peers using a semaphore-based sliding window.
        #    Up to ALPHA stores run concurrently; a new one starts as soon as
        #    any in-flight store completes.
        stored_count_list: list[int] = [0]
        sem = trio.Semaphore(ALPHA)

        async def store_one(peer: ID) -> None:
            try:
                with trio.move_on_after(QUERY_TIMEOUT):
                    success = await self.value_store._store_at_peer(
                        peer, key_bytes, value
                    )
                    if success:
                        stored_count_list[0] += 1
                        logger.debug(f"Stored value at peer {peer}")
                    else:
                        logger.debug(f"Failed to store value at peer {peer}")
            except Exception as e:
                logger.debug(f"Error storing value at peer {peer}: {e}")
            finally:
                sem.release()

        async with trio.open_nursery() as nursery:
            for peer in closest_peers:
                await sem.acquire()
                nursery.start_soon(store_one, peer)

        logger.info(f"Successfully stored value at {stored_count_list[0]} peers")

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

        # Validate quorum parameter
        if quorum < 0:
            quorum = 0

        # Convert string key to bytes for lookup
        key_bytes = key.encode("utf-8")

        # 1. Check local store first
        value_record = self.value_store.get(key_bytes)
        if value_record:
            logger.debug("Found value locally")
            return value_record.value

        # 2. Get closest peers via network lookup (iterative FIND_NODE)
        closest_peers = [
            peer
            for peer in await self.peer_routing.find_closest_peers_network(key_bytes)
            if peer != self.local_peer_id
        ]
        logger.debug(f"Searching {len(closest_peers)} peers for value")

        # Collect valid records from peers: mapping peer -> Record
        valid_records: list[tuple[ID, Record]] = []
        # Per spec: Pb = peers that returned the best value
        # Po = peers that returned an outdated/worse value
        peers_best: set[ID] = set()  # Pb
        peers_outdated: set[ID] = set()  # Po
        # Track peers that returned no valid record (for entry correction)
        peers_with_no_record: set[ID] = set()
        # Track best value for comparison (use list as mutable container)
        best_value_container: list[bytes | None] = [None]

        # 3. Query peers using a semaphore-based sliding window (up to ALPHA
        #    concurrent queries). A new query starts as soon as any finishes.
        #
        #    When quorum is reached:
        #    - Cancel all outstanding queries (per spec)
        #    - This ensures we return quickly once we have enough answers
        total_responses_list: list[int] = [0]
        sem = trio.Semaphore(ALPHA)
        quorum_reached = trio.Event()
        # Track queried peers to avoid duplicates
        queried_peers: set[ID] = set()
        # Candidate peers for iterative lookup (closer peers from responses)
        # Use list wrapper for mutable reference in closure
        candidate_peers_wrapper: list[list[ID]] = [list(closest_peers)]
        # Per-query cancel scopes for the in-flight queries below. Each query
        # runs in its own scope so that, when quorum is reached, we can cancel
        # the outstanding slow queries without cancelling the scheduling loop
        # (which must keep running to stop dispatching and collect the results).
        query_scopes: list[trio.CancelScope] = []

        async def query_one(peer: ID) -> None:
            closer_peers: list[ID] = []
            try:
                with trio.move_on_after(QUERY_TIMEOUT):
                    result = await self.value_store._get_from_peer(
                        peer, key_bytes, return_record=True, return_closer_peers=True
                    )
                    if result is None or not isinstance(result, tuple):
                        peers_with_no_record.add(peer)
                        return
                    rec, closer_peers = result
                    if rec is not None:
                        total_responses_list[0] += 1
                        try:
                            if self.validator is None:
                                raise ValueError("Validator is required")
                            if not isinstance(rec, Record):
                                raise TypeError("Expected Record type")
                            self.validator.validate(key, rec.value)

                            # Per spec: track Pb and Po sets
                            best_val = best_value_container[0]
                            if best_val is None:
                                # First valid record becomes the best
                                best_value_container[0] = rec.value
                                peers_best.add(peer)
                            elif rec.value == best_val:
                                # Same as current best -> Pb
                                peers_best.add(peer)
                                # Remove from Po if it was there
                                peers_outdated.discard(peer)
                            else:
                                # Different value -> compare with best
                                values = [best_val, rec.value]
                                best_idx = self.validator.select(key, values)
                                if best_idx == 1:
                                    # New value is better!
                                    # Old best peers become outdated
                                    peers_outdated.update(peers_best)
                                    peers_best.clear()
                                    best_value_container[0] = rec.value
                                    peers_best.add(peer)
                                else:
                                    # Current best wins, new peer is outdated
                                    peers_outdated.add(peer)
                                    peers_best.discard(peer)

                            valid_records.append((peer, rec))
                            logger.debug(f"Found valid record at peer {peer}")
                            if quorum and len(valid_records) >= quorum:
                                logger.debug(
                                    f"Quorum reached "
                                    f"({len(valid_records)} valid records)"
                                )
                                quorum_reached.set()
                                # Per spec: cancel outstanding requests only
                                # (not the scheduling loop below)
                                for scope in query_scopes:
                                    scope.cancel()
                        except Exception as e:
                            peers_with_no_record.add(peer)
                            logger.debug(
                                f"Received invalid record from {peer}, discarding: {e}"
                            )
                    else:
                        # Peer returned no record
                        peers_with_no_record.add(peer)
            except Exception as e:
                peers_with_no_record.add(peer)
                logger.debug(f"Error querying peer {peer}: {e}")
            finally:
                # Add closer peers from response to candidates for iterative lookup
                if closer_peers:
                    from .utils import sort_peer_ids_by_distance

                    candidates = candidate_peers_wrapper[0]
                    for cp in closer_peers:
                        if (
                            cp not in queried_peers
                            and cp not in candidates
                            and cp != self.local_peer_id
                        ):
                            candidates.append(cp)
                    # Re-sort candidates by distance to key (per spec)
                    candidate_peers_wrapper[0] = sort_peer_ids_by_distance(
                        key_bytes, candidates
                    )
                sem.release()

        async def run_query(peer: ID, scope: trio.CancelScope) -> None:
            """Run a single peer query inside its own quorum cancel scope."""
            with scope:
                await query_one(peer)

        async with trio.open_nursery() as nursery:
            # Iterative lookup: query peers, add closer peers, continue
            while candidate_peers_wrapper[0] and not quorum_reached.is_set():
                # Take next unqueried peer from candidates
                while candidate_peers_wrapper[0]:
                    peer = candidate_peers_wrapper[0].pop(0)
                    if peer not in queried_peers:
                        queried_peers.add(peer)
                        break
                else:
                    break

                await sem.acquire()
                if quorum_reached.is_set():
                    sem.release()
                    break
                scope = trio.CancelScope()
                query_scopes.append(scope)
                nursery.start_soon(run_query, peer, scope)

        logger.debug(
            f"get_value query complete: {total_responses_list[0]} responses, "
            f"{len(valid_records)} valid records from {len(closest_peers)} peers"
        )

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
                f"Selected best value at index {best_idx} using validator.select()"
            )

            best_peer, best_rec = valid_records[best_idx]
            best_value = best_rec.value

            # Per spec: Entry correction - propagate best value to Po peers
            # (peers that returned outdated values)
            # Also propagate to peers in closest_peers[:k] that had no record
            if peers_outdated:
                logger.debug(
                    f"Entry correction: propagating best value to "
                    f"{len(peers_outdated)} peers with outdated values (Po)"
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
                    for p in peers_outdated:
                        nursery.start_soon(propagate, p)

            # Entry correction: also update peers that returned no record
            # but are among the k closest to the key (per spec requirement)
            missing_peers = [
                p for p in peers_with_no_record if p in closest_peers[:BUCKET_SIZE]
            ]
            if missing_peers:
                logger.debug(
                    f"Entry correction: propagating value to {len(missing_peers)} "
                    "peers that had no record among k closest"
                )

                async def propagate_to_missing(peer: ID) -> None:
                    try:
                        with trio.move_on_after(QUERY_TIMEOUT):
                            await self.value_store._store_at_peer(
                                peer, key_bytes, best_value, record=best_rec
                            )
                            logger.debug(
                                f"Propagated record to peer {peer} (had no record)"
                            )
                    except Exception as e:
                        logger.debug(f"Failed to propagate to peer {peer}: {e}")

                async with trio.open_nursery() as nursery:
                    for p in missing_peers:
                        nursery.start_soon(propagate_to_missing, p)

            # Store the best record locally (preserve original signature)
            self.value_store.put_record(key_bytes, best_rec)
            logger.info("Successfully retrieved value from network")
            return best_value

        # 5. Not found
        logger.warning(f"Value not found for key {key}")
        return None

    async def _propagate_to_closest_peers(
        self, key: bytes, value: bytes, record: Record
    ) -> None:
        """
        Propagate a value to the k closest peers (sliding window PUT_VALUE).

        Per spec: when a value is stored, it should be propagated to ensure
        availability. This implements entry correction for PUT_VALUE.

        :param key: The key being stored
        :param value: The value being stored
        :param record: The signed record to propagate
        """
        # Find k closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)

        # Propagate to k closest peers in batches of ALPHA
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]
            if not batch:
                break

            async def store_at_peer(peer_id: ID) -> None:
                if peer_id == self.local_peer_id:
                    return
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        await self.value_store._store_at_peer(
                            peer_id, key, value, record=record
                        )
                        logger.debug(f"Propagated value to peer {peer_id}")
                except Exception as e:
                    logger.debug(f"Failed to propagate to peer {peer_id}: {e}")

            async with trio.open_nursery() as nursery:
                for peer_id in batch:
                    nursery.start_soon(store_at_peer, peer_id)

    # Add these methods in the Utility methods section

    # Utility methods

    async def add_peer(
        self, peer_id: ID, *, skip_server_mode_check: bool = False
    ) -> bool:
        """
        Add a peer to the routing table.

        params: peer_id: The peer ID to add.
        params: skip_server_mode_check: If True, skip the server-mode protocol check

        Returns
        -------
        bool
            True if peer was added or updated, False otherwise.

        """
        return await self.routing_table.add_peer(
            peer_id, skip_server_mode_check=skip_server_mode_check
        )

    async def provide(self, key: str) -> bool:
        """
        Reference to provider_store.provide for convenience.

        Accepts either a CID string or a multihash hex string.
        """
        from libp2p.bitswap.cid import parse_cid

        try:
            cid_obj = parse_cid(key)
            key_bytes = cid_obj.multihash
        except (ValueError, TypeError):
            try:
                key_bytes = bytes.fromhex(key)
            except ValueError:
                key_bytes = key.encode("utf-8")
        return await self.provider_store.provide(key_bytes)

    async def find_providers(self, key: str, count: int = 20) -> list[PeerInfo]:
        """
        Reference to provider_store.find_providers for convenience.

        Accepts either a CID string or a multihash hex string.
        """
        from libp2p.bitswap.cid import parse_cid

        try:
            cid_obj = parse_cid(key)
            key_bytes = cid_obj.multihash
        except (ValueError, TypeError):
            try:
                key_bytes = bytes.fromhex(key)
            except ValueError:
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
