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
                cid_length = 8  # We are using standard CID length everywhere

                if len(data) < 1 + cid_length:
                    return None

                dest_cid = data[1 : 1 + cid_length]

                return QUICPacketInfo(
                    version=1,  # Assume QUIC v1 for established connections
                    destination_cid=dest_cid,
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
        """Process incoming QUIC packet with optimized routing."""
        try:
            self._stats["packets_processed"] += 1
            self._stats["bytes_received"] += len(data)

            packet_info = self.parse_quic_packet(data)
            if packet_info is None:
                self._stats["invalid_packets"] += 1
                return

            dest_cid = packet_info.destination_cid

            # Single lock acquisition with all lookups
            async with self._connection_lock:
                connection_obj = self._connections.get(dest_cid)
                pending_quic_conn = self._pending_connections.get(dest_cid)

                if not connection_obj and not pending_quic_conn:
                    if packet_info.packet_type == QuicPacketType.INITIAL:
                        pending_quic_conn = await self._handle_new_connection(
                            data, addr, packet_info
                        )
                    else:
                        return

            # Process outside the lock
            if connection_obj:
                await self._handle_established_connection_packet(
                    connection_obj, data, addr, dest_cid
                )
            elif pending_quic_conn:
                await self._handle_pending_connection_packet(
                    pending_quic_conn, data, addr, dest_cid
                )

        except Exception as e:
            logger.error(f"Error processing packet from {addr}: {e}")

    async def _handle_established_connection_packet(
        self,
        connection_obj: QUICConnection,
        data: bytes,
        addr: tuple[str, int],
        dest_cid: bytes,
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
        dest_cid: bytes,
    ) -> None:
        """Handle packet for pending connection WITHOUT holding connection lock."""
        try:
            logger.debug(f"Handling packet for pending connection {dest_cid.hex()}")
            logger.debug(f"Packet size: {len(data)} bytes from {addr}")

            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())
            logger.debug("PENDING: Datagram received by QUIC connection")

            # Process events - this is crucial for handshake progression
            logger.debug("Processing QUIC events...")
            await self._process_quic_events(quic_conn, addr, dest_cid)

            # Send any outgoing packets
            logger.debug("Transmitting response...")
            await self._transmit_for_connection(quic_conn, addr)

            # Check if handshake completed (with minimal locking)
            if quic_conn._handshake_complete:
                logger.debug("PENDING: Handshake completed, promoting connection")
                await self._promote_pending_connection(quic_conn, addr, dest_cid)
            else:
                logger.debug("Handshake still in progress")

        except Exception as e:
            logger.error(f"Error handling pending connection {dest_cid.hex()}: {e}")

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
                await self._send_version_negotiation(addr, packet_info.source_cid)
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
                f"Original destination CID: {packet_info.destination_cid.hex()}"
            )

            quic_conn = QuicConnection(
                configuration=server_config,
                original_destination_connection_id=packet_info.destination_cid,
            )

            quic_conn._replenish_connection_ids()
            # Use the first host CID as our routing CID
            if quic_conn._host_cids:
                destination_cid = quic_conn._host_cids[0].cid
                logger.debug(f"Using host CID as routing CID: {destination_cid.hex()}")
            else:
                # Fallback to random if no host CIDs generated
                import secrets

                destination_cid = secrets.token_bytes(8)
                logger.debug(f"Fallback to random CID: {destination_cid.hex()}")

            logger.debug(f"Generated {len(quic_conn._host_cids)} host CIDs for client")

            logger.debug(
                f"QUIC connection created for destination CID {destination_cid.hex()}"
            )

            # Store connection mapping using our generated CID
            self._pending_connections[destination_cid] = quic_conn
            self._addr_to_cid[addr] = destination_cid
            self._cid_to_addr[destination_cid] = addr

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
            await self._process_quic_events(quic_conn, addr, destination_cid)
            await self._transmit_for_connection(quic_conn, addr)

            logger.debug(
                f"Started handshake for new connection from {addr} "
                f"(version: 0x{packet_info.version:08x}, cid: {destination_cid.hex()})"
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

            # First, try address-based lookup
            dest_cid = self._addr_to_cid.get(addr)
            if dest_cid and dest_cid in self._connections:
                connection = self._connections[dest_cid]
                await self._route_to_connection(connection, data, addr)
                return

            # Fallback: try to extract CID from packet
            if len(data) >= 9:  # 1 byte header + 8 byte CID
                potential_cid = data[1:9]

                if potential_cid in self._connections:
                    connection = self._connections[potential_cid]

                    # Update mappings for future packets
                    self._addr_to_cid[addr] = potential_cid
                    self._cid_to_addr[potential_cid] = addr

                    await self._route_to_connection(connection, data, addr)
                    return

            logger.debug(f"❌ SHORT_HDR: No matching connection found for {addr}")

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
        """Handle packet for a pending (handshaking) connection."""
        try:
            logger.debug(f"Handling packet for pending connection {dest_cid.hex()}")

            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())

            if quic_conn.tls:
                logger.debug(f"TLS state after: {quic_conn.tls.state}")

            # Process events - this is crucial for handshake progression
            await self._process_quic_events(quic_conn, addr, dest_cid)

            # Send any outgoing packets - this is where the response should be sent
            await self._transmit_for_connection(quic_conn, addr)

            # Check if handshake completed
            if quic_conn._handshake_complete:
                logger.debug("PENDING: Handshake completed, promoting connection")
                await self._promote_pending_connection(quic_conn, addr, dest_cid)

        except Exception as e:
            logger.error(f"Error handling pending connection {dest_cid.hex()}: {e}")

            # Remove problematic pending connection
            logger.error(f"Removing problematic connection {dest_cid.hex()}")
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
                logger.debug(
                    "QUIC EVENT: Processing event "
                    f"{events_processed}: {type(event).__name__}"
                )

                if isinstance(event, events.ConnectionTerminated):
                    logger.debug(
                        "QUIC EVENT: Connection terminated "
                        f"- code: {event.error_code}, reason: {event.reason_phrase}"
                        f"Connection {dest_cid.hex()} from {addr} "
                        f"terminated: {event.reason_phrase}"
                    )
                    await self._remove_connection(dest_cid)
                    break

                elif isinstance(event, events.HandshakeCompleted):
                    logger.debug(
                        "QUIC EVENT: Handshake completed for connection "
                        f"{dest_cid.hex()}"
                    )
                    logger.debug(f"Handshake completed for connection {dest_cid.hex()}")
                    await self._promote_pending_connection(quic_conn, addr, dest_cid)

                elif isinstance(event, events.StreamDataReceived):
                    logger.debug(
                        f"QUIC EVENT: Stream data received on stream {event.stream_id}"
                    )
                    if dest_cid in self._connections:
                        connection = self._connections[dest_cid]
                        await connection._handle_stream_data(event)

                elif isinstance(event, events.StreamReset):
                    logger.debug(
                        f"QUIC EVENT: Stream reset on stream {event.stream_id}"
                    )
                    if dest_cid in self._connections:
                        connection = self._connections[dest_cid]
                        await connection._handle_stream_reset(event)

                elif isinstance(event, events.ConnectionIdIssued):
                    logger.debug(
                        f"QUIC EVENT: Connection ID issued: {event.connection_id.hex()}"
                    )
                    # Add new CID to the same address mapping
                    taddr = self._cid_to_addr.get(dest_cid)
                    if taddr:
                        # Don't overwrite, but this CID is also valid for this address
                        logger.debug(
                            f"QUIC EVENT: New CID {event.connection_id.hex()} "
                            f"available for {taddr}"
                        )

                elif isinstance(event, events.ConnectionIdRetired):
                    logger.info(f"Connection ID retired: {event.connection_id.hex()}")
                    retired_cid = event.connection_id
                    if retired_cid in self._cid_to_addr:
                        addr = self._cid_to_addr[retired_cid]
                        del self._cid_to_addr[retired_cid]
                        # Only remove addr mapping if this was the active CID
                        if self._addr_to_cid.get(addr) == retired_cid:
                            del self._addr_to_cid[addr]
                else:
                    logger.warning(f"Unhandled event type: {type(event).__name__}")

        except Exception as e:
            logger.debug(f"❌ EVENT: Error processing events: {e}")

    async def _promote_pending_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int], dest_cid: bytes
    ) -> None:
        """Promote pending connection - avoid duplicate creation."""
        try:
            self._pending_connections.pop(dest_cid, None)

            if dest_cid in self._connections:
                logger.debug(
                    f"⚠️ Connection {dest_cid.hex()} already exists in _connections!"
                )
                connection = self._connections[dest_cid]
            else:
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
                )

                logger.debug(f"🔄 Created NEW QUICConnection for {dest_cid.hex()}")

                self._connections[dest_cid] = connection

            self._addr_to_cid[addr] = dest_cid
            self._cid_to_addr[dest_cid] = addr

            if self._nursery:
                connection._nursery = self._nursery
                await connection.connect(self._nursery)
                logger.debug(f"Connection connected succesfully for {dest_cid.hex()}")

            if self._security_manager:
                try:
                    peer_id = await connection._verify_peer_identity_with_security()
                    if peer_id:
                        connection.peer_id = peer_id
                    logger.info(
                        f"Security verification successful for {dest_cid.hex()}"
                    )
                except Exception as e:
                    logger.error(
                        f"Security verification failed for {dest_cid.hex()}: {e}"
                    )
                    await connection.close()
                    return

            if self._nursery:
                connection._nursery = self._nursery
                await connection._start_background_tasks()
                logger.debug(
                    f"Started background tasks for connection {dest_cid.hex()}"
                )

            try:
                logger.debug(f"Invoking user callback {dest_cid.hex()}")
                await self._handler(connection)

            except Exception as e:
                logger.error(f"Error in user callback: {e}")

            self._stats["connections_accepted"] += 1
            logger.info(f"Enhanced connection {dest_cid.hex()} established from {addr}")

        except Exception as e:
            logger.error(f"❌ Error promoting connection {dest_cid.hex()}: {e}")
            await self._remove_connection(dest_cid)

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

    async def _transmit_for_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int]
    ) -> None:
        """Enhanced transmission diagnostics to analyze datagram content."""
        try:
            logger.debug(f" TRANSMIT: Starting transmission to {addr}")

            # Get current timestamp for timing
            import time

            now = time.time()

            datagrams = quic_conn.datagrams_to_send(now=now)
            logger.debug(f" TRANSMIT: Got {len(datagrams)} datagrams to send")

            if not datagrams:
                logger.debug("⚠️  TRANSMIT: No datagrams to send")
                return

            for i, (datagram, dest_addr) in enumerate(datagrams):
                logger.debug(f" TRANSMIT: Analyzing datagram {i}")
                logger.debug(f" TRANSMIT: Datagram size: {len(datagram)} bytes")
                logger.debug(f" TRANSMIT: Destination: {dest_addr}")
                logger.debug(f" TRANSMIT: Expected destination: {addr}")

                # Analyze datagram content
                if len(datagram) > 0:
                    # QUIC packet format analysis
                    first_byte = datagram[0]
                    header_form = (first_byte & 0x80) >> 7  # Bit 7

                    # For long header packets (handshake), analyze further
                    if header_form == 1:  # Long header
                        # CRYPTO frame type is 0x06
                        crypto_frame_found = False
                        for offset in range(len(datagram)):
                            if datagram[offset] == 0x06:
                                crypto_frame_found = True
                                break

                        if not crypto_frame_found:
                            logger.error("No CRYPTO frame found in datagram!")
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

                if self._socket:
                    try:
                        await self._socket.sendto(datagram, addr)
                    except Exception as send_error:
                        logger.error(f"Socket send failed: {send_error}")
                else:
                    logger.error("No socket available!")
        except Exception as e:
            logger.debug(f"Transmission error: {e}")

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

    async def _remove_connection_by_object(
        self, connection_obj: "QUICConnection"
    ) -> None:
        """Remove a connection by object reference."""
        try:
            # Find the connection ID for this object
            connection_cid = None
            for cid, tracked_connection in self._connections.items():
                if tracked_connection is connection_obj:
                    connection_cid = cid
                    break

            if connection_cid:
                await self._remove_connection(connection_cid)
                logger.debug(f"Removed connection {connection_cid.hex()}")
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
