"""
QUIC Listener
"""

import logging
import socket
import struct
import sys
import time
from typing import TYPE_CHECKING

from aioquic.quic import events
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import QuicPacketType
from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.custom_types import (
    TProtocol,
    TQUICConnHandlerFn,
)
from libp2p.transport.quic.security import (
    LIBP2P_TLS_EXTENSION_OID,
    QUICTLSConfigManager,
)

from .config import QUICTransportConfig
from .connection import QUICConnection
from .connection_id_registry import ConnectionIDRegistry
from .exceptions import QUICListenError
from .utils import (
    create_quic_multiaddr,
    create_server_config_from_base,
    custom_quic_version_to_wire_format,
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    quic_multiaddr_to_endpoint,
)

if TYPE_CHECKING:
    from .transport import QUICTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class QUICPacketInfo:
    """Information extracted from a QUIC packet header."""

    def __init__(
        self,
        version: int,
        destination_cid: bytes,
        source_cid: bytes,
        packet_type: QuicPacketType,
        token: bytes | None = None,
    ):
        self.version = version
        self.destination_cid = destination_cid
        self.source_cid = source_cid
        self.packet_type = packet_type
        self.token = token


class QUICListener(IListener):
    """
    QUIC Listener with connection ID handling and protocol negotiation.
    """

    def __init__(
        self,
        transport: "QUICTransport",
        handler_function: TQUICConnHandlerFn,
        quic_configs: dict[TProtocol, QuicConfiguration],
        config: QUICTransportConfig,
        security_manager: QUICTLSConfigManager | None = None,
    ):
        """Initialize enhanced QUIC listener."""
        self._transport = transport
        self._handler = handler_function
        self._quic_configs = quic_configs
        self._config = config
        self._security_manager = security_manager

        # Network components
        self._socket: trio.socket.SocketType | None = None
        self._bound_addresses: list[Multiaddr] = []

        # Connection ID registry for managing all Connection ID mappings
        self._connection_lock = trio.Lock()
        self._registry = ConnectionIDRegistry(self._connection_lock)

        # Sequence counters are now managed by the registry for better encapsulation

        # Version negotiation support
        self._supported_versions = self._get_supported_versions()

        # Listener state
        self._closed = False
        self._listening = False
        self._nursery: trio.Nursery | None = None

        # Serialize promotion of pending connections to avoid duplicate promotions
        # and repeated connect() calls under concurrent packet processing.
        self._promotion_lock = trio.Lock()
        # Keyed by underlying aioquic QuicConnection identity (not by CID), because
        # the same QuicConnection may be observed under multiple destination CIDs.
        self._promotion_locks: dict[int, trio.Lock] = {}
        self._conn_by_quic_id: dict[int, QUICConnection] = {}
        self._pending_cid_by_quic_id: dict[int, bytes] = {}
        self._handler_invoked_quic_ids: set[int] = set()

        # Performance tracking
        self._stats = {
            "connections_accepted": 0,
            "connections_rejected": 0,
            "version_negotiations": 0,
            "bytes_received": 0,
            "packets_processed": 0,
            "invalid_packets": 0,
            "fallback_routing_used": 0,
        }

    def _get_supported_versions(self) -> set[int]:
        """Get wire format versions for all supported QUIC configurations."""
        versions: set[int] = set()
        for protocol in self._quic_configs:
            try:
                config = self._quic_configs[protocol]
                wire_versions = config.supported_versions
                for version in wire_versions:
                    versions.add(version)
            except Exception as e:
                logger.warning(f"Failed to get wire version for {protocol}: {e}")
        return versions

    def parse_quic_packet(self, data: bytes) -> QUICPacketInfo | None:
        """
        Parse QUIC packet header to extract connection IDs and version.
        Based on RFC 9000 packet format.
        """
        try:
            if len(data) < 1:
                return None

            # Read first byte to get packet type and flags
            first_byte = data[0]

            # Check if this is a long header packet (version negotiation, initial, etc.)
            is_long_header = (first_byte & 0x80) != 0

            if not is_long_header:
                # We are using standard Connection ID length everywhere
                connection_id_length = 8

                if len(data) < 1 + connection_id_length:
                    return None

                destination_connection_id = data[1 : 1 + connection_id_length]

                return QUICPacketInfo(
                    version=1,  # Assume QUIC v1 for established connections
                    destination_cid=destination_connection_id,
                    source_cid=b"",  # Not available in short header
                    packet_type=QuicPacketType.ONE_RTT,
                    token=b"",
                )

            # Long header packet parsing
            offset = 1

            # Extract version (4 bytes)
            if len(data) < offset + 4:
                return None
            version = struct.unpack("!I", data[offset : offset + 4])[0]
            offset += 4

            # Extract destination connection ID length and value
            if len(data) < offset + 1:
                return None
            destination_connection_id_length = data[offset]
            offset += 1

            if len(data) < offset + destination_connection_id_length:
                return None
            destination_connection_id = data[
                offset : offset + destination_connection_id_length
            ]
            offset += destination_connection_id_length

            # Extract source connection ID length and value
            if len(data) < offset + 1:
                return None
            source_connection_id_length = data[offset]
            offset += 1

            if len(data) < offset + source_connection_id_length:
                return None
            source_connection_id = data[offset : offset + source_connection_id_length]
            offset += source_connection_id_length

            # Determine packet type from first byte
            packet_type_value = (first_byte & 0x30) >> 4

            packet_value_to_type_mapping = {
                0: QuicPacketType.INITIAL,
                1: QuicPacketType.ZERO_RTT,
                2: QuicPacketType.HANDSHAKE,
                3: QuicPacketType.RETRY,
                4: QuicPacketType.VERSION_NEGOTIATION,
                5: QuicPacketType.ONE_RTT,
            }

            # For Initial packets, extract token
            token = b""
            if packet_type_value == 0:  # Initial packet
                if len(data) < offset + 1:
                    return None
                # Token length is variable-length integer
                token_len, token_len_bytes = self._decode_varint(data[offset:])
                offset += token_len_bytes

                if len(data) < offset + token_len:
                    return None
                token = data[offset : offset + token_len]

            return QUICPacketInfo(
                version=version,
                destination_cid=destination_connection_id,
                source_cid=source_connection_id,
                packet_type=packet_value_to_type_mapping.get(packet_type_value)
                or QuicPacketType.INITIAL,
                token=token,
            )

        except Exception as e:
            logger.debug(f"Failed to parse QUIC packet: {e}")
            return None

    def _decode_varint(self, data: bytes) -> tuple[int, int]:
        """Decode QUIC variable-length integer."""
        if len(data) < 1:
            return 0, 0

        first_byte = data[0]
        length_bits = (first_byte & 0xC0) >> 6

        if length_bits == 0:
            return first_byte & 0x3F, 1
        elif length_bits == 1:
            if len(data) < 2:
                return 0, 0
            return ((first_byte & 0x3F) << 8) | data[1], 2
        elif length_bits == 2:
            if len(data) < 4:
                return 0, 0
            return ((first_byte & 0x3F) << 24) | (data[1] << 16) | (
                data[2] << 8
            ) | data[3], 4
        else:  # length_bits == 3
            if len(data) < 8:
                return 0, 0
            value = (first_byte & 0x3F) << 56
            for i in range(1, 8):
                value |= data[i] << (8 * (7 - i))
            return value, 8

    async def _process_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process incoming QUIC packet with optimized routing."""
        try:
            self._stats["packets_processed"] += 1
            self._stats["bytes_received"] += len(data)

            # Periodic stats logging every 1000 packets
            if self._stats["packets_processed"] % 1000 == 0:
                registry_stats = self._registry.get_stats()
                lock_stats_raw = registry_stats.get("lock_stats", {})
                # Type check: lock_stats should be a dict
                lock_stats = lock_stats_raw if isinstance(lock_stats_raw, dict) else {}
                logger.debug(
                    f"Registry stats after {self._stats['packets_processed']} packets: "
                    f"lock_acquisitions={lock_stats.get('acquisitions', 0)}, "
                    f"max_wait_time="
                    f"{lock_stats.get('max_wait_time', 0) * 1000:.2f}ms, "
                    f"max_hold_time="
                    f"{lock_stats.get('max_hold_time', 0) * 1000:.2f}ms, "
                    f"max_concurrent_holds="
                    f"{lock_stats.get('max_concurrent_holds', 0)}, "
                    f"fallback_routing="
                    f"{registry_stats.get('fallback_routing_count', 0)}"
                )

            packet_info = self.parse_quic_packet(data)
            if packet_info is None:
                self._stats["invalid_packets"] += 1
                return

            destination_connection_id = packet_info.destination_cid

            # Determine if this is an initial packet (inspired by quinn)
            is_initial = packet_info.packet_type == QuicPacketType.INITIAL

            # Look up connection by Connection ID (check initial Connection IDs for
            # initial packets)
            find_connection_id_start = time.time()
            (
                connection_obj,
                pending_quic_conn,
                is_pending,
            ) = await self._registry.find_by_connection_id(
                destination_connection_id, is_initial=is_initial
            )
            find_connection_id_duration = time.time() - find_connection_id_start
            if (
                find_connection_id_duration > 0.001
            ):  # Log slow find_by_connection_id (>1ms)
                logger.debug(
                    f"Slow find_by_connection_id in _process_packet: "
                    f"{find_connection_id_duration * 1000:.2f}ms "
                    f"for Connection ID {destination_connection_id.hex()[:8]}, "
                    f"is_initial={is_initial}"
                )

            if not connection_obj and not pending_quic_conn:
                if is_initial:
                    pending_quic_conn = await self._handle_new_connection(
                        data, addr, packet_info
                    )
                else:
                    # Try to find connection by address (fallback routing)
                    # This handles the race condition where packets with new
                    # Connection IDs arrive before ConnectionIdIssued events
                    # are processed
                    fallback_start = time.time()
                    (
                        connection_obj,
                        original_connection_id,
                    ) = await self._registry.find_by_address(addr)
                    fallback_duration = time.time() - fallback_start
                    if fallback_duration > 0.01:  # Log slow fallback routing (>10ms)
                        logger.debug(
                            f"Slow fallback routing: {fallback_duration * 1000:.2f}ms "
                            f"for Connection ID {destination_connection_id.hex()[:8]} "
                            f"at {addr}"
                        )

                    if connection_obj:
                        # Found connection by address - register new Connection ID
                        # Track fallback routing usage
                        self._stats["fallback_routing_used"] += 1
                        registry = self._registry
                        await registry.register_new_connection_id_for_existing_conn(
                            destination_connection_id, connection_obj, addr
                        )
                        if original_connection_id:
                            logger.debug(
                                f"Registered new Connection ID "
                                f"{destination_connection_id.hex()[:8]} "
                                f"for existing connection "
                                f"{original_connection_id.hex()[:8]} "
                                f"at address {addr} "
                                f"(fallback mechanism)"
                            )
                    else:
                        # No connection found - drop packet
                        logger.debug(
                            f"No connection found for Connection ID "
                            f"{destination_connection_id.hex()[:8]} at address {addr}, "
                            f"dropping packet"
                        )
                        return

            # Process outside the lock
            if connection_obj:
                await self._handle_established_connection_packet(
                    connection_obj, data, addr, destination_connection_id
                )
            elif pending_quic_conn:
                await self._handle_pending_connection_packet(
                    pending_quic_conn, data, addr, destination_connection_id
                )

        except Exception as e:
            logger.error(f"Error processing packet from {addr}: {e}", exc_info=True)

    async def _handle_established_connection_packet(
        self,
        connection_obj: QUICConnection,
        data: bytes,
        addr: tuple[str, int],
        destination_connection_id: bytes,
    ) -> None:
        """Handle packet for established connection WITHOUT holding connection lock."""
        try:
            await self._route_to_connection(connection_obj, data, addr)

        except Exception as e:
            logger.error(f"Error handling established connection packet: {e}")

    async def _handle_pending_connection_packet(
        self,
        quic_conn: QuicConnection,
        data: bytes,
        addr: tuple[str, int],
        destination_connection_id: bytes,
    ) -> None:
        """Handle packet for pending connection WITHOUT holding connection lock."""
        try:
            logger.debug(
                f"[PENDING] Handling packet for pending connection "
                f"{destination_connection_id.hex()[:8]}... "
                f"({len(data)} bytes from {addr}), "
                f"handshake_complete={quic_conn._handshake_complete}"
            )

            # Check if handshake is complete BEFORE feeding data
            # If complete, promote immediately so connection's event loop
            # handles all events
            if quic_conn._handshake_complete:
                logger.debug(
                    f"[PENDING] Handshake already complete for "
                    f"{destination_connection_id.hex()[:8]}, "
                    f"promoting connection immediately"
                )
                await self._promote_pending_connection(
                    quic_conn, addr, destination_connection_id
                )
                # After promotion, route this packet to the connection
                # so it processes events. The connection will call
                # receive_datagram and process events in its event loop
                connection_obj, _, _ = await self._registry.find_by_connection_id(
                    destination_connection_id
                )
                if connection_obj:
                    logger.debug(
                        f"[PENDING] Routing packet to newly promoted connection "
                        f"{destination_connection_id.hex()[:8]}"
                    )
                    await self._route_to_connection(connection_obj, data, addr)
                else:
                    logger.warning(
                        f"[PENDING] Connection {destination_connection_id.hex()[:8]} "
                        f"not found after promotion!"
                    )
                return

            # Feed data to QUIC connection for handshake progression
            logger.debug(
                "[PENDING] Feeding datagram to QUIC connection for handshake..."
            )
            quic_conn.receive_datagram(data, addr, now=time.time())
            logger.debug("[PENDING] Datagram received by QUIC connection")

            # Process events only for handshake progression (before handshake completes)
            logger.debug(
                "[PENDING] Processing QUIC events for handshake progression..."
            )
            await self._process_quic_events(quic_conn, addr, destination_connection_id)

            # Send any outgoing packets
            logger.debug("[PENDING] Transmitting handshake response...")
            await self._transmit_for_connection(quic_conn, addr)

            # Check again if handshake completed after processing events
            if quic_conn._handshake_complete:
                logger.debug(
                    f"[PENDING] Handshake completed after event processing for "
                    f"{destination_connection_id.hex()[:8]}, promoting connection"
                )
                await self._promote_pending_connection(
                    quic_conn, addr, destination_connection_id
                )
            else:
                logger.debug(
                    f"[PENDING] Handshake still in progress for "
                    f"{destination_connection_id.hex()[:8]}"
                )

        except Exception as e:
            logger.error(
                f"[PENDING] Error handling pending connection "
                f"{destination_connection_id.hex()[:8]}: {e}",
                exc_info=True,
            )

    async def _send_version_negotiation(
        self, addr: tuple[str, int], source_connection_id: bytes
    ) -> None:
        """Send version negotiation packet to client."""
        try:
            self._stats["version_negotiations"] += 1

            # Construct version negotiation packet
            packet = bytearray()

            # First byte: long header (1) + unused bits (0111)
            packet.append(0x80 | 0x70)

            # Version: 0 for version negotiation
            packet.extend(struct.pack("!I", 0))

            # Destination connection ID (echo source CID from client)
            packet.append(len(source_connection_id))
            packet.extend(source_connection_id)

            # Source Connection ID (empty for version negotiation)
            packet.append(0)

            # Supported versions
            for version in sorted(self._supported_versions):
                packet.extend(struct.pack("!I", version))

            # Send the packet
            if self._socket:
                await self._socket.sendto(bytes(packet), addr)
                logger.debug(
                    f"Sent version negotiation to {addr} "
                    f"with versions {sorted(self._supported_versions)}"
                )

        except Exception as e:
            logger.error(f"Failed to send version negotiation to {addr}: {e}")

    async def _handle_new_connection(
        self, data: bytes, addr: tuple[str, int], packet_info: QUICPacketInfo
    ) -> QuicConnection | None:
        """Handle new connection with proper connection ID handling."""
        try:
            logger.debug(f"Starting handshake for {addr}")

            # Find appropriate QUIC configuration
            quic_config = None

            for protocol, config in self._quic_configs.items():
                wire_versions = custom_quic_version_to_wire_format(protocol)
                if wire_versions == packet_info.version:
                    quic_config = config
                    break

            if not quic_config:
                logger.error(
                    f"No configuration found for version 0x{packet_info.version:08x}"
                )
                await self._send_version_negotiation(
                    addr, packet_info.source_cid
                )  # source_cid is from QUICPacketInfo struct
                return None

            if not quic_config:
                raise QUICListenError("Cannot determine QUIC configuration")

            # Create server-side QUIC configuration
            server_config = create_server_config_from_base(
                base_config=quic_config,
                security_manager=self._security_manager,
                transport_config=self._config,
            )

            # Validate certificate has libp2p extension
            if server_config.certificate:
                cert = server_config.certificate
                has_libp2p_ext = False
                for ext in cert.extensions:
                    if ext.oid == LIBP2P_TLS_EXTENSION_OID:
                        has_libp2p_ext = True
                        break
                logger.debug(f"Certificate has libp2p extension: {has_libp2p_ext}")

                if not has_libp2p_ext:
                    logger.error("Certificate missing libp2p extension!")

            logger.debug(
                f"Original destination Connection ID: "
                f"{packet_info.destination_cid.hex()}"
            )

            quic_conn = QuicConnection(
                configuration=server_config,
                original_destination_connection_id=packet_info.destination_cid,
            )

            quic_conn._replenish_connection_ids()
            # Use the first host CID as our routing CID
            if quic_conn._host_cids:
                destination_connection_id = quic_conn._host_cids[0].cid
                logger.debug(
                    f"Using host Connection ID as routing Connection ID: "
                    f"{destination_connection_id.hex()}"
                )
            else:
                # Fallback to random if no host CIDs generated
                import secrets

                destination_connection_id = secrets.token_bytes(8)
                logger.debug(
                    f"Fallback to random Connection ID: "
                    f"{destination_connection_id.hex()}"
                )

            logger.debug(f"Generated {len(quic_conn._host_cids)} host CIDs for client")

            logger.debug(
                f"QUIC connection created for destination Connection ID "
                f"{destination_connection_id.hex()}"
            )

            # Store connection mapping using our generated Connection ID
            # Initial Connection ID has sequence number 0
            sequence = 0
            await self._registry.set_sequence_counter(
                destination_connection_id, sequence
            )
            await self._registry.register_pending(
                destination_connection_id, quic_conn, addr, sequence
            )
            self._pending_cid_by_quic_id[id(quic_conn)] = destination_connection_id

            # Also register the initial destination Connection ID (from client)
            # in _initial_connection_ids
            # This allows proper routing of initial packets (inspired by quinn)
            initial_dcid = packet_info.destination_cid
            await self._registry.register_initial_connection_id(
                initial_dcid, quic_conn, addr, sequence
            )

            # Process initial packet
            quic_conn.receive_datagram(data, addr, now=time.time())
            if quic_conn.tls:
                if self._security_manager:
                    try:
                        quic_conn.tls._request_client_certificate = True
                        logger.debug(
                            "request_client_certificate set to True in server TLS"
                        )
                    except Exception as e:
                        logger.error(f"FAILED to apply request_client_certificate: {e}")

            # Process events and send response
            await self._process_quic_events(quic_conn, addr, destination_connection_id)
            await self._transmit_for_connection(quic_conn, addr)

            logger.debug(
                f"Started handshake for new connection from {addr} "
                f"(version: 0x{packet_info.version:08x}, "
                f"Connection ID: {destination_connection_id.hex()})"
            )

            return quic_conn

        except Exception as e:
            logger.error(f"Error handling new connection from {addr}: {e}")
            self._stats["connections_rejected"] += 1
            return None

    async def _handle_short_header_packet(
        self, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Handle short header packets for established connections."""
        try:
            logger.debug(f" SHORT_HDR: Handling short header packet from {addr}")

            # Try to find connection by address
            connection, connection_id = await self._registry.find_by_address(addr)
            if connection:
                await self._route_to_connection(connection, data, addr)
                return

            # Fallback: try to extract Connection ID from packet
            if len(data) >= 9:  # 1 byte header + 8 byte Connection ID
                potential_connection_id = data[1:9]
                connection, _, _ = await self._registry.find_by_connection_id(
                    potential_connection_id
                )
                if connection:
                    # Update mappings for future packets
                    registry = self._registry
                    await registry.register_new_connection_id_for_existing_conn(
                        potential_connection_id, connection, addr
                    )
                    await self._route_to_connection(connection, data, addr)
                    return

            logger.debug(f"No matching connection found for {addr}")

        except Exception as e:
            logger.error(f"Error handling short header packet from {addr}: {e}")

    async def _route_to_connection(
        self, connection: QUICConnection, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Route packet to existing connection."""
        try:
            # Feed data to the connection's QUIC instance
            connection._quic.receive_datagram(data, addr, now=time.time())
            # NOTE: Established connections process events and transmit in their own
            # event loop. Avoid double-consuming `next_event()` here.

        except Exception as e:
            logger.error(
                f"Error routing packet to connection {addr}: {e}", exc_info=True
            )
            # Remove problematic connection
            await self._remove_connection_by_addr(addr)

    async def _handle_pending_connection(
        self,
        quic_conn: QuicConnection,
        data: bytes,
        addr: tuple[str, int],
        destination_connection_id: bytes,
    ) -> None:
        """Handle packet for a pending (handshaking) connection."""
        try:
            logger.debug(
                f"Handling packet for pending connection "
                f"{destination_connection_id.hex()}"
            )

            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())

            if quic_conn.tls:
                logger.debug(f"TLS state after: {quic_conn.tls.state}")

            # Process events - this is crucial for handshake progression
            await self._process_quic_events(quic_conn, addr, destination_connection_id)

            # Send any outgoing packets - this is where the response should be sent
            await self._transmit_for_connection(quic_conn, addr)

            # Check if handshake completed
            if quic_conn._handshake_complete:
                logger.debug("PENDING: Handshake completed, promoting connection")
                await self._promote_pending_connection(
                    quic_conn, addr, destination_connection_id
                )

        except Exception as e:
            logger.error(
                f"Error handling pending connection "
                f"{destination_connection_id.hex()}: {e}"
            )

            # Remove problematic pending connection
            logger.error(
                f"Removing problematic connection {destination_connection_id.hex()}"
            )
            await self._remove_pending_connection(destination_connection_id)

    async def _process_quic_events(
        self,
        quic_conn: QuicConnection,
        addr: tuple[str, int],
        destination_connection_id: bytes,
    ) -> None:
        """
        Process QUIC events with enhanced debugging.

        NOTE: This should only be called for pending connections. Once a connection
        is promoted, its own event loop will process events. We avoid consuming
        events here that the connection's event loop needs.
        """
        try:
            # Check if connection is already promoted - if so, don't process events here
            # as the connection's event loop will handle them
            find_connection_id_start = time.time()
            connection_obj, _, _ = await self._registry.find_by_connection_id(
                destination_connection_id
            )
            find_connection_id_duration = time.time() - find_connection_id_start
            if (
                find_connection_id_duration > 0.001
            ):  # Log slow find_by_connection_id (>1ms)
                logger.debug(
                    f"Slow find_by_connection_id in _process_quic_events: "
                    f"{find_connection_id_duration * 1000:.2f}ms for Connection ID "
                    f"{destination_connection_id.hex()[:8]}"
                )
            if connection_obj:
                return

            batch_start = time.time()
            event_count = 0
            while True:
                event = quic_conn.next_event()
                if event is None:
                    break

                event_start = time.time()
                event_count += 1

                if isinstance(event, events.ConnectionTerminated):
                    logger.warning(
                        f"ConnectionTerminated - code={event.error_code}, "
                        f"reason={event.reason_phrase} for "
                        f"{destination_connection_id.hex()[:8]} "
                        f"from {addr}"
                    )
                    await self._remove_connection(destination_connection_id)
                    break

                elif isinstance(event, events.HandshakeCompleted):
                    await self._promote_pending_connection(
                        quic_conn, addr, destination_connection_id
                    )

                elif isinstance(event, events.ProtocolNegotiated):
                    # If handshake is complete, promote connection immediately
                    # This can happen before HandshakeCompleted event in some cases
                    (
                        _,
                        pending_conn,
                        is_pending,
                    ) = await self._registry.find_by_connection_id(
                        destination_connection_id
                    )
                    if quic_conn._handshake_complete and is_pending and pending_conn:
                        await self._promote_pending_connection(
                            quic_conn, addr, destination_connection_id
                        )

                elif isinstance(event, events.StreamDataReceived):
                    # For pending connections, if handshake is complete, we should
                    # have already promoted. But if we get here, promote now.
                    # Don't process stream data events here - let the connection's
                    # event loop handle them
                    (
                        connection_obj,
                        pending_conn,
                        is_pending,
                    ) = await self._registry.find_by_connection_id(
                        destination_connection_id
                    )
                    if connection_obj:
                        # Don't process here - the connection's event loop
                        # will handle it
                        pass
                    elif is_pending and pending_conn:
                        if quic_conn._handshake_complete:
                            await self._promote_pending_connection(
                                quic_conn, addr, destination_connection_id
                            )
                            # Connection's event loop will process this event
                        else:
                            logger.warning(
                                f"StreamDataReceived on stream {event.stream_id} "
                                f"but handshake not complete yet for "
                                f"{destination_connection_id.hex()[:8]}! "
                                f"This may indicate early stream data."
                            )

                elif isinstance(event, events.StreamReset):
                    (
                        connection_obj,
                        pending_conn,
                        is_pending,
                    ) = await self._registry.find_by_connection_id(
                        destination_connection_id
                    )
                    if connection_obj:
                        await connection_obj._handle_stream_reset(event)
                    elif is_pending and pending_conn and quic_conn._handshake_complete:
                        # Promote connection to handle stream reset
                        await self._promote_pending_connection(
                            quic_conn, addr, destination_connection_id
                        )
                        (
                            connection_obj,
                            _,
                            _,
                        ) = await self._registry.find_by_connection_id(
                            destination_connection_id
                        )
                        if connection_obj:
                            await connection_obj._handle_stream_reset(event)

                elif isinstance(event, events.ConnectionIdIssued):
                    new_connection_id = event.connection_id
                    # Track sequence number for this connection
                    # Increment sequence counter for this connection using registry
                    sequence = await self._registry.increment_sequence_counter(
                        destination_connection_id
                    )
                    # Also track for the new Connection ID
                    await self._registry.set_sequence_counter(
                        new_connection_id, sequence
                    )
                    # Add new Connection ID to the same address mapping and connection
                    await self._registry.add_connection_id(
                        new_connection_id, destination_connection_id, sequence
                    )

                elif isinstance(event, events.ConnectionIdRetired):
                    retired_connection_id = event.connection_id
                    # Find the connection for this Connection ID
                    connection_obj, _, _ = await self._registry.find_by_connection_id(
                        retired_connection_id
                    )
                    if connection_obj:
                        # Get sequence number of retired Connection ID
                        retired_seq = (
                            await self._registry.get_sequence_for_connection_id(
                                retired_connection_id
                            )
                        )
                        if retired_seq is not None:
                            # Retire Connection IDs in sequence order up to
                            # (but not including) this one
                            # This ensures proper retirement ordering per QUIC spec
                            # We retire all CIDs with sequence < retired_seq
                            await (
                                self._registry.retire_connection_ids_by_sequence_range(
                                    connection_obj, 0, retired_seq
                                )
                            )
                        # Remove the specific retired CID
                        await self._registry.remove_connection_id(retired_connection_id)
                    else:
                        # Connection not found, just remove the CID
                        await self._registry.remove_connection_id(retired_connection_id)

                # Log slow event processing
                event_duration = time.time() - event_start
                if event_duration > 0.01:  # Log slow events (>10ms)
                    logger.debug(
                        f"Slow event processing: {type(event).__name__} took "
                        f"{event_duration * 1000:.2f}ms for Connection ID "
                        f"{destination_connection_id.hex()[:8]}"
                    )

            # Log batch processing time
            batch_duration = time.time() - batch_start
            if batch_duration > 0.01 and event_count > 0:  # Log slow batches
                logger.debug(
                    f"Processed {event_count} events in {batch_duration * 1000:.2f}ms "
                    f"for Connection ID {destination_connection_id.hex()[:8]}"
                )

        except Exception as e:
            logger.debug(f"Error processing events: {e}")

    async def _cleanup_promotion_lock(self, quic_key: int) -> None:
        """
        Clean up promotion lock and related tracking for a quic_key (idempotent).

        This method safely removes all promotion-related state for a connection,
        preventing memory leaks from stale locks and tracking dictionaries.

        Args:
            quic_key: The identity (id()) of the aioquic QuicConnection

        """
        async with self._promotion_lock:
            self._promotion_locks.pop(quic_key, None)
            self._conn_by_quic_id.pop(quic_key, None)
            self._pending_cid_by_quic_id.pop(quic_key, None)
            self._handler_invoked_quic_ids.discard(quic_key)

    async def _promote_pending_connection(
        self,
        quic_conn: QuicConnection,
        addr: tuple[str, int],
        destination_connection_id: bytes,
    ) -> None:
        """Promote pending connection - avoid duplicate creation."""
        promotion_start = time.time()

        quic_key = id(quic_conn)
        pending_cid = self._pending_cid_by_quic_id.get(
            quic_key, destination_connection_id
        )

        # Acquire per-connection promotion lock (keyed by aioquic connection id).
        try:
            async with self._promotion_lock:
                per_cid_lock = self._promotion_locks.get(quic_key)
                if per_cid_lock is None:
                    per_cid_lock = trio.Lock()
                    self._promotion_locks[quic_key] = per_cid_lock
        except Exception:
            # If lock creation fails, cleanup and re-raise
            await self._cleanup_promotion_lock(quic_key)
            raise

        async with per_cid_lock:
            try:
                connection = self._conn_by_quic_id.get(quic_key)
                if connection is None:
                    from .connection import QUICConnection

                    host, port = addr
                    quic_version = "quic"
                    remote_maddr = create_quic_multiaddr(host, port, f"/{quic_version}")

                    connection = QUICConnection(
                        quic_connection=quic_conn,
                        remote_addr=addr,
                        remote_peer_id=None,
                        local_peer_id=self._transport._peer_id,
                        is_initiator=False,
                        maddr=remote_maddr,
                        transport=self._transport,
                        security_manager=self._security_manager,
                        listener_socket=self._socket,
                        listener=self,
                        listener_connection_id=pending_cid,
                    )
                    self._conn_by_quic_id[quic_key] = connection
                else:
                    # Ensure owning listener context is set for O(1) CID registration.
                    if (
                        getattr(connection, "_listener", None) is None
                        or getattr(connection, "_listener_connection_id", None) is None
                    ):
                        try:
                            connection.set_listener_context(self, pending_cid)
                        except Exception:
                            pass

                # Promote/register using the pending routing CID (host CID).
                _, _, is_pending = await self._registry.find_by_connection_id(
                    pending_cid
                )
                if is_pending:
                    await self._registry.promote_pending(pending_cid, connection)
                else:
                    sequence = await self._registry.get_sequence_counter(pending_cid)
                    await self._registry.register_connection(
                        pending_cid, connection, addr, sequence
                    )

                # Ensure the packet's destination CID also routes to this connection.
                if destination_connection_id != pending_cid:
                    await self._registry.register_new_connection_id_for_existing_conn(
                        destination_connection_id, connection, addr
                    )

                if self._nursery:
                    connection._nursery = self._nursery
                    # connect() will start background tasks internally. Avoid calling it
                    # repeatedly when multiple packets race to promote the same CID.
                    if not getattr(connection, "_background_tasks_started", False):
                        await connection.connect(self._nursery)

                if self._security_manager:
                    try:
                        peer_id = await connection._verify_peer_identity_with_security()
                        if peer_id:
                            connection.peer_id = peer_id
                        logger.info(
                            f"Security verification successful for "
                            f"{destination_connection_id.hex()}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Security verification failed for "
                            f"{destination_connection_id.hex()}: {e}"
                        )
                        await connection.close()
                        return

                # Note: connect() already starts background tasks,
                #  so we don't need to call
                # _start_background_tasks() again. The connection's event loop will now
                # process all events from the QUIC connection.

                try:
                    logger.debug(
                        f"Invoking user callback {destination_connection_id.hex()}"
                    )
                    if quic_key not in self._handler_invoked_quic_ids:
                        self._handler_invoked_quic_ids.add(quic_key)
                        await self._handler(connection)

                except Exception as e:
                    logger.error(f"Error in user callback: {e}")

                self._stats["connections_accepted"] += 1
                logger.info(
                    f"Enhanced connection {destination_connection_id.hex()} "
                    f"established from {addr}"
                )

                # Log promotion duration
                promotion_duration = time.time() - promotion_start
                if promotion_duration > 0.01:  # Log slow promotions (>10ms)
                    logger.debug(
                        f"Slow connection promotion: {promotion_duration * 1000:.2f}ms "
                        f"for Connection ID {destination_connection_id.hex()[:8]}"
                    )

            except Exception as e:
                logger.error(
                    f"Error promoting connection {destination_connection_id.hex()}: {e}"
                )
                await self._remove_connection(destination_connection_id)
            finally:
                # Best-effort cleanup of the per-CID lock and related tracking.
                await self._cleanup_promotion_lock(quic_key)

    async def _remove_connection(self, destination_connection_id: bytes) -> None:
        """Remove connection by connection ID."""
        try:
            # Get connection before removing from registry
            connection_obj, _, _ = await self._registry.find_by_connection_id(
                destination_connection_id
            )
            if connection_obj:
                await connection_obj.close()
                # Clean up promotion lock if connection has a quic connection
                if (
                    hasattr(connection_obj, "_quic")
                    and connection_obj._quic is not None
                ):
                    quic_key = id(connection_obj._quic)
                    await self._cleanup_promotion_lock(quic_key)

            # Remove from registry (cleans up all mappings)
            await self._registry.remove_connection_id(destination_connection_id)

            logger.debug(f"Removed connection {destination_connection_id.hex()}")

        except Exception as e:
            logger.error(
                f"Error removing connection {destination_connection_id.hex()}: {e}"
            )

    async def _remove_pending_connection(
        self, destination_connection_id: bytes
    ) -> None:
        """Remove pending connection by connection ID."""
        try:
            await self._registry.remove_pending_connection(destination_connection_id)
            logger.debug(
                f"Removed pending connection {destination_connection_id.hex()}"
            )
        except Exception as e:
            logger.error(
                f"Error removing pending connection "
                f"{destination_connection_id.hex()}: {e}"
            )

    async def _remove_connection_by_addr(self, addr: tuple[str, int]) -> None:
        """Remove connection by address (fallback method)."""
        connection_id = await self._registry.remove_by_address(addr)
        if connection_id:
            # Get connection before removing
            connection_obj, _, _ = await self._registry.find_by_connection_id(
                connection_id
            )
            if connection_obj:
                await connection_obj.close()

    async def _transmit_for_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int]
    ) -> None:
        """Transmit datagrams for a QUIC connection."""
        try:
            # Get current timestamp for timing
            import time

            now = time.time()

            datagrams = quic_conn.datagrams_to_send(now=now)

            if not datagrams:
                return

            # Note: We don't validate packet contents here. The QUIC library
            # (aioquic) handles all packet parsing and validation. This function
            # just transmits the datagrams that aioquic generates.

            socket = self._socket
            if socket is None:
                logger.error("No socket available!")
                return

            for datagram, dest_addr in datagrams:
                try:
                    await socket.sendto(datagram, addr)
                except Exception as send_error:
                    logger.error(f"Socket send failed: {send_error}")
        except Exception as e:
            logger.error(f"Transmission error: {e}", exc_info=True)

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """Start listening on the given multiaddr with enhanced connection handling."""
        if self._listening:
            raise QUICListenError("Already listening")

        if not is_quic_multiaddr(maddr):
            raise QUICListenError(f"Invalid QUIC multiaddr: {maddr}")

        if self._transport._background_nursery:
            active_nursery = self._transport._background_nursery
            logger.debug("Using transport background nursery for listener")
        elif nursery:
            active_nursery = nursery
            self._transport._background_nursery = nursery
            logger.debug("Using provided nursery for listener")
        else:
            raise QUICListenError("No nursery available")

        try:
            host, port = quic_multiaddr_to_endpoint(maddr)

            # Create and configure socket
            self._socket = await self._create_socket(host, port)
            self._nursery = active_nursery

            # Get the actual bound address
            bound_host, bound_port = self._socket.getsockname()
            quic_version = multiaddr_to_quic_version(maddr)
            bound_maddr = create_quic_multiaddr(bound_host, bound_port, quic_version)
            self._bound_addresses = [bound_maddr]

            self._listening = True

            # Start packet handling loop
            active_nursery.start_soon(self._handle_incoming_packets)

            logger.info(
                f"QUIC listener started on {bound_maddr} with connection ID support"
            )
            return True

        except Exception as e:
            await self.close()
            raise QUICListenError(f"Failed to start listening: {e}") from e

    async def _create_socket(self, host: str, port: int) -> trio.socket.SocketType:
        """Create and configure UDP socket."""
        try:
            # Determine address family
            try:
                import ipaddress

                ip = ipaddress.ip_address(host)
                family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
            except ValueError:
                family = socket.AF_INET

            # Create UDP socket
            sock = trio.socket.socket(family=family, type=socket.SOCK_DGRAM)

            # Set socket options
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # type: ignore[attr-defined]

            # Bind to address
            await sock.bind((host, port))

            logger.debug(f"Created and bound UDP socket to {host}:{port}")
            return sock

        except Exception as e:
            raise QUICListenError(f"Failed to create socket: {e}") from e

    async def _handle_incoming_packets(self) -> None:
        """Handle incoming UDP packets with enhanced routing."""
        logger.debug("Started enhanced packet handling loop")

        try:
            while self._listening and self._socket:
                try:
                    # Receive UDP packet
                    data, addr = await self._socket.recvfrom(65536)

                    # Process packet asynchronously
                    if self._nursery:
                        self._nursery.start_soon(self._process_packet, data, addr)

                except trio.ClosedResourceError:
                    logger.debug("Socket closed, exiting packet handler")
                    break
                except Exception as e:
                    logger.error(f"Error receiving packet: {e}")
                    await trio.sleep(0.01)
        except trio.Cancelled:
            logger.info("Packet handling cancelled")
            raise
        finally:
            logger.debug("Enhanced packet handling loop terminated")

    async def close(self) -> None:
        """Close the listener and clean up resources."""
        if self._closed:
            return

        self._closed = True
        self._listening = False

        try:
            # Close all connections
            # Get all Connection IDs before removing (to avoid modifying dict
            # during iteration)
            established_cids = await self._registry.get_all_established_cids()
            pending_cids = await self._registry.get_all_pending_cids()

            # Remove all established connections
            for cid in established_cids:
                await self._remove_connection(cid)

            # Remove all pending connections
            for cid in pending_cids:
                await self._remove_pending_connection(cid)

            # Clean up all remaining promotion locks and tracking
            async with self._promotion_lock:
                self._promotion_locks.clear()
                self._conn_by_quic_id.clear()
                self._pending_cid_by_quic_id.clear()
                self._handler_invoked_quic_ids.clear()

            # Close socket
            if self._socket:
                self._socket.close()
                self._socket = None

            self._bound_addresses.clear()

            logger.info("QUIC listener closed")

        except Exception as e:
            logger.error(f"Error closing listener: {e}")

    async def _remove_connection_by_object(
        self, connection_obj: "QUICConnection"
    ) -> None:
        """Remove a connection by object reference."""
        try:
            # Clean up promotion lock if connection has a quic connection
            if hasattr(connection_obj, "_quic") and connection_obj._quic is not None:
                quic_key = id(connection_obj._quic)
                await self._cleanup_promotion_lock(quic_key)

            # Find the connection ID for this object
            connection_ids = await self._registry.get_all_cids_for_connection(
                connection_obj
            )
            if connection_ids:
                # Remove using the first Connection ID found
                connection_connection_id = connection_ids[0]
                await self._remove_connection(connection_connection_id)
                logger.debug(f"Removed connection {connection_connection_id.hex()}")
            else:
                logger.warning("Connection object not found in tracking")

        except Exception as e:
            logger.error(f"Error removing connection by object: {e}")

    def get_addresses(self) -> list[Multiaddr]:
        """Get the bound addresses."""
        return self._bound_addresses.copy()

    async def _handle_new_established_connection(
        self, connection: QUICConnection
    ) -> None:
        """Handle newly established connection by adding to swarm."""
        try:
            logger.debug(
                f"New QUIC connection established from {connection._remote_addr}"
            )

            if self._transport._swarm:
                logger.debug("Adding QUIC connection directly to swarm")
                await self._transport._swarm.add_conn(connection)
                logger.debug("Successfully added QUIC connection to swarm")
            else:
                logger.error("No swarm available for QUIC connection")
                await connection.close()

        except Exception as e:
            logger.error(f"Error adding QUIC connection to swarm: {e}")
            await connection.close()

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        return tuple(self.get_addresses())

    def is_listening(self) -> bool:
        """
        Check if the listener is currently listening for connections.

        Returns:
            bool: True if the listener is actively listening, False otherwise

        """
        return self._listening and not self._closed

    def get_stats(self) -> dict[str, int | bool]:
        """
        Get listener statistics including the listening state.

        Returns:
            dict: Statistics dictionary with current state information

        """
        stats: dict[str, int | bool] = dict(self._stats)
        stats["is_listening"] = self.is_listening()
        registry_stats = self._registry.get_stats()
        # Extract integer values from registry stats (handle type checking)
        established = registry_stats.get("established_connections", 0)
        pending = registry_stats.get("pending_connections", 0)
        if isinstance(established, int):
            stats["active_connections"] = established
        if isinstance(pending, int):
            stats["pending_connections"] = pending
        # Include registry performance metrics
        fallback_count = registry_stats.get("fallback_routing_count", 0)
        if isinstance(fallback_count, int):
            stats["registry_fallback_routing"] = fallback_count
        # Include lock stats
        lock_stats_raw = registry_stats.get("lock_stats", {})
        if isinstance(lock_stats_raw, dict):
            lock_stats = lock_stats_raw
            stats["registry_lock_acquisitions"] = lock_stats.get("acquisitions", 0)
            stats["registry_max_wait_time_ms"] = int(
                lock_stats.get("max_wait_time", 0.0) * 1000
            )
            stats["registry_max_hold_time_ms"] = int(
                lock_stats.get("max_hold_time", 0.0) * 1000
            )
            stats["registry_max_concurrent_holds"] = lock_stats.get(
                "max_concurrent_holds", 0
            )
        return stats
