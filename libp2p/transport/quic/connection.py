"""
QUIC Connection implementation.
Uses aioquic's sans-IO core with trio for async operations.
"""

import logging
import socket
import time
from typing import TYPE_CHECKING, Any, Optional

from aioquic.quic import events
from aioquic.quic.connection import QuicConnection
from cryptography import x509
import multiaddr
import trio

from libp2p.abc import IMuxedConn, IRawConnection
from libp2p.custom_types import TQUICStreamHandlerFn
from libp2p.peer.id import ID

from .exceptions import (
    QUICConnectionClosedError,
    QUICConnectionError,
    QUICConnectionTimeoutError,
    QUICErrorContext,
    QUICPeerVerificationError,
    QUICStreamError,
    QUICStreamLimitError,
    QUICStreamTimeoutError,
)
from .stream import QUICStream, StreamDirection

if TYPE_CHECKING:
    from .security import QUICTLSConfigManager
    from .transport import QUICTransport

logger = logging.getLogger(__name__)


class QUICConnection(IRawConnection, IMuxedConn):
    """
    QUIC connection implementing both raw connection and muxed connection interfaces.

    Uses aioquic's sans-IO core with trio for native async support.
    QUIC natively provides stream multiplexing, so this connection acts as both
    a raw connection (for transport layer) and muxed connection (for upper layers).

    Features:
    - Native QUIC stream multiplexing
    - Integrated libp2p TLS security with peer identity verification
    - Resource-aware stream management
    - Comprehensive error handling
    - Flow control integration
    - Connection migration support
    - Performance monitoring
    """

    # Configuration constants based on research
    MAX_CONCURRENT_STREAMS = 1000
    MAX_INCOMING_STREAMS = 1000
    MAX_OUTGOING_STREAMS = 1000
    STREAM_ACCEPT_TIMEOUT = 30.0
    CONNECTION_HANDSHAKE_TIMEOUT = 30.0
    CONNECTION_CLOSE_TIMEOUT = 10.0

    def __init__(
        self,
        quic_connection: QuicConnection,
        remote_addr: tuple[str, int],
        peer_id: ID | None,
        local_peer_id: ID,
        is_initiator: bool,
        maddr: multiaddr.Multiaddr,
        transport: "QUICTransport",
        security_manager: Optional["QUICTLSConfigManager"] = None,
        resource_scope: Any | None = None,
    ):
        """
        Initialize QUIC connection with security integration.

        Args:
            quic_connection: aioquic QuicConnection instance
            remote_addr: Remote peer address
            peer_id: Remote peer ID (may be None initially)
            local_peer_id: Local peer ID
            is_initiator: Whether this is the connection initiator
            maddr: Multiaddr for this connection
            transport: Parent QUIC transport
            security_manager: Security manager for TLS/certificate handling
            resource_scope: Resource manager scope for tracking

        """
        self._quic = quic_connection
        self._remote_addr = remote_addr
        self._peer_id = peer_id
        self._local_peer_id = local_peer_id
        self.__is_initiator = is_initiator
        self._maddr = maddr
        self._transport = transport
        self._security_manager = security_manager
        self._resource_scope = resource_scope

        # Trio networking - socket may be provided by listener
        self._socket: trio.socket.SocketType | None = None
        self._connected_event = trio.Event()
        self._closed_event = trio.Event()

        # Stream management
        self._streams: dict[int, QUICStream] = {}
        self._next_stream_id: int = self._calculate_initial_stream_id()
        self._stream_handler: TQUICStreamHandlerFn | None = None
        self._stream_id_lock = trio.Lock()
        self._stream_count_lock = trio.Lock()

        # Stream counting and limits
        self._outbound_stream_count = 0
        self._inbound_stream_count = 0

        # Stream acceptance for incoming streams
        self._stream_accept_queue: list[QUICStream] = []
        self._stream_accept_event = trio.Event()
        self._accept_queue_lock = trio.Lock()

        # Connection state
        self._closed = False
        self._established = False
        self._started = False
        self._handshake_completed = False
        self._peer_verified = False

        # Security state
        self._peer_certificate: x509.Certificate | None = None
        self._handshake_events: list[events.HandshakeCompleted] = []

        # Background task management
        self._background_tasks_started = False
        self._nursery: trio.Nursery | None = None
        self._event_processing_task: Any | None = None

        # Performance and monitoring
        self._connection_start_time = time.time()
        self._stats = {
            "streams_opened": 0,
            "streams_accepted": 0,
            "streams_closed": 0,
            "streams_reset": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
            "packets_sent": 0,
            "packets_received": 0,
        }

        logger.debug(
            f"Created QUIC connection to {peer_id} "
            f"(initiator: {is_initiator}, addr: {remote_addr}, "
            "security: {security_manager is not None})"
        )

    def _calculate_initial_stream_id(self) -> int:
        """
        Calculate the initial stream ID based on QUIC specification.

        QUIC stream IDs:
        - Client-initiated bidirectional: 0, 4, 8, 12, ...
        - Server-initiated bidirectional: 1, 5, 9, 13, ...
        - Client-initiated unidirectional: 2, 6, 10, 14, ...
        - Server-initiated unidirectional: 3, 7, 11, 15, ...

        For libp2p, we primarily use bidirectional streams.
        """
        if self.__is_initiator:
            return 0  # Client starts with 0, then 4, 8, 12...
        else:
            return 1  # Server starts with 1, then 5, 9, 13...

    # Properties

    @property
    def is_initiator(self) -> bool:  # type: ignore
        """Check if this connection is the initiator."""
        return self.__is_initiator

    @property
    def is_closed(self) -> bool:
        """Check if connection is closed."""
        return self._closed

    @property
    def is_established(self) -> bool:
        """Check if connection is established (handshake completed)."""
        return self._established and self._handshake_completed

    @property
    def is_started(self) -> bool:
        """Check if connection has been started."""
        return self._started

    @property
    def is_peer_verified(self) -> bool:
        """Check if peer identity has been verified."""
        return self._peer_verified

    def multiaddr(self) -> multiaddr.Multiaddr:
        """Get the multiaddr for this connection."""
        return self._maddr

    def local_peer_id(self) -> ID:
        """Get the local peer ID."""
        return self._local_peer_id

    def remote_peer_id(self) -> ID | None:
        """Get the remote peer ID."""
        return self._peer_id

    # Connection lifecycle methods

    async def start(self) -> None:
        """
        Start the connection and its background tasks.

        This method implements the IMuxedConn.start() interface.
        It should be called to begin processing connection events.
        """
        if self._started:
            logger.warning("Connection already started")
            return

        if self._closed:
            raise QUICConnectionError("Cannot start a closed connection")

        self._started = True
        logger.debug(f"Starting QUIC connection to {self._peer_id}")

        try:
            # If this is a client connection, we need to establish the connection
            if self.__is_initiator:
                await self._initiate_connection()
            else:
                # For server connections, we're already connected via the listener
                self._established = True
                self._connected_event.set()

            logger.debug(f"QUIC connection to {self._peer_id} started")

        except Exception as e:
            logger.error(f"Failed to start connection: {e}")
            raise QUICConnectionError(f"Connection start failed: {e}") from e

    async def _initiate_connection(self) -> None:
        """Initiate client-side connection establishment."""
        try:
            with QUICErrorContext("connection_initiation", "connection"):
                # Create UDP socket using trio
                self._socket = trio.socket.socket(
                    family=socket.AF_INET, type=socket.SOCK_DGRAM
                )

                # Connect the socket to the remote address
                await self._socket.connect(self._remote_addr)

                # Start the connection establishment
                self._quic.connect(self._remote_addr, now=time.time())

                # Send initial packet(s)
                await self._transmit()

                logger.debug(f"Initiated QUIC connection to {self._remote_addr}")

        except Exception as e:
            logger.error(f"Failed to initiate connection: {e}")
            raise QUICConnectionError(f"Connection initiation failed: {e}") from e

    async def connect(self, nursery: trio.Nursery) -> None:
        """
        Establish the QUIC connection using trio nursery for background tasks.

        Args:
            nursery: Trio nursery for managing connection background tasks

        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        self._nursery = nursery

        try:
            with QUICErrorContext("connection_establishment", "connection"):
                # Start the connection if not already started
                if not self._started:
                    await self.start()

                # Start background event processing
                if not self._background_tasks_started:
                    await self._start_background_tasks()

                # Wait for handshake completion with timeout
                with trio.move_on_after(
                    self.CONNECTION_HANDSHAKE_TIMEOUT
                ) as cancel_scope:
                    await self._connected_event.wait()

                if cancel_scope.cancelled_caught:
                    raise QUICConnectionTimeoutError(
                        "Connection handshake timed out after"
                        f"{self.CONNECTION_HANDSHAKE_TIMEOUT}s"
                    )

                # Verify peer identity using security manager
                await self._verify_peer_identity_with_security()

                self._established = True
                logger.info(f"QUIC connection established with {self._peer_id}")

        except Exception as e:
            logger.error(f"Failed to establish connection: {e}")
            await self.close()
            raise

    async def _start_background_tasks(self) -> None:
        """Start background tasks for connection management."""
        if self._background_tasks_started or not self._nursery:
            return

        self._background_tasks_started = True

        # Start event processing task
        self._nursery.start_soon(self._event_processing_loop)

        # Start periodic tasks
        self._nursery.start_soon(self._periodic_maintenance)

        logger.debug("Started background tasks for QUIC connection")

    async def _event_processing_loop(self) -> None:
        """Main event processing loop for the connection."""
        logger.debug("Started QUIC event processing loop")

        try:
            while not self._closed:
                # Process QUIC events
                await self._process_quic_events()

                # Handle timer events
                await self._handle_timer_events()

                # Transmit any pending data
                await self._transmit()

                # Short sleep to prevent busy waiting
                await trio.sleep(0.001)  # 1ms

        except Exception as e:
            logger.error(f"Error in event processing loop: {e}")
            await self._handle_connection_error(e)
        finally:
            logger.debug("QUIC event processing loop finished")

    async def _periodic_maintenance(self) -> None:
        """Perform periodic connection maintenance."""
        try:
            while not self._closed:
                # Update connection statistics
                self._update_stats()

                # Check for idle streams that can be cleaned up
                await self._cleanup_idle_streams()

                # Sleep for maintenance interval
                await trio.sleep(30.0)  # 30 seconds

        except Exception as e:
            logger.error(f"Error in periodic maintenance: {e}")

    # Security and identity methods

    async def _verify_peer_identity_with_security(self) -> None:
        """
        Verify peer identity using integrated security manager.

        Raises:
            QUICPeerVerificationError: If peer verification fails

        """
        if not self._security_manager:
            logger.warning("No security manager available for peer verification")
            return

        try:
            # Extract peer certificate from TLS handshake
            await self._extract_peer_certificate()

            if not self._peer_certificate:
                logger.warning("No peer certificate available for verification")
                return

            # Validate certificate format and accessibility
            if not self._validate_peer_certificate():
                raise QUICPeerVerificationError("Peer certificate validation failed")

            # Verify peer identity using security manager
            verified_peer_id = self._security_manager.verify_peer_identity(
                self._peer_certificate,
                self._peer_id,  # Expected peer ID for outbound connections
            )

            # Update peer ID if it wasn't known (inbound connections)
            if not self._peer_id:
                self._peer_id = verified_peer_id
                logger.info(f"Discovered peer ID from certificate: {verified_peer_id}")
            elif self._peer_id != verified_peer_id:
                raise QUICPeerVerificationError(
                    f"Peer ID mismatch: expected {self._peer_id}, "
                    f"got {verified_peer_id}"
                )

            self._peer_verified = True
            logger.info(f"Peer identity verified successfully: {verified_peer_id}")

        except QUICPeerVerificationError:
            # Re-raise verification errors as-is
            raise
        except Exception as e:
            # Wrap other errors in verification error
            raise QUICPeerVerificationError(f"Peer verification failed: {e}") from e

    async def _extract_peer_certificate(self) -> None:
        """Extract peer certificate from completed TLS handshake."""
        try:
            # Get peer certificate from aioquic TLS context
            # Based on aioquic source code: QuicConnection.tls._peer_certificate
            if hasattr(self._quic, "tls") and self._quic.tls:
                tls_context = self._quic.tls

                # Check if peer certificate is available in TLS context
                if (
                    hasattr(tls_context, "_peer_certificate")
                    and tls_context._peer_certificate
                ):
                    # aioquic stores the peer certificate as cryptography
                    # x509.Certificate
                    self._peer_certificate = tls_context._peer_certificate
                    logger.debug(
                        f"Extracted peer certificate: {self._peer_certificate.subject}"
                    )
                else:
                    logger.debug("No peer certificate found in TLS context")

            else:
                logger.debug("No TLS context available for certificate extraction")

        except Exception as e:
            logger.warning(f"Failed to extract peer certificate: {e}")

            # Try alternative approach - check if certificate is in handshake events
            try:
                # Some versions of aioquic might expose certificate differently
                if hasattr(self._quic, "configuration") and self._quic.configuration:
                    config = self._quic.configuration
                    if hasattr(config, "certificate") and config.certificate:
                        # This would be the local certificate, not peer certificate
                        # but we can use it for debugging
                        logger.debug("Found local certificate in configuration")

            except Exception as inner_e:
                logger.debug(
                    f"Alternative certificate extraction also failed: {inner_e}"
                )

    async def get_peer_certificate(self) -> x509.Certificate | None:
        """
        Get the peer's TLS certificate.

        Returns:
            The peer's X.509 certificate, or None if not available

        """
        # If we don't have a certificate yet, try to extract it
        if not self._peer_certificate and self._handshake_completed:
            await self._extract_peer_certificate()

        return self._peer_certificate

    def _validate_peer_certificate(self) -> bool:
        """
        Validate that the peer certificate is properly formatted and accessible.

        Returns:
            True if certificate is valid and accessible, False otherwise

        """
        if not self._peer_certificate:
            return False

        try:
            # Basic validation - try to access certificate properties
            subject = self._peer_certificate.subject
            serial_number = self._peer_certificate.serial_number

            logger.debug(
                f"Certificate validation - Subject: {subject}, Serial: {serial_number}"
            )
            return True

        except Exception as e:
            logger.error(f"Certificate validation failed: {e}")
            return False

    def get_security_manager(self) -> Optional["QUICTLSConfigManager"]:
        """Get the security manager for this connection."""
        return self._security_manager

    def get_security_info(self) -> dict[str, Any]:
        """Get security-related information about the connection."""
        info: dict[str, bool | Any | None] = {
            "peer_verified": self._peer_verified,
            "handshake_complete": self._handshake_completed,
            "peer_id": str(self._peer_id) if self._peer_id else None,
            "local_peer_id": str(self._local_peer_id),
            "is_initiator": self.__is_initiator,
            "has_certificate": self._peer_certificate is not None,
            "security_manager_available": self._security_manager is not None,
        }

        # Add certificate details if available
        if self._peer_certificate:
            try:
                info.update(
                    {
                        "certificate_subject": str(self._peer_certificate.subject),
                        "certificate_issuer": str(self._peer_certificate.issuer),
                        "certificate_serial": str(self._peer_certificate.serial_number),
                        "certificate_not_before": (
                            self._peer_certificate.not_valid_before.isoformat()
                        ),
                        "certificate_not_after": (
                            self._peer_certificate.not_valid_after.isoformat()
                        ),
                    }
                )
            except Exception as e:
                info["certificate_error"] = str(e)

        # Add TLS context debug info
        try:
            if hasattr(self._quic, "tls") and self._quic.tls:
                tls_info = {
                    "tls_context_available": True,
                    "tls_state": getattr(self._quic.tls, "state", None),
                }

                # Check for peer certificate in TLS context
                if hasattr(self._quic.tls, "_peer_certificate"):
                    tls_info["tls_peer_certificate_available"] = (
                        self._quic.tls._peer_certificate is not None
                    )

                info["tls_debug"] = tls_info
            else:
                info["tls_debug"] = {"tls_context_available": False}

        except Exception as e:
            info["tls_debug"] = {"error": str(e)}

        return info

    # Legacy compatibility for existing code
    async def verify_peer_identity(self) -> None:
        """
        Legacy method for compatibility - delegates to security manager.
        """
        await self._verify_peer_identity_with_security()

    # Stream management methods (IMuxedConn interface)

    async def open_stream(self, timeout: float = 5.0) -> QUICStream:
        """
        Open a new outbound stream

        Args:
            timeout: Timeout for stream creation

        Returns:
            New QUIC stream

        Raises:
            QUICStreamLimitError: Too many concurrent streams
            QUICConnectionClosedError: Connection is closed
            QUICStreamTimeoutError: Stream creation timed out

        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        if not self._started:
            raise QUICConnectionError("Connection not started")

        # Check stream limits
        async with self._stream_count_lock:
            if self._outbound_stream_count >= self.MAX_OUTGOING_STREAMS:
                raise QUICStreamLimitError(
                    f"Maximum outbound streams ({self.MAX_OUTGOING_STREAMS}) reached"
                )

        with trio.move_on_after(timeout):
            async with self._stream_id_lock:
                # Generate next stream ID
                stream_id = self._next_stream_id
                self._next_stream_id += 4  # Increment by 4 for bidirectional streams

                stream = QUICStream(
                    connection=self,
                    stream_id=stream_id,
                    direction=StreamDirection.OUTBOUND,
                    resource_scope=self._resource_scope,
                    remote_addr=self._remote_addr,
                )

                self._streams[stream_id] = stream

                async with self._stream_count_lock:
                    self._outbound_stream_count += 1
                    self._stats["streams_opened"] += 1

                logger.debug(f"Opened outbound QUIC stream {stream_id}")
                return stream

        raise QUICStreamTimeoutError(f"Stream creation timed out after {timeout}s")

    async def accept_stream(self, timeout: float | None = None) -> QUICStream:
        """
        Accept an incoming stream with timeout support.

        Args:
            timeout: Optional timeout for accepting streams

        Returns:
            Accepted incoming stream

        Raises:
            QUICStreamTimeoutError: Accept timeout exceeded
            QUICConnectionClosedError: Connection is closed

        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        timeout = timeout or self.STREAM_ACCEPT_TIMEOUT

        with trio.move_on_after(timeout):
            while True:
                async with self._accept_queue_lock:
                    if self._stream_accept_queue:
                        stream = self._stream_accept_queue.pop(0)
                        logger.debug(f"Accepted inbound stream {stream.stream_id}")
                        return stream

                if self._closed:
                    raise QUICConnectionClosedError(
                        "Connection closed while accepting stream"
                    )

                # Wait for new streams
                await self._stream_accept_event.wait()
                self._stream_accept_event = trio.Event()

        raise QUICStreamTimeoutError(f"Stream accept timed out after {timeout}s")

    def set_stream_handler(self, handler_function: TQUICStreamHandlerFn) -> None:
        """
        Set handler for incoming streams.

        Args:
            handler_function: Function to handle new incoming streams

        """
        self._stream_handler = handler_function
        logger.debug("Set stream handler for incoming streams")

    def _remove_stream(self, stream_id: int) -> None:
        """
        Remove stream from connection registry.
        Called by stream cleanup process.
        """
        if stream_id in self._streams:
            stream = self._streams.pop(stream_id)

            # Update stream counts asynchronously
            async def update_counts() -> None:
                async with self._stream_count_lock:
                    if stream.direction == StreamDirection.OUTBOUND:
                        self._outbound_stream_count = max(
                            0, self._outbound_stream_count - 1
                        )
                    else:
                        self._inbound_stream_count = max(
                            0, self._inbound_stream_count - 1
                        )
                    self._stats["streams_closed"] += 1

            # Schedule count update if we're in a trio context
            if self._nursery:
                self._nursery.start_soon(update_counts)

            logger.debug(f"Removed stream {stream_id} from connection")

    # QUIC event handling

    async def _process_quic_events(self) -> None:
        """Process all pending QUIC events."""
        while True:
            event = self._quic.next_event()
            if event is None:
                break

            try:
                await self._handle_quic_event(event)
            except Exception as e:
                logger.error(f"Error handling QUIC event {type(event).__name__}: {e}")

    async def _handle_quic_event(self, event: events.QuicEvent) -> None:
        """Handle a single QUIC event."""
        if isinstance(event, events.ConnectionTerminated):
            await self._handle_connection_terminated(event)
        elif isinstance(event, events.HandshakeCompleted):
            await self._handle_handshake_completed(event)
        elif isinstance(event, events.StreamDataReceived):
            await self._handle_stream_data(event)
        elif isinstance(event, events.StreamReset):
            await self._handle_stream_reset(event)
        elif isinstance(event, events.DatagramFrameReceived):
            await self._handle_datagram_received(event)
        else:
            logger.debug(f"Unhandled QUIC event: {type(event).__name__}")

    async def _handle_handshake_completed(
        self, event: events.HandshakeCompleted
    ) -> None:
        """Handle handshake completion with security integration."""
        logger.debug("QUIC handshake completed")
        self._handshake_completed = True

        # Store handshake event for security verification
        self._handshake_events.append(event)

        # Try to extract certificate information after handshake
        await self._extract_peer_certificate()

        self._connected_event.set()

    async def _handle_connection_terminated(
        self, event: events.ConnectionTerminated
    ) -> None:
        """Handle connection termination."""
        logger.debug(f"QUIC connection terminated: {event.reason_phrase}")

        # Close all streams
        for stream in list(self._streams.values()):
            if event.error_code:
                await stream.handle_reset(event.error_code)
            else:
                await stream.close()

        self._streams.clear()
        self._closed = True
        self._closed_event.set()

    async def _handle_stream_data(self, event: events.StreamDataReceived) -> None:
        """Stream data handling with proper error management."""
        stream_id = event.stream_id
        self._stats["bytes_received"] += len(event.data)

        try:
            with QUICErrorContext("stream_data_handling", "stream"):
                # Get or create stream
                stream = await self._get_or_create_stream(stream_id)

                # Forward data to stream
                await stream.handle_data_received(event.data, event.end_stream)

        except Exception as e:
            logger.error(f"Error handling stream data for stream {stream_id}: {e}")
            # Reset the stream on error
            if stream_id in self._streams:
                await self._streams[stream_id].reset(error_code=1)

    async def _get_or_create_stream(self, stream_id: int) -> QUICStream:
        """Get existing stream or create new inbound stream."""
        if stream_id in self._streams:
            return self._streams[stream_id]

        # Check if this is an incoming stream
        is_incoming = self._is_incoming_stream(stream_id)

        if not is_incoming:
            # This shouldn't happen - outbound streams should be created by open_stream
            raise QUICStreamError(
                f"Received data for unknown outbound stream {stream_id}"
            )

        # Check stream limits for incoming streams
        async with self._stream_count_lock:
            if self._inbound_stream_count >= self.MAX_INCOMING_STREAMS:
                logger.warning(f"Rejecting incoming stream {stream_id}: limit reached")
                # Send reset to reject the stream
                self._quic.reset_stream(
                    stream_id, error_code=0x04
                )  # STREAM_LIMIT_ERROR
                await self._transmit()
                raise QUICStreamLimitError("Too many inbound streams")

        # Create new inbound stream
        stream = QUICStream(
            connection=self,
            stream_id=stream_id,
            direction=StreamDirection.INBOUND,
            resource_scope=self._resource_scope,
            remote_addr=self._remote_addr,
        )

        self._streams[stream_id] = stream

        async with self._stream_count_lock:
            self._inbound_stream_count += 1
            self._stats["streams_accepted"] += 1

        # Add to accept queue and notify handler
        async with self._accept_queue_lock:
            self._stream_accept_queue.append(stream)
            self._stream_accept_event.set()

        # Handle directly with stream handler if available
        if self._stream_handler:
            try:
                if self._nursery:
                    self._nursery.start_soon(self._stream_handler, stream)
                else:
                    await self._stream_handler(stream)
            except Exception as e:
                logger.error(f"Error in stream handler for stream {stream_id}: {e}")

        logger.debug(f"Created inbound stream {stream_id}")
        return stream

    def _is_incoming_stream(self, stream_id: int) -> bool:
        """
        Determine if a stream ID represents an incoming stream.

        For bidirectional streams:
        - Even IDs are client-initiated
        - Odd IDs are server-initiated
        """
        if self.__is_initiator:
            # We're the client, so odd stream IDs are incoming
            return stream_id % 2 == 1
        else:
            # We're the server, so even stream IDs are incoming
            return stream_id % 2 == 0

    async def _handle_stream_reset(self, event: events.StreamReset) -> None:
        """Stream reset handling."""
        stream_id = event.stream_id
        self._stats["streams_reset"] += 1

        if stream_id in self._streams:
            try:
                stream = self._streams[stream_id]
                await stream.handle_reset(event.error_code)
                logger.debug(
                    f"Handled reset for stream {stream_id}"
                    f"with error code {event.error_code}"
                )
            except Exception as e:
                logger.error(f"Error handling stream reset for {stream_id}: {e}")
                # Force remove the stream
                self._remove_stream(stream_id)
        else:
            logger.debug(f"Received reset for unknown stream {stream_id}")

    async def _handle_datagram_received(
        self, event: events.DatagramFrameReceived
    ) -> None:
        """Handle received datagrams."""
        # For future datagram support
        logger.debug(f"Received datagram: {len(event.data)} bytes")

    async def _handle_timer_events(self) -> None:
        """Handle QUIC timer events."""
        timer = self._quic.get_timer()
        if timer is not None:
            now = time.time()
            if timer <= now:
                self._quic.handle_timer(now=now)

    # Network transmission

    async def _transmit(self) -> None:
        """Send pending datagrams using trio."""
        sock = self._socket
        if not sock:
            return

        try:
            datagrams = self._quic.datagrams_to_send(now=time.time())
            for data, addr in datagrams:
                await sock.sendto(data, addr)
                self._stats["packets_sent"] += 1
                self._stats["bytes_sent"] += len(data)
        except Exception as e:
            logger.error(f"Failed to send datagram: {e}")
            await self._handle_connection_error(e)

    # Error handling

    async def _handle_connection_error(self, error: Exception) -> None:
        """Handle connection-level errors."""
        logger.error(f"Connection error: {error}")

        if not self._closed:
            try:
                await self.close()
            except Exception as close_error:
                logger.error(f"Error during connection close: {close_error}")

    # Connection close

    async def close(self) -> None:
        """Connection close with proper stream cleanup."""
        if self._closed:
            return

        self._closed = True
        logger.debug(f"Closing QUIC connection to {self._peer_id}")

        try:
            # Close all streams gracefully
            stream_close_tasks = []
            for stream in list(self._streams.values()):
                if stream.can_write() or stream.can_read():
                    stream_close_tasks.append(stream.close)

            if stream_close_tasks and self._nursery:
                try:
                    # Close streams concurrently with timeout
                    with trio.move_on_after(self.CONNECTION_CLOSE_TIMEOUT):
                        async with trio.open_nursery() as close_nursery:
                            for task in stream_close_tasks:
                                close_nursery.start_soon(task)
                except Exception as e:
                    logger.warning(f"Error during graceful stream close: {e}")
                    # Force reset remaining streams
                    for stream in self._streams.values():
                        try:
                            await stream.reset(error_code=0)
                        except Exception:
                            pass

            # Close QUIC connection
            self._quic.close()
            if self._socket:
                await self._transmit()  # Send close frames

            # Close socket
            if self._socket:
                self._socket.close()

            self._streams.clear()
            self._closed_event.set()

            logger.debug(f"QUIC connection to {self._peer_id} closed")

        except Exception as e:
            logger.error(f"Error during connection close: {e}")

    # IRawConnection interface (for compatibility)

    def get_remote_address(self) -> tuple[str, int]:
        return self._remote_addr

    async def write(self, data: bytes) -> None:
        """
        Write data to the connection.
        For QUIC, this creates a new stream for each write operation.
        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        stream = await self.open_stream()
        try:
            await stream.write(data)
            await stream.close_write()
        except Exception:
            await stream.reset()
            raise

    async def read(self, n: int | None = -1) -> bytes:
        """
        Read data from the connection.
        For QUIC, this reads from the next available stream.
        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        # For raw connection interface, we need to handle this differently
        # In practice, upper layers will use the muxed connection interface
        raise NotImplementedError(
            "Use muxed connection interface for stream-based reading"
        )

    # Utility and monitoring methods

    def get_stream_stats(self) -> dict[str, Any]:
        """Get stream statistics for monitoring."""
        return {
            "total_streams": len(self._streams),
            "outbound_streams": self._outbound_stream_count,
            "inbound_streams": self._inbound_stream_count,
            "max_streams": self.MAX_CONCURRENT_STREAMS,
            "stream_utilization": len(self._streams) / self.MAX_CONCURRENT_STREAMS,
            "stats": self._stats.copy(),
        }

    def get_active_streams(self) -> list[QUICStream]:
        """Get list of active streams."""
        return [stream for stream in self._streams.values() if not stream.is_closed()]

    def get_streams_by_protocol(self, protocol: str) -> list[QUICStream]:
        """Get streams filtered by protocol."""
        return [
            stream
            for stream in self._streams.values()
            if stream.protocol == protocol and not stream.is_closed()
        ]

    def _update_stats(self) -> None:
        """Update connection statistics."""
        # Add any periodic stats updates here
        pass

    async def _cleanup_idle_streams(self) -> None:
        """Clean up idle streams that are no longer needed."""
        current_time = time.time()
        streams_to_cleanup = []

        for stream in self._streams.values():
            if stream.is_closed():
                # Check if stream has been closed for a while
                if hasattr(stream, "_timeline") and stream._timeline.closed_at:
                    if current_time - stream._timeline.closed_at > 60:  # 1 minute
                        streams_to_cleanup.append(stream.stream_id)

        for stream_id in streams_to_cleanup:
            self._remove_stream(int(stream_id))

    # String representation

    def __repr__(self) -> str:
        return (
            f"QUICConnection(peer={self._peer_id}, "
            f"addr={self._remote_addr}, "
            f"initiator={self.__is_initiator}, "
            f"verified={self._peer_verified}, "
            f"established={self._established}, "
            f"streams={len(self._streams)})"
        )

    def __str__(self) -> str:
        return f"QUICConnection({self._peer_id})"
