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
from libp2p.transport.quic.security import QUICTLSConfigManager

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
        packet_type: int,
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
        handler_function: THandler,
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
            packet_type = (first_byte & 0x30) >> 4

            # For Initial packets, extract token
            token = b""
            if packet_type == 0:  # Initial packet
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
                packet_type=packet_type,
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
        Enhanced packet processing with connection ID routing and version negotiation.
        """
        try:
            self._stats["packets_processed"] += 1
            self._stats["bytes_received"] += len(data)

            # Parse packet to extract connection information
            packet_info = self.parse_quic_packet(data)

            async with self._connection_lock:
                if packet_info:
                    # Check for version negotiation
                    if packet_info.version == 0:
                        # Version negotiation packet - this shouldn't happen on server
                        logger.warning(
                            f"Received version negotiation packet from {addr}"
                        )
                        return

                    # Check if version is supported
                    if packet_info.version not in self._supported_versions:
                        await self._send_version_negotiation(
                            addr, packet_info.source_cid
                        )
                        return

                    # Route based on destination connection ID
                    dest_cid = packet_info.destination_cid

                    if dest_cid in self._connections:
                        # Existing connection
                        connection = self._connections[dest_cid]
                        await self._route_to_connection(connection, data, addr)
                    elif dest_cid in self._pending_connections:
                        # Pending connection
                        quic_conn = self._pending_connections[dest_cid]
                        await self._handle_pending_connection(
                            quic_conn, data, addr, dest_cid
                        )
                    else:
                        # New connection - only handle Initial packets for new conn
                        if packet_info.packet_type == 0:  # Initial packet
                            await self._handle_new_connection(data, addr, packet_info)
                        else:
                            logger.debug(
                                "Ignoring non-Initial packet for unknown "
                                f"connection ID from {addr}"
                            )
                else:
                    # Fallback to address-based routing for short header packets
                    await self._handle_short_header_packet(data, addr)

        except Exception as e:
            logger.error(f"Error processing packet from {addr}: {e}")
            self._stats["invalid_packets"] += 1

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
        self,
        data: bytes,
        addr: tuple[str, int],
        packet_info: QUICPacketInfo,
    ) -> None:
        """
        Handle new connection with proper version negotiation.
        """
        try:
            quic_config = None
            for protocol, config in self._quic_configs.items():
                wire_versions = custom_quic_version_to_wire_format(protocol)
                if wire_versions == packet_info.version:
                    quic_config = config
                    break

            if not quic_config:
                logger.warning(
                    f"No configuration found for version {packet_info.version:08x}"
                )
                await self._send_version_negotiation(addr, packet_info.source_cid)
                return

            # Create server-side QUIC configuration
            server_config = create_server_config_from_base(
                base_config=quic_config,
                security_manager=self._security_manager,
                transport_config=self._config,
            )

            # Generate a new destination connection ID for this connection
            # In a real implementation, this should be cryptographically secure
            import secrets

            destination_cid = secrets.token_bytes(8)

            # Create QUIC connection with specific version
            quic_conn = QuicConnection(
                configuration=server_config,
                original_destination_connection_id=packet_info.destination_cid,
            )

            # Store connection mapping
            self._pending_connections[destination_cid] = quic_conn
            self._addr_to_cid[addr] = destination_cid
            self._cid_to_addr[destination_cid] = addr

            print("Receiving Datagram")

            # Process initial packet
            quic_conn.receive_datagram(data, addr, now=time.time())
            await self._process_quic_events(quic_conn, addr, destination_cid)
            await self._transmit_for_connection(quic_conn, addr)

            logger.debug(
                f"Started handshake for new connection from {addr} "
                f"(version: {packet_info.version:08x}, cid: {destination_cid.hex()})"
            )

        except Exception as e:
            logger.error(f"Error handling new connection from {addr}: {e}")
            self._stats["connections_rejected"] += 1

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
        """Handle packet for a pending (handshaking) connection."""
        try:
            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())

            # Process events
            await self._process_quic_events(quic_conn, addr, dest_cid)

            # Send any outgoing packets
            await self._transmit_for_connection(quic_conn, addr)

        except Exception as e:
            logger.error(f"Error handling pending connection {dest_cid.hex()}: {e}")
            # Remove from pending connections
            await self._remove_pending_connection(dest_cid)

    async def _process_quic_events(
        self, quic_conn: QuicConnection, addr: tuple[str, int], dest_cid: bytes
    ) -> None:
        """Process QUIC events for a connection with connection ID context."""
        while True:
            event = quic_conn.next_event()
            if event is None:
                break

            if isinstance(event, events.ConnectionTerminated):
                logger.debug(
                    f"Connection {dest_cid.hex()} from {addr} "
                    f"terminated: {event.reason_phrase}"
                )
                await self._remove_connection(dest_cid)
                break

            elif isinstance(event, events.HandshakeCompleted):
                logger.debug(f"Handshake completed for connection {dest_cid.hex()}")
                await self._promote_pending_connection(quic_conn, addr, dest_cid)

            elif isinstance(event, events.StreamDataReceived):
                # Forward to established connection if available
                if dest_cid in self._connections:
                    connection = self._connections[dest_cid]
                    await connection._handle_stream_data(event)

            elif isinstance(event, events.StreamReset):
                # Forward to established connection if available
                if dest_cid in self._connections:
                    connection = self._connections[dest_cid]
                    await connection._handle_stream_reset(event)

    async def _promote_pending_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int], dest_cid: bytes
    ) -> None:
        """Promote a pending connection to an established connection."""
        try:
            # Remove from pending connections
            self._pending_connections.pop(dest_cid, None)

            # Create multiaddr for this connection
            host, port = addr
            # Use the appropriate QUIC version
            quic_version = next(iter(self._quic_configs.keys()))
            remote_maddr = create_quic_multiaddr(host, port, f"/{quic_version}")

            # Create libp2p connection wrapper
            connection = QUICConnection(
                quic_connection=quic_conn,
                remote_addr=addr,
                peer_id=None,  # Will be determined during identity verification
                local_peer_id=self._transport._peer_id,
                is_initiator=False,  # We're the server
                maddr=remote_maddr,
                transport=self._transport,
                security_manager=self._security_manager,
            )

            # Store the connection with connection ID
            self._connections[dest_cid] = connection

            # Start connection management tasks
            if self._nursery:
                self._nursery.start_soon(connection._handle_datagram_received)
                self._nursery.start_soon(connection._handle_timer_events)

            # Handle security verification
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
            logger.info(f"Accepted new QUIC connection {dest_cid.hex()} from {addr}")

        except Exception as e:
            logger.error(f"Error promoting connection {dest_cid.hex()}: {e}")
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

    async def _transmit_for_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int]
    ) -> None:
        """Send outgoing packets for a QUIC connection."""
        try:
            while True:
                datagrams = quic_conn.datagrams_to_send(now=time.time())
                if not datagrams:
                    break

                for datagram, _ in datagrams:
                    if self._socket:
                        await self._socket.sendto(datagram, addr)

        except Exception as e:
            logger.error(f"Error transmitting packets to {addr}: {e}")

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
