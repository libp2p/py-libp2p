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
from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.custom_types import THandler, TProtocol
from libp2p.transport.quic.security import (
    LIBP2P_TLS_EXTENSION_OID,
    QUICTLSConfigManager,
)
from libp2p.custom_types import TQUICConnHandlerFn
from libp2p.custom_types import TQUICStreamHandlerFn
from aioquic.quic.packet import QuicPacketType

from .config import QUICTransportConfig
from .connection import QUICConnection
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
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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
    Enhanced QUIC Listener with proper connection ID handling and protocol negotiation.

    Key improvements:
    - Proper QUIC packet parsing to extract connection IDs
    - Version negotiation following RFC 9000
    - Connection routing based on destination connection ID
    - Support for connection migration
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

        # Enhanced connection management with connection ID routing
        self._connections: dict[
            bytes, QUICConnection
        ] = {}  # destination_cid -> connection
        self._pending_connections: dict[
            bytes, QuicConnection
        ] = {}  # destination_cid -> quic_conn
        self._addr_to_cid: dict[
            tuple[str, int], bytes
        ] = {}  # (host, port) -> destination_cid
        self._cid_to_addr: dict[
            bytes, tuple[str, int]
        ] = {}  # destination_cid -> (host, port)
        self._connection_lock = trio.Lock()

        # Version negotiation support
        self._supported_versions = self._get_supported_versions()

        # Listener state
        self._closed = False
        self._listening = False
        self._nursery: trio.Nursery | None = None

        # Performance tracking
        self._stats = {
            "connections_accepted": 0,
            "connections_rejected": 0,
            "version_negotiations": 0,
            "bytes_received": 0,
            "packets_processed": 0,
            "invalid_packets": 0,
        }

        logger.debug("Initialized enhanced QUIC listener with connection ID support")

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
                # Short header packet - extract destination connection ID
                # For short headers, we need to know the connection ID length
                # This is typically managed by the connection state
                # For now, we'll handle this in the connection routing logic
                return None

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
            dest_cid_len = data[offset]
            offset += 1

            if len(data) < offset + dest_cid_len:
                return None
            dest_cid = data[offset : offset + dest_cid_len]
            offset += dest_cid_len

            # Extract source connection ID length and value
            if len(data) < offset + 1:
                return None
            src_cid_len = data[offset]
            offset += 1

            if len(data) < offset + src_cid_len:
                return None
            src_cid = data[offset : offset + src_cid_len]
            offset += src_cid_len

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
                destination_cid=dest_cid,
                source_cid=src_cid,
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
        """
        Enhanced packet processing with better connection ID routing and debugging.
        """
        try:
            # self._stats["packets_processed"] += 1
            # self._stats["bytes_received"] += len(data)

            print(f"🔧 PACKET: Processing {len(data)} bytes from {addr}")

            # Parse packet to extract connection information
            packet_info = self.parse_quic_packet(data)

            print(
                f"🔧 DEBUG: Pending connections: {[cid.hex() for cid in self._pending_connections.keys()]}"
            )
            print(
                f"🔧 DEBUG: Established connections: {[cid.hex() for cid in self._connections.keys()]}"
            )

            async with self._connection_lock:
                if packet_info:
                    print(
                        f"🔧 PACKET: Parsed packet - version: 0x{packet_info.version:08x}, "
                        f"dest_cid: {packet_info.destination_cid.hex()}, "
                        f"src_cid: {packet_info.source_cid.hex()}"
                    )

                    # Check for version negotiation
                    if packet_info.version == 0:
                        logger.warning(
                            f"Received version negotiation packet from {addr}"
                        )
                        return

                    # Check if version is supported
                    if packet_info.version not in self._supported_versions:
                        print(
                            f"❌ PACKET: Unsupported version 0x{packet_info.version:08x}"
                        )
                        await self._send_version_negotiation(
                            addr, packet_info.source_cid
                        )
                        return

                    # Route based on destination connection ID
                    dest_cid = packet_info.destination_cid

                    # First, try exact connection ID match
                    if dest_cid in self._connections:
                        print(
                            f"✅ PACKET: Routing to established connection {dest_cid.hex()}"
                        )
                        connection = self._connections[dest_cid]
                        await self._route_to_connection(connection, data, addr)
                        return

                    elif dest_cid in self._pending_connections:
                        print(
                            f"✅ PACKET: Routing to pending connection {dest_cid.hex()}"
                        )
                        quic_conn = self._pending_connections[dest_cid]
                        await self._handle_pending_connection(
                            quic_conn, data, addr, dest_cid
                        )
                        return

                    # No existing connection found, create new one
                    print(f"🔧 PACKET: Creating new connection for {addr}")
                    await self._handle_new_connection(data, addr, packet_info)

                else:
                    # Failed to parse packet
                    print(f"❌ PACKET: Failed to parse packet from {addr}")
                    await self._handle_short_header_packet(data, addr)

        except Exception as e:
            logger.error(f"Error processing packet from {addr}: {e}")
            import traceback

            traceback.print_exc()

    async def _send_version_negotiation(
        self, addr: tuple[str, int], source_cid: bytes
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
            packet.append(len(source_cid))
            packet.extend(source_cid)

            # Source connection ID (empty for version negotiation)
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
    ) -> None:
        """Handle new connection with proper connection ID handling."""
        try:
            print(f"🔧 NEW_CONN: Starting handshake for {addr}")

            # Find appropriate QUIC configuration
            quic_config = None
            config_key = None

            for protocol, config in self._quic_configs.items():
                wire_versions = custom_quic_version_to_wire_format(protocol)
                if wire_versions == packet_info.version:
                    quic_config = config
                    config_key = protocol
                    break

            if not quic_config:
                print(
                    f"❌ NEW_CONN: No configuration found for version 0x{packet_info.version:08x}"
                )
                print(
                    f"🔧 NEW_CONN: Available configs: {list(self._quic_configs.keys())}"
                )
                await self._send_version_negotiation(addr, packet_info.source_cid)
                return

            print(
                f"✅ NEW_CONN: Using config {config_key} for version 0x{packet_info.version:08x}"
            )

            # Create server-side QUIC configuration
            server_config = create_server_config_from_base(
                base_config=quic_config,
                security_manager=self._security_manager,
                transport_config=self._config,
            )

            # Debug the server configuration
            print(f"🔧 NEW_CONN: Server config - is_client: {server_config.is_client}")
            print(
                f"🔧 NEW_CONN: Server config - has_certificate: {server_config.certificate is not None}"
            )
            print(
                f"🔧 NEW_CONN: Server config - has_private_key: {server_config.private_key is not None}"
            )
            print(f"🔧 NEW_CONN: Server config - ALPN: {server_config.alpn_protocols}")
            print(
                f"🔧 NEW_CONN: Server config - verify_mode: {server_config.verify_mode}"
            )

            # Validate certificate has libp2p extension
            if server_config.certificate:
                cert = server_config.certificate
                has_libp2p_ext = False
                for ext in cert.extensions:
                    if ext.oid == LIBP2P_TLS_EXTENSION_OID:
                        has_libp2p_ext = True
                        break
                print(
                    f"🔧 NEW_CONN: Certificate has libp2p extension: {has_libp2p_ext}"
                )

                if not has_libp2p_ext:
                    print("❌ NEW_CONN: Certificate missing libp2p extension!")

            # Generate a new destination connection ID for this connection
            import secrets

            destination_cid = secrets.token_bytes(8)

            print(f"🔧 NEW_CONN: Generated new CID: {destination_cid.hex()}")
            print(
                f"🔧 NEW_CONN: Original destination CID: {packet_info.destination_cid.hex()}"
            )

            # Create QUIC connection with proper parameters for server
            quic_conn = QuicConnection(
                configuration=server_config,
                original_destination_connection_id=packet_info.destination_cid,
            )

            quic_conn._replenish_connection_ids()
            # Use the first host CID as our routing CID
            if quic_conn._host_cids:
                destination_cid = quic_conn._host_cids[0].cid
                print(
                    f"🔧 NEW_CONN: Using host CID as routing CID: {destination_cid.hex()}"
                )
            else:
                # Fallback to random if no host CIDs generated
                destination_cid = secrets.token_bytes(8)
                print(f"🔧 NEW_CONN: Fallback to random CID: {destination_cid.hex()}")

            print(
                f"🔧 NEW_CONN: Original destination CID: {packet_info.destination_cid.hex()}"
            )

            print(f"🔧 Generated {len(quic_conn._host_cids)} host CIDs for client")

            print("✅ NEW_CONN: QUIC connection created successfully")

            # Store connection mapping using our generated CID
            self._pending_connections[destination_cid] = quic_conn
            self._addr_to_cid[addr] = destination_cid
            self._cid_to_addr[destination_cid] = addr

            print(
                f"🔧 NEW_CONN: Stored mappings for {addr} <-> {destination_cid.hex()}"
            )
            print("Receiving Datagram")

            # Process initial packet
            quic_conn.receive_datagram(data, addr, now=time.time())

            # Debug connection state after receiving packet
            await self._debug_quic_connection_state_detailed(quic_conn, destination_cid)

            # Process events and send response
            await self._process_quic_events(quic_conn, addr, destination_cid)
            await self._transmit_for_connection(quic_conn, addr)

            logger.debug(
                f"Started handshake for new connection from {addr} "
                f"(version: 0x{packet_info.version:08x}, cid: {destination_cid.hex()})"
            )

        except Exception as e:
            logger.error(f"Error handling new connection from {addr}: {e}")
            import traceback

            traceback.print_exc()
            self._stats["connections_rejected"] += 1

    async def _debug_quic_connection_state_detailed(
        self, quic_conn: QuicConnection, connection_id: bytes
    ):
        """Enhanced connection state debugging."""
        try:
            print(f"🔧 QUIC_STATE: Debugging connection {connection_id.hex()}")

            if not quic_conn:
                print("❌ QUIC_STATE: QUIC CONNECTION NOT FOUND")
                return

            # Check TLS state
            if hasattr(quic_conn, "tls") and quic_conn.tls:
                print("✅ QUIC_STATE: TLS context exists")
                if hasattr(quic_conn.tls, "state"):
                    print(f"🔧 QUIC_STATE: TLS state: {quic_conn.tls.state}")

                # Check if we have peer certificate
                if (
                    hasattr(quic_conn.tls, "_peer_certificate")
                    and quic_conn.tls._peer_certificate
                ):
                    print("✅ QUIC_STATE: Peer certificate available")
                else:
                    print("🔧 QUIC_STATE: No peer certificate yet")

                # Check TLS handshake completion
                if hasattr(quic_conn.tls, "handshake_complete"):
                    handshake_status = quic_conn._handshake_complete
                    print(f"🔧 QUIC_STATE: TLS handshake complete: {handshake_status}")
            else:
                print("❌ QUIC_STATE: No TLS context!")

            # Check connection state
            if hasattr(quic_conn, "_state"):
                print(f"🔧 QUIC_STATE: Connection state: {quic_conn._state}")

            # Check if handshake is complete
            if hasattr(quic_conn, "_handshake_complete"):
                print(
                    f"🔧 QUIC_STATE: Handshake complete: {quic_conn._handshake_complete}"
                )

            # Check configuration
            if hasattr(quic_conn, "configuration"):
                config = quic_conn.configuration
                print(
                    f"🔧 QUIC_STATE: Config certificate: {config.certificate is not None}"
                )
                print(
                    f"🔧 QUIC_STATE: Config private_key: {config.private_key is not None}"
                )
                print(f"🔧 QUIC_STATE: Config is_client: {config.is_client}")
                print(f"🔧 QUIC_STATE: Config verify_mode: {config.verify_mode}")
                print(f"🔧 QUIC_STATE: Config ALPN: {config.alpn_protocols}")

                if config.certificate:
                    cert = config.certificate
                    print(f"🔧 QUIC_STATE: Certificate subject: {cert.subject}")
                    print(
                        f"🔧 QUIC_STATE: Certificate valid from: {cert.not_valid_before_utc}"
                    )
                    print(
                        f"🔧 QUIC_STATE: Certificate valid until: {cert.not_valid_after_utc}"
                    )

            # Check for connection errors
            if hasattr(quic_conn, "_close_event") and quic_conn._close_event:
                print(
                    f"❌ QUIC_STATE: Connection has close event: {quic_conn._close_event}"
                )

            # Check for TLS errors
            if (
                hasattr(quic_conn, "_handshake_complete")
                and not quic_conn._handshake_complete
            ):
                print("⚠️  QUIC_STATE: Handshake not yet complete")

        except Exception as e:
            print(f"❌ QUIC_STATE: Error checking state: {e}")
            import traceback

            traceback.print_exc()

    async def _handle_short_header_packet(
        self, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Handle short header packets using address-based fallback routing."""
        try:
            # Check if we have a connection for this address
            dest_cid = self._addr_to_cid.get(addr)
            if dest_cid:
                if dest_cid in self._connections:
                    connection = self._connections[dest_cid]
                    await self._route_to_connection(connection, data, addr)
                elif dest_cid in self._pending_connections:
                    quic_conn = self._pending_connections[dest_cid]
                    await self._handle_pending_connection(
                        quic_conn, data, addr, dest_cid
                    )
            else:
                logger.debug(
                    f"Received short header packet from unknown address {addr}"
                )

        except Exception as e:
            logger.error(f"Error handling short header packet from {addr}: {e}")

    async def _route_to_connection(
        self, connection: QUICConnection, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Route packet to existing connection."""
        try:
            # Feed data to the connection's QUIC instance
            connection._quic.receive_datagram(data, addr, now=time.time())

            # Process events and handle responses
            await connection._process_quic_events()
            await connection._transmit()

        except Exception as e:
            logger.error(f"Error routing packet to connection {addr}: {e}")
            # Remove problematic connection
            await self._remove_connection_by_addr(addr)

    async def _handle_pending_connection(
        self,
        quic_conn: QuicConnection,
        data: bytes,
        addr: tuple[str, int],
        dest_cid: bytes,
    ) -> None:
        """Handle packet for a pending (handshaking) connection with enhanced debugging."""
        try:
            print(
                f"🔧 PENDING: Handling packet for pending connection {dest_cid.hex()}"
            )
            print(f"🔧 PENDING: Packet size: {len(data)} bytes from {addr}")

            # Check connection state before processing
            if hasattr(quic_conn, "_state"):
                print(f"🔧 PENDING: Connection state before: {quic_conn._state}")

            if (
                hasattr(quic_conn, "tls")
                and quic_conn.tls
                and hasattr(quic_conn.tls, "state")
            ):
                print(f"🔧 PENDING: TLS state before: {quic_conn.tls.state}")

            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())
            print("✅ PENDING: Datagram received by QUIC connection")

            # Check state after receiving packet
            if hasattr(quic_conn, "_state"):
                print(f"🔧 PENDING: Connection state after: {quic_conn._state}")

            if (
                hasattr(quic_conn, "tls")
                and quic_conn.tls
                and hasattr(quic_conn.tls, "state")
            ):
                print(f"🔧 PENDING: TLS state after: {quic_conn.tls.state}")

            # Process events - this is crucial for handshake progression
            print("🔧 PENDING: Processing QUIC events...")
            await self._process_quic_events(quic_conn, addr, dest_cid)

            # Send any outgoing packets - this is where the response should be sent
            print("🔧 PENDING: Transmitting response...")
            await self._transmit_for_connection(quic_conn, addr)

            # Check if handshake completed
            if (
                hasattr(quic_conn, "_handshake_complete")
                and quic_conn._handshake_complete
            ):
                print("✅ PENDING: Handshake completed, promoting connection")
                await self._promote_pending_connection(quic_conn, addr, dest_cid)
            else:
                print("🔧 PENDING: Handshake still in progress")

                # Debug why handshake might be stuck
                await self._debug_handshake_state(quic_conn, dest_cid)

        except Exception as e:
            logger.error(f"Error handling pending connection {dest_cid.hex()}: {e}")
            import traceback

            traceback.print_exc()

            # Remove problematic pending connection
            print(f"❌ PENDING: Removing problematic connection {dest_cid.hex()}")
            await self._remove_pending_connection(dest_cid)

    async def _process_quic_events(
        self, quic_conn: QuicConnection, addr: tuple[str, int], dest_cid: bytes
    ) -> None:
        """Process QUIC events with enhanced debugging."""
        try:
            events_processed = 0
            while True:
                event = quic_conn.next_event()
                if event is None:
                    break

                events_processed += 1
                print(
                    f"🔧 EVENT: Processing event {events_processed}: {type(event).__name__}"
                )

                if isinstance(event, events.ConnectionTerminated):
                    print(
                        f"❌ EVENT: Connection terminated - code: {event.error_code}, reason: {event.reason_phrase}"
                    )
                    logger.debug(
                        f"Connection {dest_cid.hex()} from {addr} "
                        f"terminated: {event.reason_phrase}"
                    )
                    await self._remove_connection(dest_cid)
                    break

                elif isinstance(event, events.HandshakeCompleted):
                    print(
                        f"✅ EVENT: Handshake completed for connection {dest_cid.hex()}"
                    )
                    logger.debug(f"Handshake completed for connection {dest_cid.hex()}")
                    await self._promote_pending_connection(quic_conn, addr, dest_cid)

                elif isinstance(event, events.StreamDataReceived):
                    print(f"🔧 EVENT: Stream data received on stream {event.stream_id}")
                    # Forward to established connection if available
                    if dest_cid in self._connections:
                        connection = self._connections[dest_cid]
                        await connection._handle_stream_data(event)

                elif isinstance(event, events.StreamReset):
                    print(f"🔧 EVENT: Stream reset on stream {event.stream_id}")
                    # Forward to established connection if available
                    if dest_cid in self._connections:
                        connection = self._connections[dest_cid]
                        await connection._handle_stream_reset(event)

                elif isinstance(event, events.ConnectionIdIssued):
                    print(
                        f"🔧 EVENT: Connection ID issued: {event.connection_id.hex()}"
                    )
                    # ADD: Update mappings using existing data structures
                    # Add new CID to the same address mapping
                    taddr = self._cid_to_addr.get(dest_cid)
                    if taddr:
                        # Don't overwrite, but note that this CID is also valid for this address
                        print(
                            f"🔧 EVENT: New CID {event.connection_id.hex()} available for {taddr}"
                        )

                elif isinstance(event, events.ConnectionIdRetired):
                    print(
                        f"🔧 EVENT: Connection ID retired: {event.connection_id.hex()}"
                    )
                    # ADD: Clean up using existing patterns
                    retired_cid = event.connection_id
                    if retired_cid in self._cid_to_addr:
                        addr = self._cid_to_addr[retired_cid]
                        del self._cid_to_addr[retired_cid]
                        # Only remove addr mapping if this was the active CID
                        if self._addr_to_cid.get(addr) == retired_cid:
                            del self._addr_to_cid[addr]
                        print(
                            f"🔧 EVENT: Cleaned up mapping for retired CID {retired_cid.hex()}"
                        )
                else:
                    print(f"🔧 EVENT: Unhandled event type: {type(event).__name__}")

            if events_processed == 0:
                print("🔧 EVENT: No events to process")
            else:
                print(f"🔧 EVENT: Processed {events_processed} events total")

        except Exception as e:
            print(f"❌ EVENT: Error processing events: {e}")
            import traceback

            traceback.print_exc()

    async def _debug_quic_connection_state(
        self, quic_conn: QuicConnection, connection_id: bytes
    ):
        """Debug the internal state of the QUIC connection."""
        try:
            print(f"🔧 QUIC_STATE: Debugging connection {connection_id}")

            if not quic_conn:
                print("🔧 QUIC_STATE: QUIC CONNECTION NOT FOUND")
                return

            # Check TLS state
            if hasattr(quic_conn, "tls") and quic_conn.tls:
                print("🔧 QUIC_STATE: TLS context exists")
                if hasattr(quic_conn.tls, "state"):
                    print(f"🔧 QUIC_STATE: TLS state: {quic_conn.tls.state}")
            else:
                print("❌ QUIC_STATE: No TLS context!")

            # Check connection state
            if hasattr(quic_conn, "_state"):
                print(f"🔧 QUIC_STATE: Connection state: {quic_conn._state}")

            # Check if handshake is complete
            if hasattr(quic_conn, "_handshake_complete"):
                print(
                    f"🔧 QUIC_STATE: Handshake complete: {quic_conn._handshake_complete}"
                )

            # Check configuration
            if hasattr(quic_conn, "configuration"):
                config = quic_conn.configuration
                print(
                    f"🔧 QUIC_STATE: Config certificate: {config.certificate is not None}"
                )
                print(
                    f"🔧 QUIC_STATE: Config private_key: {config.private_key is not None}"
                )
                print(f"🔧 QUIC_STATE: Config is_client: {config.is_client}")

        except Exception as e:
            print(f"❌ QUIC_STATE: Error checking state: {e}")

    async def _promote_pending_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int], dest_cid: bytes
    ) -> None:
        """Promote a pending connection to an established connection."""
        try:
            # Remove from pending connections
            self._pending_connections.pop(dest_cid, None)

            # Create multiaddr for this connection
            host, port = addr
            quic_version = next(iter(self._quic_configs.keys()))
            remote_maddr = create_quic_multiaddr(host, port, f"/{quic_version}")

            from .connection import QUICConnection

            connection = QUICConnection(
                quic_connection=quic_conn,
                remote_addr=addr,
                peer_id=None,
                local_peer_id=self._transport._peer_id,
                is_initiator=False,
                maddr=remote_maddr,
                transport=self._transport,
                security_manager=self._security_manager,
            )

            self._connections[dest_cid] = connection

            if self._nursery:
                await connection.connect(self._nursery)

            if self._security_manager:
                try:
                    await connection._verify_peer_identity_with_security()
                    logger.info(
                        f"Security verification successful for {dest_cid.hex()}"
                    )
                except Exception as e:
                    logger.error(
                        f"Security verification failed for {dest_cid.hex()}: {e}"
                    )
                    await connection.close()
                    return

            # Call the connection handler
            if self._nursery:
                self._nursery.start_soon(
                    self._handle_new_established_connection, connection
                )

            self._stats["connections_accepted"] += 1
            logger.info(
                f"✅ Enhanced connection {dest_cid.hex()} established from {addr}"
            )

        except Exception as e:
            logger.error(f"❌ Error promoting connection {dest_cid.hex()}: {e}")
            await self._remove_connection(dest_cid)
            self._stats["connections_rejected"] += 1

    async def _remove_connection(self, dest_cid: bytes) -> None:
        """Remove connection by connection ID."""
        try:
            # Remove connection
            connection = self._connections.pop(dest_cid, None)
            if connection:
                await connection.close()

            # Clean up mappings
            addr = self._cid_to_addr.pop(dest_cid, None)
            if addr:
                self._addr_to_cid.pop(addr, None)

            logger.debug(f"Removed connection {dest_cid.hex()}")

        except Exception as e:
            logger.error(f"Error removing connection {dest_cid.hex()}: {e}")

    async def _remove_pending_connection(self, dest_cid: bytes) -> None:
        """Remove pending connection by connection ID."""
        try:
            self._pending_connections.pop(dest_cid, None)
            addr = self._cid_to_addr.pop(dest_cid, None)
            if addr:
                self._addr_to_cid.pop(addr, None)
            logger.debug(f"Removed pending connection {dest_cid.hex()}")
        except Exception as e:
            logger.error(f"Error removing pending connection {dest_cid.hex()}: {e}")

    async def _remove_connection_by_addr(self, addr: tuple[str, int]) -> None:
        """Remove connection by address (fallback method)."""
        dest_cid = self._addr_to_cid.get(addr)
        if dest_cid:
            await self._remove_connection(dest_cid)

    async def _transmit_for_connection(self, quic_conn, addr):
        """Enhanced transmission diagnostics to analyze datagram content."""
        try:
            print(f"🔧 TRANSMIT: Starting transmission to {addr}")

            # Get current timestamp for timing
            import time

            now = time.time()

            datagrams = quic_conn.datagrams_to_send(now=now)
            print(f"🔧 TRANSMIT: Got {len(datagrams)} datagrams to send")

            if not datagrams:
                print("⚠️  TRANSMIT: No datagrams to send")
                return

            for i, (datagram, dest_addr) in enumerate(datagrams):
                print(f"🔧 TRANSMIT: Analyzing datagram {i}")
                print(f"🔧 TRANSMIT: Datagram size: {len(datagram)} bytes")
                print(f"🔧 TRANSMIT: Destination: {dest_addr}")
                print(f"🔧 TRANSMIT: Expected destination: {addr}")

                # Analyze datagram content
                if len(datagram) > 0:
                    # QUIC packet format analysis
                    first_byte = datagram[0]
                    header_form = (first_byte & 0x80) >> 7  # Bit 7
                    fixed_bit = (first_byte & 0x40) >> 6  # Bit 6
                    packet_type = (first_byte & 0x30) >> 4  # Bits 4-5
                    type_specific = first_byte & 0x0F  # Bits 0-3

                    print(f"🔧 TRANSMIT: First byte: 0x{first_byte:02x}")
                    print(
                        f"🔧 TRANSMIT: Header form: {header_form} ({'Long' if header_form else 'Short'})"
                    )
                    print(
                        f"🔧 TRANSMIT: Fixed bit: {fixed_bit} ({'Valid' if fixed_bit else 'INVALID!'})"
                    )
                    print(f"🔧 TRANSMIT: Packet type: {packet_type}")

                    # For long header packets (handshake), analyze further
                    if header_form == 1:  # Long header
                        packet_types = {
                            0: "Initial",
                            1: "0-RTT",
                            2: "Handshake",
                            3: "Retry",
                        }
                        type_name = packet_types.get(packet_type, "Unknown")
                        print(f"🔧 TRANSMIT: Long header packet type: {type_name}")

                        # Look for CRYPTO frame indicators
                        # CRYPTO frame type is 0x06
                        crypto_frame_found = False
                        for offset in range(len(datagram)):
                            if datagram[offset] == 0x06:  # CRYPTO frame type
                                crypto_frame_found = True
                                print(
                                    f"✅ TRANSMIT: Found CRYPTO frame at offset {offset}"
                                )
                                break

                        if not crypto_frame_found:
                            print("❌ TRANSMIT: NO CRYPTO frame found in datagram!")
                            # Look for other frame types
                            frame_types_found = set()
                            for offset in range(len(datagram)):
                                frame_type = datagram[offset]
                                if frame_type in [0x00, 0x01]:  # PADDING/PING
                                    frame_types_found.add("PADDING/PING")
                                elif frame_type == 0x02:  # ACK
                                    frame_types_found.add("ACK")
                                elif frame_type == 0x06:  # CRYPTO
                                    frame_types_found.add("CRYPTO")

                            print(
                                f"🔧 TRANSMIT: Frame types detected: {frame_types_found}"
                            )

                    # Show first few bytes for debugging
                    preview_bytes = min(32, len(datagram))
                    hex_preview = " ".join(f"{b:02x}" for b in datagram[:preview_bytes])
                    print(f"🔧 TRANSMIT: First {preview_bytes} bytes: {hex_preview}")

                # Actually send the datagram
                if self._socket:
                    try:
                        print(f"🔧 TRANSMIT: Sending datagram {i} via socket...")
                        await self._socket.sendto(datagram, addr)
                        print(f"✅ TRANSMIT: Successfully sent datagram {i}")
                    except Exception as send_error:
                        print(f"❌ TRANSMIT: Socket send failed: {send_error}")
                else:
                    print("❌ TRANSMIT: No socket available!")

            # Check if there are more datagrams after sending
            remaining_datagrams = quic_conn.datagrams_to_send(now=time.time())
            print(
                f"🔧 TRANSMIT: After sending, {len(remaining_datagrams)} datagrams remain"
            )
            print("------END OF THIS DATAGRAM LOG-----")

        except Exception as e:
            print(f"❌ TRANSMIT: Transmission error: {e}")
            import traceback

            traceback.print_exc()

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """Start listening on the given multiaddr with enhanced connection handling."""
        if self._listening:
            raise QUICListenError("Already listening")

        if not is_quic_multiaddr(maddr):
            raise QUICListenError(f"Invalid QUIC multiaddr: {maddr}")

        try:
            host, port = quic_multiaddr_to_endpoint(maddr)

            # Create and configure socket
            self._socket = await self._create_socket(host, port)
            self._nursery = nursery

            # Get the actual bound address
            bound_host, bound_port = self._socket.getsockname()
            quic_version = multiaddr_to_quic_version(maddr)
            bound_maddr = create_quic_multiaddr(bound_host, bound_port, quic_version)
            self._bound_addresses = [bound_maddr]

            self._listening = True

            # Start packet handling loop
            nursery.start_soon(self._handle_incoming_packets)

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
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

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
            async with self._connection_lock:
                for dest_cid in list(self._connections.keys()):
                    await self._remove_connection(dest_cid)

                for dest_cid in list(self._pending_connections.keys()):
                    await self._remove_pending_connection(dest_cid)

            # Close socket
            if self._socket:
                self._socket.close()
                self._socket = None

            self._bound_addresses.clear()

            logger.info("QUIC listener closed")

        except Exception as e:
            logger.error(f"Error closing listener: {e}")

    def get_addresses(self) -> list[Multiaddr]:
        """Get the bound addresses."""
        return self._bound_addresses.copy()

    async def _handle_new_established_connection(
        self, connection: QUICConnection
    ) -> None:
        """Handle a newly established connection."""
        try:
            await self._handler(connection)
        except Exception as e:
            logger.error(f"Error in connection handler: {e}")
            await connection.close()

    def get_addrs(self) -> tuple[Multiaddr]:
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
        stats = self._stats.copy()
        stats["is_listening"] = self.is_listening()
        stats["active_connections"] = len(self._connections)
        stats["pending_connections"] = len(self._pending_connections)
        return stats

    async def _debug_handshake_state(self, quic_conn: QuicConnection, dest_cid: bytes):
        """Debug why handshake might be stuck."""
        try:
            print(f"🔧 HANDSHAKE_DEBUG: Analyzing stuck handshake for {dest_cid.hex()}")

            # Check TLS handshake state
            if hasattr(quic_conn, "tls") and quic_conn.tls:
                tls = quic_conn.tls
                print(
                    f"🔧 HANDSHAKE_DEBUG: TLS state: {getattr(tls, 'state', 'Unknown')}"
                )

                # Check for TLS errors
                if hasattr(tls, "_error") and tls._error:
                    print(f"❌ HANDSHAKE_DEBUG: TLS error: {tls._error}")

                # Check certificate validation
                if hasattr(tls, "_peer_certificate"):
                    if tls._peer_certificate:
                        print("✅ HANDSHAKE_DEBUG: Peer certificate received")
                    else:
                        print("❌ HANDSHAKE_DEBUG: No peer certificate")

                # Check ALPN negotiation
                if hasattr(tls, "_alpn_protocols"):
                    if tls._alpn_protocols:
                        print(
                            f"✅ HANDSHAKE_DEBUG: ALPN negotiated: {tls._alpn_protocols}"
                        )
                    else:
                        print("❌ HANDSHAKE_DEBUG: No ALPN protocol negotiated")

            # Check QUIC connection state
            if hasattr(quic_conn, "_state"):
                state = quic_conn._state
                print(f"🔧 HANDSHAKE_DEBUG: QUIC state: {state}")

                # Check specific states that might indicate problems
                if "FIRSTFLIGHT" in str(state):
                    print("⚠️  HANDSHAKE_DEBUG: Connection stuck in FIRSTFLIGHT state")
                elif "CONNECTED" in str(state):
                    print(
                        "⚠️  HANDSHAKE_DEBUG: Connection shows CONNECTED but handshake not complete"
                    )

            # Check for pending crypto data
            if hasattr(quic_conn, "_cryptos") and quic_conn._cryptos:
                print(
                    f"🔧 HANDSHAKE_DEBUG: Crypto data present {len(quic_conn._cryptos.keys())}"
                )

            # Check loss detection state
            if hasattr(quic_conn, "_loss") and quic_conn._loss:
                loss_detection = quic_conn._loss
                if hasattr(loss_detection, "_pto_count"):
                    print(f"🔧 HANDSHAKE_DEBUG: PTO count: {loss_detection._pto_count}")

        except Exception as e:
            print(f"❌ HANDSHAKE_DEBUG: Error during debug: {e}")
