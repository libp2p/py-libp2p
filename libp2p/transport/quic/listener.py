"""
QUIC Listener implementation for py-libp2p.
Based on go-libp2p and js-libp2p QUIC listener patterns.
Uses aioquic's server-side QUIC implementation with trio.
"""

import copy
import logging
import socket
import time
from typing import TYPE_CHECKING

from aioquic.quic import events
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.custom_types import THandler, TProtocol

from .config import QUICTransportConfig
from .connection import QUICConnection
from .exceptions import QUICListenError
from .utils import (
    create_quic_multiaddr,
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    quic_multiaddr_to_endpoint,
)

if TYPE_CHECKING:
    from .transport import QUICTransport

logger = logging.getLogger(__name__)
logger.setLevel("DEBUG")


class QUICListener(IListener):
    """
    QUIC Listener implementation following libp2p listener interface.

    Handles incoming QUIC connections, manages server-side handshakes,
    and integrates with the libp2p connection handler system.
    Based on go-libp2p and js-libp2p listener patterns.
    """

    def __init__(
        self,
        transport: "QUICTransport",
        handler_function: THandler,
        quic_configs: dict[TProtocol, QuicConfiguration],
        config: QUICTransportConfig,
    ):
        """
        Initialize QUIC listener.

        Args:
            transport: Parent QUIC transport
            handler_function: Function to handle new connections
            quic_configs: QUIC configurations for different versions
            config: QUIC transport configuration

        """
        self._transport = transport
        self._handler = handler_function
        self._quic_configs = quic_configs
        self._config = config

        # Network components
        self._socket: trio.socket.SocketType | None = None
        self._bound_addresses: list[Multiaddr] = []

        # Connection management
        self._connections: dict[tuple[str, int], QUICConnection] = {}
        self._pending_connections: dict[tuple[str, int], QuicConnection] = {}
        self._connection_lock = trio.Lock()

        # Listener state
        self._closed = False
        self._listening = False
        self._nursery: trio.Nursery | None = None

        # Performance tracking
        self._stats = {
            "connections_accepted": 0,
            "connections_rejected": 0,
            "bytes_received": 0,
            "packets_processed": 0,
        }

        logger.debug("Initialized QUIC listener")

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening on the given multiaddr.

        Args:
            maddr: Multiaddr to listen on
            nursery: Trio nursery for managing background tasks

        Returns:
            True if listening started successfully

        Raises:
            QUICListenError: If failed to start listening

        """
        if not is_quic_multiaddr(maddr):
            raise QUICListenError(f"Invalid QUIC multiaddr: {maddr}")

        if self._listening:
            raise QUICListenError("Already listening")

        try:
            # Extract host and port from multiaddr
            host, port = quic_multiaddr_to_endpoint(maddr)
            quic_version = multiaddr_to_quic_version(maddr)

            # Validate QUIC version support
            if quic_version not in self._quic_configs:
                raise QUICListenError(f"Unsupported QUIC version: {quic_version}")

            # Create and bind UDP socket
            self._socket = await self._create_and_bind_socket(host, port)
            actual_port = self._socket.getsockname()[1]

            # Update multiaddr with actual bound port
            actual_maddr = create_quic_multiaddr(host, actual_port, f"/{quic_version}")
            self._bound_addresses = [actual_maddr]

            # Store nursery reference and set listening state
            self._nursery = nursery
            self._listening = True

            # Start background tasks directly in the provided nursery
            # This e per cancellation when the nursery exits
            nursery.start_soon(self._handle_incoming_packets)
            nursery.start_soon(self._manage_connections)

            logger.info(f"QUIC listener started on {actual_maddr}")
            return True

        except trio.Cancelled:
            print("CLOSING LISTENER")
            raise
        except Exception as e:
            logger.error(f"Failed to start QUIC listener on {maddr}: {e}")
            await self._cleanup_socket()
            raise QUICListenError(f"Listen failed: {e}") from e

    async def _create_and_bind_socket(
        self, host: str, port: int
    ) -> trio.socket.SocketType:
        """Create and bind UDP socket for QUIC."""
        try:
            # Determine address family
            try:
                import ipaddress

                ip = ipaddress.ip_address(host)
                family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
            except ValueError:
                # Assume IPv4 for hostnames
                family = socket.AF_INET

            # Create UDP socket
            sock = trio.socket.socket(family=family, type=socket.SOCK_DGRAM)

            # Set socket options for better performance
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
        """
        Handle incoming UDP packets and route to appropriate connections.
        This is the main packet processing loop.
        """
        logger.debug("Started packet handling loop")

        try:
            while self._listening and self._socket:
                try:
                    # Receive UDP packet
                    # (this blocks until packet arrives or socket closes)
                    data, addr = await self._socket.recvfrom(65536)
                    self._stats["bytes_received"] += len(data)
                    self._stats["packets_processed"] += 1

                    # Process packet asynchronously to avoid blocking
                    if self._nursery:
                        self._nursery.start_soon(self._process_packet, data, addr)

                except trio.ClosedResourceError:
                    # Socket was closed, exit gracefully
                    logger.debug("Socket closed, exiting packet handler")
                    break
                except Exception as e:
                    logger.error(f"Error receiving packet: {e}")
                    # Continue processing other packets
                    await trio.sleep(0.01)
        except trio.Cancelled:
            logger.info("Received Cancel, stopping handling incoming packets")
            raise
        finally:
            logger.debug("Packet handling loop terminated")

    async def _process_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        """
        Process a single incoming packet.
        Routes to existing connection or creates new connection.

        Args:
            data: Raw UDP packet data
            addr: Source address (host, port)

        """
        try:
            async with self._connection_lock:
                # Check if we have an existing connection for this address
                if addr in self._connections:
                    connection = self._connections[addr]
                    await self._route_to_connection(connection, data, addr)
                elif addr in self._pending_connections:
                    # Handle packet for pending connection
                    quic_conn = self._pending_connections[addr]
                    await self._handle_pending_connection(quic_conn, data, addr)
                else:
                    # New connection
                    await self._handle_new_connection(data, addr)

        except Exception as e:
            logger.error(f"Error processing packet from {addr}: {e}")

    async def _route_to_connection(
        self, connection: QUICConnection, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Route packet to existing connection."""
        try:
            # Feed data to the connection's QUIC instance
            connection._quic.receive_datagram(data, addr, now=time.time())

            # Process events and handle responses
            await connection._process_events()
            await connection._transmit()

        except Exception as e:
            logger.error(f"Error routing packet to connection {addr}: {e}")
            # Remove problematic connection
            await self._remove_connection(addr)

    async def _handle_pending_connection(
        self, quic_conn: QuicConnection, data: bytes, addr: tuple[str, int]
    ) -> None:
        """Handle packet for a pending (handshaking) connection."""
        try:
            # Feed data to QUIC connection
            quic_conn.receive_datagram(data, addr, now=time.time())

            # Process events
            await self._process_quic_events(quic_conn, addr)

            # Send any outgoing packets
            await self._transmit_for_connection(quic_conn)

        except Exception as e:
            logger.error(f"Error handling pending connection {addr}: {e}")
            # Remove from pending connections
            self._pending_connections.pop(addr, None)

    async def _handle_new_connection(self, data: bytes, addr: tuple[str, int]) -> None:
        """
        Handle a new incoming connection.
        Creates a new QUIC connection and starts handshake.

        Args:
            data: Initial packet data
            addr: Source address

        """
        try:
            # Determine QUIC version from packet
            # For now, use the first available configuration
            # TODO: Implement proper version negotiation
            quic_version = next(iter(self._quic_configs.keys()))
            config = self._quic_configs[quic_version]

            # Create server-side QUIC configuration
            server_config = copy.deepcopy(config)
            server_config.is_client = False

            # Create QUIC connection
            quic_conn = QuicConnection(configuration=server_config)

            # Store as pending connection
            self._pending_connections[addr] = quic_conn

            # Process initial packet
            quic_conn.receive_datagram(data, addr, now=time.time())
            await self._process_quic_events(quic_conn, addr)
            await self._transmit_for_connection(quic_conn)

            logger.debug(f"Started handshake for new connection from {addr}")

        except Exception as e:
            logger.error(f"Error handling new connection from {addr}: {e}")
            self._stats["connections_rejected"] += 1

    async def _process_quic_events(
        self, quic_conn: QuicConnection, addr: tuple[str, int]
    ) -> None:
        """Process QUIC events for a connection."""
        while True:
            event = quic_conn.next_event()
            if event is None:
                break

            if isinstance(event, events.ConnectionTerminated):
                logger.debug(
                    f"Connection from {addr} terminated: {event.reason_phrase}"
                )
                await self._remove_connection(addr)
                break

            elif isinstance(event, events.HandshakeCompleted):
                logger.debug(f"Handshake completed for {addr}")
                await self._promote_pending_connection(quic_conn, addr)

            elif isinstance(event, events.StreamDataReceived):
                # Forward to established connection if available
                if addr in self._connections:
                    connection = self._connections[addr]
                    await connection._handle_stream_data(event)

            elif isinstance(event, events.StreamReset):
                # Forward to established connection if available
                if addr in self._connections:
                    connection = self._connections[addr]
                    await connection._handle_stream_reset(event)

    async def _promote_pending_connection(
        self, quic_conn: QuicConnection, addr: tuple[str, int]
    ) -> None:
        """
        Promote a pending connection to an established connection.
        Called after successful handshake completion.

        Args:
            quic_conn: Established QUIC connection
            addr: Remote address

        """
        try:
            # Remove from pending connections
            self._pending_connections.pop(addr, None)

            # Create multiaddr for this connection
            host, port = addr
            # Use the first supported QUIC version for now
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
            )

            # Store the connection
            self._connections[addr] = connection

            # Start connection management tasks
            if self._nursery:
                self._nursery.start_soon(connection._handle_incoming_data)
                self._nursery.start_soon(connection._handle_timer)

            # TODO: Verify peer identity
            # await connection.verify_peer_identity()

            # Call the connection handler
            if self._nursery:
                self._nursery.start_soon(
                    self._handle_new_established_connection, connection
                )

            self._stats["connections_accepted"] += 1
            logger.info(f"Accepted new QUIC connection from {addr}")

        except Exception as e:
            logger.error(f"Error promoting connection from {addr}: {e}")
            # Clean up
            await self._remove_connection(addr)
            self._stats["connections_rejected"] += 1

    async def _handle_new_established_connection(
        self, connection: QUICConnection
    ) -> None:
        """
        Handle a newly established connection by calling the user handler.

        Args:
            connection: Established QUIC connection

        """
        try:
            # Call the connection handler provided by the transport
            await self._handler(connection)
        except Exception as e:
            logger.error(f"Error in connection handler: {e}")
            # Close the problematic connection
            await connection.close()

    async def _transmit_for_connection(self, quic_conn: QuicConnection) -> None:
        """Send pending datagrams for a QUIC connection."""
        sock = self._socket
        if not sock:
            return

        for data, addr in quic_conn.datagrams_to_send(now=time.time()):
            try:
                await sock.sendto(data, addr)
            except Exception as e:
                logger.error(f"Failed to send datagram to {addr}: {e}")

    async def _manage_connections(self) -> None:
        """
        Background task to manage connection lifecycle.
        Handles cleanup of closed/idle connections.
        """
        try:
            while not self._closed:
                try:
                    # Sleep for a short interval
                    await trio.sleep(1.0)

                    # Clean up closed connections
                    await self._cleanup_closed_connections()

                    # Handle connection timeouts
                    await self._handle_connection_timeouts()

                except Exception as e:
                    logger.error(f"Error in connection management: {e}")
        except trio.Cancelled:
            raise

    async def _cleanup_closed_connections(self) -> None:
        """Remove closed connections from tracking."""
        async with self._connection_lock:
            closed_addrs = []

            for addr, connection in self._connections.items():
                if connection.is_closed:
                    closed_addrs.append(addr)

            for addr in closed_addrs:
                self._connections.pop(addr, None)
                logger.debug(f"Cleaned up closed connection from {addr}")

    async def _handle_connection_timeouts(self) -> None:
        """Handle connection timeouts and cleanup."""
        # TODO: Implement connection timeout handling
        # Check for idle connections and close them
        pass

    async def _remove_connection(self, addr: tuple[str, int]) -> None:
        """Remove a connection from tracking."""
        async with self._connection_lock:
            # Remove from active connections
            connection = self._connections.pop(addr, None)
            if connection:
                await connection.close()

            # Remove from pending connections
            quic_conn = self._pending_connections.pop(addr, None)
            if quic_conn:
                quic_conn.close()

    async def close(self) -> None:
        """Close the listener and cleanup resources."""
        if self._closed:
            return

        self._closed = True
        self._listening = False
        logger.debug("Closing QUIC listener")

        # CRITICAL: Close socket FIRST to unblock recvfrom()
        await self._cleanup_socket()

        logger.debug("SOCKET CLEANUP COMPLETE")

        # Close all connections WITHOUT using the lock during shutdown
        # (avoid deadlock if background tasks are cancelled while holding lock)
        connections_to_close = list(self._connections.values())
        pending_to_close = list(self._pending_connections.values())

        logger.debug(
            f"CLOSING {connections_to_close} connections and {pending_to_close} pending"
        )

        # Close active connections
        for connection in connections_to_close:
            try:
                await connection.close()
            except Exception as e:
                print(f"Error closing connection: {e}")

        # Close pending connections
        for quic_conn in pending_to_close:
            try:
                quic_conn.close()
            except Exception as e:
                print(f"Error closing pending connection: {e}")

        # Clear the dictionaries without lock (we're shutting down)
        self._connections.clear()
        self._pending_connections.clear()
        logger.debug("QUIC listener closed")

    async def _cleanup_socket(self) -> None:
        """Clean up the UDP socket."""
        if self._socket:
            try:
                self._socket.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
            finally:
                self._socket = None

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Get the addresses this listener is bound to.

        Returns:
            Tuple of bound multiaddrs

        """
        return tuple(self._bound_addresses)

    def is_listening(self) -> bool:
        """Check if the listener is actively listening."""
        return self._listening and not self._closed

    def get_stats(self) -> dict[str, int]:
        """Get listener statistics."""
        stats = self._stats.copy()
        stats.update(
            {
                "active_connections": len(self._connections),
                "pending_connections": len(self._pending_connections),
                "is_listening": self.is_listening(),
            }
        )
        return stats

    def __str__(self) -> str:
        """String representation of the listener."""
        addr = self._bound_addresses
        conn_count = len(self._connections)
        return f"QUICListener(addrs={addr}, connections={conn_count})"
