"""
QUIC Connection implementation.
Manages bidirectional QUIC connections with integrated stream multiplexing.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
import logging
import socket
import time
from typing import TYPE_CHECKING, Any, Optional

from aioquic.quic import events
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent
from cryptography import x509
import multiaddr
import trio

from libp2p.abc import IMuxedConn, IRawConnection
from libp2p.custom_types import TQUICStreamHandlerFn
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction
from libp2p.stream_muxer.exceptions import MuxedConnUnavailable

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
    - COMPLETE connection ID management (fixes the original issue)
    """

    def __init__(
        self,
        quic_connection: QuicConnection,
        remote_addr: tuple[str, int],
        remote_peer_id: ID | None,
        local_peer_id: ID,
        is_initiator: bool,
        maddr: multiaddr.Multiaddr,
        transport: "QUICTransport",
        security_manager: Optional["QUICTLSConfigManager"] = None,
        resource_scope: Any | None = None,
        listener_socket: trio.socket.SocketType | None = None,
    ):
        """
        Initialize QUIC connection with security integration.

        Args:
            quic_connection: aioquic QuicConnection instance
            remote_addr: Remote peer address
            remote_peer_id: Remote peer ID (may be None initially)
            local_peer_id: Local peer ID
            is_initiator: Whether this is the connection initiator
            maddr: Multiaddr for this connection
            transport: Parent QUIC transport
            security_manager: Security manager for TLS/certificate handling
            resource_scope: Resource manager scope for tracking
            listener_socket: Socket of listener to transmit data

        """
        self._quic = quic_connection
        self._remote_addr = remote_addr
        self._remote_peer_id = remote_peer_id
        self._local_peer_id = local_peer_id
        self.peer_id = remote_peer_id or local_peer_id
        self._is_initiator = is_initiator
        self._maddr = maddr
        self._transport = transport
        self._security_manager = security_manager
        self._resource_scope = resource_scope

        # Trio networking - socket may be provided by listener
        self._socket = listener_socket if listener_socket else None
        self._owns_socket = listener_socket is None
        self._connected_event = trio.Event()
        self._closed_event = trio.Event()

        self._streams: dict[int, QUICStream] = {}
        self._stream_cache: dict[int, QUICStream] = {}  # Cache for frequent lookups
        self._next_stream_id: int = self._calculate_initial_stream_id()
        self._stream_handler: TQUICStreamHandlerFn | None = None

        # Single lock for all stream operations
        self._stream_lock = trio.Lock()

        # Stream counting and limits
        self._outbound_stream_count: int = 0
        self._inbound_stream_count: int = 0

        # Stream acceptance for incoming streams
        self._stream_accept_queue: list[QUICStream] = []
        self._stream_accept_event = trio.Event()

        # Connection state
        self._closed: bool = False
        self._established: bool = False
        self._started: bool = False
        self._handshake_completed: bool = False
        self._peer_verified: bool = False

        # Security state
        self._peer_certificate: x509.Certificate | None = None
        self._handshake_events: list[events.HandshakeCompleted] = []

        # Background task management
        self._background_tasks_started: bool = False
        self._nursery: trio.Nursery | None = None
        self._event_processing_task: Any | None = None
        self.on_close: Callable[[], Awaitable[None]] | None = None
        self.event_started = trio.Event()

        self._available_connection_ids: set[bytes] = set()
        self._current_connection_id: bytes | None = None
        self._retired_connection_ids: set[bytes] = set()
        self._connection_id_sequence_numbers: set[int] = set()

        # Event processing control with batching
        self._event_processing_active: bool = False
        self._event_batch: list[events.QuicEvent] = []
        self._event_batch_size: int = 10
        self._last_event_time: float = 0.0

        # Set quic connection configuration
        self.CONNECTION_CLOSE_TIMEOUT = self._transport._config.CONNECTION_CLOSE_TIMEOUT
        self.MAX_INCOMING_STREAMS = self._transport._config.MAX_INCOMING_STREAMS
        self.MAX_OUTGOING_STREAMS = self._transport._config.MAX_OUTGOING_STREAMS
        self.CONNECTION_HANDSHAKE_TIMEOUT = (
            self._transport._config.CONNECTION_HANDSHAKE_TIMEOUT
        )
        self.MAX_CONCURRENT_STREAMS = self._transport._config.MAX_CONCURRENT_STREAMS

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
            "connection_ids_issued": 0,
            "connection_ids_retired": 0,
            "connection_id_changes": 0,
        }

        logger.debug(
            f"Created QUIC connection to {self._remote_peer_id} "
            f"(initiator: {self._is_initiator}, addr: {self._remote_addr}, "
            f"security: {self._security_manager is not None})"
        )

    # Resource manager integration
    def set_resource_scope(self, scope: Any) -> None:
        """
        Attach a resource scope to the connection for stream construction and cleanup.
        """
        self._resource_scope = scope

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
        if self._is_initiator:
            return 0
        else:
            return 1

    @property
    def is_initiator(self) -> bool:  # type: ignore
        """Check if this connection is the initiator."""
        return self._is_initiator

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
        return self._remote_peer_id

    def get_connection_id_stats(self) -> dict[str, Any]:
        """Get connection ID statistics and current state."""
        return {
            "available_connection_ids": len(self._available_connection_ids),
            "current_connection_id": self._current_connection_id.hex()
            if self._current_connection_id
            else None,
            "retired_connection_ids": len(self._retired_connection_ids),
            "connection_ids_issued": self._stats["connection_ids_issued"],
            "connection_ids_retired": self._stats["connection_ids_retired"],
            "connection_id_changes": self._stats["connection_id_changes"],
            "available_cid_list": [cid.hex() for cid in self._available_connection_ids],
        }

    def get_current_connection_id(self) -> bytes | None:
        """Get the current connection ID."""
        return self._current_connection_id

    # Fast stream lookup with caching
    def _get_stream_fast(self, stream_id: int) -> QUICStream | None:
        """Get stream with caching for performance."""
        # Try cache first
        stream = self._stream_cache.get(stream_id)
        if stream is not None:
            return stream

        # Fallback to main dict
        stream = self._streams.get(stream_id)
        if stream is not None:
            self._stream_cache[stream_id] = stream

        return stream

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
        self.event_started.set()
        logger.debug(f"Starting QUIC connection to {self._remote_peer_id}")

        try:
            # If this is a client connection, we need to establish the connection
            if self._is_initiator:
                await self._initiate_connection()
            else:
                # For server connections, we're already connected via the listener
                self._established = True
                self._connected_event.set()

            logger.debug(f"QUIC connection to {self._remote_peer_id} started")

        except Exception as e:
            logger.error(f"Failed to start connection: {e}")
            raise QUICConnectionError(f"Connection start failed: {e}") from e

    async def _initiate_connection(self) -> None:
        """Initiate client-side connection, reusing listener socket if available."""
        try:
            with QUICErrorContext("connection_initiation", "connection"):
                if not self._socket:
                    logger.debug("Creating new socket for outbound connection")
                    self._socket = trio.socket.socket(
                        family=socket.AF_INET, type=socket.SOCK_DGRAM
                    )

                await self._socket.bind(("0.0.0.0", 0))

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
                logger.debug("STARTING TO CONNECT")
                if not self._started:
                    await self.start()

                # Start background event processing
                if not self._background_tasks_started:
                    logger.debug("STARTING BACKGROUND TASK")
                    await self._start_background_tasks()
                else:
                    logger.debug("BACKGROUND TASK ALREADY STARTED")

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

                logger.debug(
                    "QUICConnection: Verifying peer identity with security manager"
                )
                # Verify peer identity using security manager
                peer_id = await self._verify_peer_identity_with_security()

                if peer_id:
                    self.peer_id = peer_id

                logger.debug(f"QUICConnection {id(self)}: Peer identity verified")
                self._established = True
                logger.debug(f"QUIC connection established with {self._remote_peer_id}")

        except Exception as e:
            logger.error(f"Failed to establish connection: {e}")
            await self.close()
            raise

    async def _start_background_tasks(self) -> None:
        """Start background tasks for connection management."""
        if self._background_tasks_started or not self._nursery:
            return

        self._background_tasks_started = True

        if self._is_initiator:
            self._nursery.start_soon(async_fn=self._client_packet_receiver)

        self._nursery.start_soon(async_fn=self._event_processing_loop)
        self._nursery.start_soon(async_fn=self._periodic_maintenance)

        logger.debug("Started background tasks for QUIC connection")

    async def _event_processing_loop(self) -> None:
        """Main event processing loop for the connection."""
        logger.debug(
            f"Started QUIC event processing loop for connection id: {id(self)} "
            f"and local peer id {str(self.local_peer_id())}"
        )

        try:
            while not self._closed:
                # Batch process events
                await self._process_quic_events_batched()

                # Handle timer events
                await self._handle_timer_events()

                # Transmit any pending data
                await self._transmit()

                # Short sleep to prevent busy waiting
                await trio.sleep(0.01)

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

                if logger.isEnabledFor(logging.DEBUG):
                    cid_stats = self.get_connection_id_stats()
                    logger.debug(f"Connection ID stats: {cid_stats}")

                # Clean cache periodically
                await self._cleanup_cache()

                # Sleep for maintenance interval
                await trio.sleep(30.0)  # 30 seconds

        except Exception as e:
            logger.error(f"Error in periodic maintenance: {e}")

    async def _cleanup_cache(self) -> None:
        """Clean up stream cache periodically to prevent memory leaks."""
        if len(self._stream_cache) > 100:  # Arbitrary threshold
            # Remove closed streams from cache
            closed_stream_ids = [
                sid for sid, stream in self._stream_cache.items() if stream.is_closed()
            ]
            for sid in closed_stream_ids:
                self._stream_cache.pop(sid, None)

    async def _client_packet_receiver(self) -> None:
        """Receive packets for client connections."""
        logger.debug("Starting client packet receiver")
        logger.debug("Started QUIC client packet receiver")

        try:
            while not self._closed and self._socket:
                try:
                    # Receive UDP packets
                    data, addr = await self._socket.recvfrom(65536)
                    logger.debug(f"Client received {len(data)} bytes from {addr}")

                    # Feed packet to QUIC connection
                    self._quic.receive_datagram(data, addr, now=time.time())

                    # Batch process events
                    await self._process_quic_events_batched()

                    # Send any response packets
                    await self._transmit()

                except trio.ClosedResourceError:
                    logger.debug("Client socket closed")
                    break
                except Exception as e:
                    logger.error(f"Error receiving client packet: {e}")
                    await trio.sleep(0.01)

        except trio.Cancelled:
            logger.debug("Client packet receiver cancelled")
            raise
        finally:
            logger.debug("Client packet receiver terminated")

    # Security and identity methods

    async def _verify_peer_identity_with_security(self) -> ID | None:
        """
        Verify peer identity using integrated security manager.

        Raises:
            QUICPeerVerificationError: If peer verification fails

        """
        logger.debug("VERIFYING PEER IDENTITY")
        if not self._security_manager:
            logger.debug("No security manager available for peer verification")
            return None

        try:
            # Extract peer certificate from TLS handshake
            await self._extract_peer_certificate()

            if not self._peer_certificate:
                logger.debug("No peer certificate available for verification")
                return None

            # Validate certificate format and accessibility
            if not self._validate_peer_certificate():
                logger.debug("Validation Failed for peer cerificate")
                raise QUICPeerVerificationError("Peer certificate validation failed")

            # Verify peer identity using security manager
            verified_peer_id = self._security_manager.verify_peer_identity(
                self._peer_certificate,
                self._remote_peer_id,  # Expected peer ID for outbound connections
            )

            # Update peer ID if it wasn't known (inbound connections)
            if not self._remote_peer_id:
                self._remote_peer_id = verified_peer_id
                logger.debug(f"Discovered peer ID from certificate: {verified_peer_id}")
            elif self._remote_peer_id != verified_peer_id:
                raise QUICPeerVerificationError(
                    f"Peer ID mismatch: expected {self._remote_peer_id}, "
                    "got {verified_peer_id}"
                )

            self._peer_verified = True
            logger.debug(f"Peer identity verified successfully: {verified_peer_id}")

            return verified_peer_id

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
            if self._quic.tls:
                tls_context = self._quic.tls

                if tls_context._peer_certificate:
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
                config = self._quic.configuration
                if hasattr(config, "certificate") and config.certificate:
                    # This would be the local certificate, not peer certificate
                    # but we can use it for debugging
                    logger.debug("Found local certificate in configuration")

            except Exception as inner_e:
                logger.error(
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
            "peer_id": str(self._remote_peer_id) if self._remote_peer_id else None,
            "local_peer_id": str(self._local_peer_id),
            "is_initiator": self._is_initiator,
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

        # Use single lock for all stream operations
        with trio.move_on_after(timeout):
            async with self._stream_lock:
                # Check stream limits inside lock
                if self._outbound_stream_count >= self.MAX_OUTGOING_STREAMS:
                    raise QUICStreamLimitError(
                        "Maximum outbound streams "
                        f"({self.MAX_OUTGOING_STREAMS}) reached"
                    )

                # Generate next stream ID
                stream_id = self._next_stream_id
                self._next_stream_id += 4  # Increment by 4 for bidirectional streams

                # Acquire stream scope from resource manager if available
                stream_scope = None
                if self._resource_scope and hasattr(
                    self._resource_scope, "_resource_manager"
                ):
                    try:
                        stream_scope = (
                            self._resource_scope._resource_manager.open_stream(
                                peer_id=self._remote_peer_id,
                                direction=Direction.OUTBOUND,
                            )
                        )
                    except Exception as e:
                        logger.warning(f"Failed to acquire stream scope: {e}")
                        raise QUICStreamLimitError(f"Resource limit exceeded: {e}")

                stream = QUICStream(
                    connection=self,
                    stream_id=stream_id,
                    direction=StreamDirection.OUTBOUND,
                    resource_scope=stream_scope,
                    remote_addr=self._remote_addr,
                )

                self._streams[stream_id] = stream
                self._stream_cache[stream_id] = stream  # Add to cache

                self._outbound_stream_count += 1
                self._stats["streams_opened"] += 1

                logger.debug(f"Opened outbound QUIC stream {stream_id}")
                return stream

        raise QUICStreamTimeoutError(f"Stream creation timed out after {timeout}s")

    async def accept_stream(self, timeout: float | None = None) -> QUICStream:
        """
        Accept incoming stream.

        Args:
            timeout: Optional timeout. If None, waits indefinitely.

        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        if timeout is not None:
            with trio.move_on_after(timeout):
                return await self._accept_stream_impl()
            # Timeout occurred
            if self._closed_event.is_set() or self._closed:
                raise MuxedConnUnavailable("QUIC connection closed during timeout")
            else:
                raise QUICStreamTimeoutError(
                    f"Stream accept timed out after {timeout}s"
                )
        else:
            # No timeout - wait indefinitely
            return await self._accept_stream_impl()

    async def _accept_stream_impl(self) -> QUICStream:
        while True:
            if self._closed:
                raise MuxedConnUnavailable("QUIC connection is closed")

            # Use single lock for stream acceptance
            async with self._stream_lock:
                if self._stream_accept_queue:
                    stream = self._stream_accept_queue.pop(0)
                    logger.debug(f"Accepted inbound stream {stream.stream_id}")
                    return stream

            if self._closed:
                raise MuxedConnUnavailable("Connection closed while accepting stream")

            # Wait for new streams indefinitely
            await self._stream_accept_event.wait()

        raise QUICConnectionError("Error occurred while waiting to accept stream")

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
            # Remove from cache too
            self._stream_cache.pop(stream_id, None)

            # Update stream counts asynchronously
            async def update_counts() -> None:
                async with self._stream_lock:
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

    # Batched event processing to reduce overhead
    async def _process_quic_events_batched(self) -> None:
        """Process QUIC events in batches for better performance."""
        if self._event_processing_active:
            return  # Prevent recursion

        self._event_processing_active = True

        try:
            current_time = time.time()
            events_processed = 0

            # Collect events into batch
            while events_processed < self._event_batch_size:
                event = self._quic.next_event()
                if event is None:
                    break

                self._event_batch.append(event)
                events_processed += 1

            # Process batch if we have events or timeout
            if self._event_batch and (
                len(self._event_batch) >= self._event_batch_size
                or current_time - self._last_event_time > 0.01  # 10ms timeout
            ):
                await self._process_event_batch()
                self._event_batch.clear()
                self._last_event_time = current_time

        finally:
            self._event_processing_active = False

    async def _process_event_batch(self) -> None:
        """Process a batch of events efficiently."""
        if not self._event_batch:
            return

        # Group events by type for batch processing where possible
        events_by_type: defaultdict[str, list[QuicEvent]] = defaultdict(list)
        for event in self._event_batch:
            events_by_type[type(event).__name__].append(event)

        # Process events by type
        for event_type, event_list in events_by_type.items():
            if event_type == type(events.StreamDataReceived).__name__:
                # Filter to only StreamDataReceived events
                stream_data_events = [
                    e for e in event_list if isinstance(e, events.StreamDataReceived)
                ]
                await self._handle_stream_data_batch(stream_data_events)
            else:
                # Process other events individually
                for event in event_list:
                    await self._handle_quic_event(event)

        logger.debug(f"Processed batch of {len(self._event_batch)} events")

    async def _handle_stream_data_batch(
        self, events_list: list[events.StreamDataReceived]
    ) -> None:
        """Handle stream data events in batch for better performance."""
        # Group by stream ID
        events_by_stream: defaultdict[int, list[QuicEvent]] = defaultdict(list)
        for event in events_list:
            events_by_stream[event.stream_id].append(event)

        # Process each stream's events
        for stream_id, stream_events in events_by_stream.items():
            stream = self._get_stream_fast(stream_id)  # Use fast lookup

            if not stream:
                if self._is_incoming_stream(stream_id):
                    try:
                        stream = await self._create_inbound_stream(stream_id)
                    except QUICStreamLimitError:
                        # Reset stream if we can't handle it
                        self._quic.reset_stream(stream_id, error_code=0x04)
                        await self._transmit()
                        continue
                else:
                    logger.error(
                        f"Unexpected outbound stream {stream_id} in data event"
                    )
                    continue

            # Process all events for this stream
            for received_event in stream_events:
                if hasattr(received_event, "data"):
                    self._stats["bytes_received"] += len(received_event.data)  # type: ignore

                    if hasattr(received_event, "end_stream"):
                        await stream.handle_data_received(
                            received_event.data,  # type: ignore
                            received_event.end_stream,  # type: ignore
                        )

    async def _create_inbound_stream(self, stream_id: int) -> QUICStream:
        """Create inbound stream with proper limit checking."""
        async with self._stream_lock:
            # Double-check stream doesn't exist
            existing_stream = self._streams.get(stream_id)
            if existing_stream:
                return existing_stream

            # Check limits
            if self._inbound_stream_count >= self.MAX_INCOMING_STREAMS:
                logger.warning(f"Rejecting inbound stream {stream_id}: limit reached")
                raise QUICStreamLimitError("Too many inbound streams")

            # Acquire stream scope from resource manager if available
            stream_scope = None
            if self._resource_scope and hasattr(
                self._resource_scope, "_resource_manager"
            ):
                try:
                    stream_scope = self._resource_scope._resource_manager.open_stream(
                        peer_id=self._remote_peer_id, direction=Direction.INBOUND
                    )
                except Exception as e:
                    logger.warning(f"Failed to acquire stream scope: {e}")
                    raise QUICStreamLimitError(f"Resource limit exceeded: {e}")

            # Create stream
            stream = QUICStream(
                connection=self,
                stream_id=stream_id,
                direction=StreamDirection.INBOUND,
                resource_scope=stream_scope,
                remote_addr=self._remote_addr,
            )

            self._streams[stream_id] = stream
            self._stream_cache[stream_id] = stream  # Add to cache
            self._inbound_stream_count += 1
            self._stats["streams_accepted"] += 1

            # Add to accept queue
            self._stream_accept_queue.append(stream)
            self._stream_accept_event.set()

            logger.debug(f"Created inbound stream {stream_id}")
            return stream

    async def _process_quic_events(self) -> None:
        """Process all pending QUIC events."""
        # Delegate to batched processing for better performance
        await self._process_quic_events_batched()

    async def _handle_quic_event(self, event: events.QuicEvent) -> None:
        """Handle a single QUIC event with COMPLETE event type coverage."""
        logger.debug(f"Handling QUIC event: {type(event).__name__}")
        logger.debug(f"QUIC event: {type(event).__name__}")

        try:
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
            # *** NEW: Connection ID event handlers - CRITICAL FIX ***
            elif isinstance(event, events.ConnectionIdIssued):
                await self._handle_connection_id_issued(event)
            elif isinstance(event, events.ConnectionIdRetired):
                await self._handle_connection_id_retired(event)
            # *** NEW: Additional event handlers for completeness ***
            elif isinstance(event, events.PingAcknowledged):
                await self._handle_ping_acknowledged(event)
            elif isinstance(event, events.ProtocolNegotiated):
                await self._handle_protocol_negotiated(event)
            elif isinstance(event, events.StopSendingReceived):
                await self._handle_stop_sending_received(event)
            else:
                logger.debug(f"Unhandled QUIC event type: {type(event).__name__}")
                logger.debug(f"Unhandled QUIC event: {type(event).__name__}")

        except Exception as e:
            logger.error(f"Error handling QUIC event {type(event).__name__}: {e}")

    async def _handle_connection_id_issued(
        self, event: events.ConnectionIdIssued
    ) -> None:
        """
        Handle new connection ID issued by peer.

        This is the CRITICAL missing functionality that was causing your issue!
        """
        logger.debug(f"🆔 NEW CONNECTION ID ISSUED: {event.connection_id.hex()}")
        logger.debug(f"🆔 NEW CONNECTION ID ISSUED: {event.connection_id.hex()}")

        # Add to available connection IDs
        self._available_connection_ids.add(event.connection_id)

        # If we don't have a current connection ID, use this one
        if self._current_connection_id is None:
            self._current_connection_id = event.connection_id
            logger.debug(
                f"🆔 Set current connection ID to: {event.connection_id.hex()}"
            )
            logger.debug(
                f"🆔 Set current connection ID to: {event.connection_id.hex()}"
            )

        # Update statistics
        self._stats["connection_ids_issued"] += 1

        logger.debug(f"Available connection IDs: {len(self._available_connection_ids)}")
        logger.debug(f"Available connection IDs: {len(self._available_connection_ids)}")

    async def _handle_connection_id_retired(
        self, event: events.ConnectionIdRetired
    ) -> None:
        """
        Handle connection ID retirement.

        This handles when the peer tells us to stop using a connection ID.
        """
        logger.debug(f"🗑️ CONNECTION ID RETIRED: {event.connection_id.hex()}")

        # Remove from available IDs and add to retired set
        self._available_connection_ids.discard(event.connection_id)
        self._retired_connection_ids.add(event.connection_id)

        # If this was our current connection ID, switch to another
        if self._current_connection_id == event.connection_id:
            if self._available_connection_ids:
                self._current_connection_id = next(iter(self._available_connection_ids))
                if self._current_connection_id:
                    logger.debug(
                        "Switching to new connection ID: "
                        f"{self._current_connection_id.hex()}"
                    )
                    self._stats["connection_id_changes"] += 1
                else:
                    logger.warning("⚠️ No available connection IDs after retirement!")
            else:
                self._current_connection_id = None
                logger.warning("⚠️ No available connection IDs after retirement!")

        # Update statistics
        self._stats["connection_ids_retired"] += 1

    async def _handle_ping_acknowledged(self, event: events.PingAcknowledged) -> None:
        """Handle ping acknowledgment."""
        logger.debug(f"Ping acknowledged: uid={event.uid}")

    async def _handle_protocol_negotiated(
        self, event: events.ProtocolNegotiated
    ) -> None:
        """Handle protocol negotiation completion."""
        logger.debug(f"Protocol negotiated: {event.alpn_protocol}")

    async def _handle_stop_sending_received(
        self, event: events.StopSendingReceived
    ) -> None:
        """Handle stop sending request from peer."""
        logger.debug(
            "Stop sending received: "
            f"stream_id={event.stream_id}, error_code={event.error_code}"
        )

        # Use fast lookup
        stream = self._get_stream_fast(event.stream_id)
        if stream:
            # Handle stop sending on the stream if method exists
            await stream.handle_stop_sending(event.error_code)

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

        logger.debug("✅ Setting connected event")
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
        self._stream_cache.clear()  # Clear cache too
        self._closed = True
        self._closed_event.set()

        self._stream_accept_event.set()
        logger.debug(f"Woke up pending accept_stream() calls, {id(self)}")

        await self._notify_parent_of_termination()

    async def _handle_stream_data(self, event: events.StreamDataReceived) -> None:
        """Handle stream data events - create streams and add to accept queue."""
        stream_id = event.stream_id
        self._stats["bytes_received"] += len(event.data)

        try:
            # Use fast lookup
            stream = self._get_stream_fast(stream_id)

            if not stream:
                if self._is_incoming_stream(stream_id):
                    logger.debug(f"Creating new incoming stream {stream_id}")
                    stream = await self._create_inbound_stream(stream_id)
                else:
                    logger.error(
                        f"Unexpected outbound stream {stream_id} in data event"
                    )
                    return

            await stream.handle_data_received(event.data, event.end_stream)

        except Exception as e:
            logger.error(f"Error handling stream data for stream {stream_id}: {e}")
            logger.debug(f"❌ STREAM_DATA: Error: {e}")

    async def _get_or_create_stream(self, stream_id: int) -> QUICStream:
        """Get existing stream or create new inbound stream."""
        # Use fast lookup
        stream = self._get_stream_fast(stream_id)
        if stream:
            return stream

        # Check if this is an incoming stream
        is_incoming = self._is_incoming_stream(stream_id)

        if not is_incoming:
            # This shouldn't happen - outbound streams should be created by open_stream
            raise QUICStreamError(
                f"Received data for unknown outbound stream {stream_id}"
            )

        # Create new inbound stream
        return await self._create_inbound_stream(stream_id)

    def _is_incoming_stream(self, stream_id: int) -> bool:
        """
        Determine if a stream ID represents an incoming stream.

        For bidirectional streams:
        - Even IDs are client-initiated
        - Odd IDs are server-initiated
        """
        if self._is_initiator:
            # We're the client, so odd stream IDs are incoming
            return stream_id % 2 == 1
        else:
            # We're the server, so even stream IDs are incoming
            return stream_id % 2 == 0

    async def _handle_stream_reset(self, event: events.StreamReset) -> None:
        """Stream reset handling."""
        stream_id = event.stream_id
        self._stats["streams_reset"] += 1

        # Use fast lookup
        stream = self._get_stream_fast(stream_id)
        if stream:
            try:
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
        """Handle datagram frame (if using QUIC datagrams)."""
        logger.debug(f"Datagram frame received: size={len(event.data)}")
        # For now, just log. Could be extended for custom datagram handling

    async def _handle_timer_events(self) -> None:
        """Handle QUIC timer events."""
        timer = self._quic.get_timer()
        if timer is not None:
            now = time.time()
            if timer <= now:
                self._quic.handle_timer(now=now)

    # Network transmission

    async def _transmit(self) -> None:
        """Transmit pending QUIC packets using available socket."""
        sock = self._socket
        if not sock:
            logger.debug("No socket to transmit")
            return

        try:
            current_time = time.time()
            datagrams = self._quic.datagrams_to_send(now=current_time)

            # Batch stats updates
            packet_count = 0
            total_bytes = 0

            for data, addr in datagrams:
                await sock.sendto(data, addr)
                packet_count += 1
                total_bytes += len(data)

            # Update stats in batch
            if packet_count > 0:
                self._stats["packets_sent"] += packet_count
                self._stats["bytes_sent"] += total_bytes

        except Exception as e:
            logger.error(f"Transmission error: {e}")
            await self._handle_connection_error(e)

    # Additional methods for stream data processing
    async def _process_quic_event(self, event: events.QuicEvent) -> None:
        """Process a single QUIC event."""
        await self._handle_quic_event(event)

    async def _transmit_pending_data(self) -> None:
        """Transmit any pending data."""
        await self._transmit()

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
        logger.debug(f"Closing QUIC connection to {self._remote_peer_id}")

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

            if self.on_close:
                await self.on_close()

            # Close QUIC connection
            self._quic.close()

            if self._socket:
                await self._transmit()  # Send close frames

            # Close socket
            if self._socket and self._owns_socket:
                self._socket.close()
                self._socket = None

            self._streams.clear()
            self._stream_cache.clear()  # Clear cache
            self._closed_event.set()

            logger.debug(f"QUIC connection to {self._remote_peer_id} closed")

            # Release resource scope if present
            try:
                scope = getattr(self, "_resource_scope", None)
                if scope is not None and hasattr(scope, "done"):
                    scope.done()
                    self._resource_scope = None
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error during connection close: {e}")

    async def _notify_parent_of_termination(self) -> None:
        """
        Notify the parent listener/transport to remove this connection from tracking.

        This ensures that terminated connections are cleaned up from the
        'established connections' list.
        """
        try:
            if self._transport:
                await self._transport._cleanup_terminated_connection(self)
                logger.debug("Notified transport of connection termination")
                return

            for listener in self._transport._listeners:
                try:
                    await listener._remove_connection_by_object(self)
                    logger.debug(
                        "Found and notified listener of connection termination"
                    )
                    return
                except Exception:
                    continue

            # Method 4: Use connection ID if we have one (most reliable)
            if self._current_connection_id:
                await self._cleanup_by_connection_id(self._current_connection_id)
                return

            logger.warning(
                "Could not notify parent of connection termination - no"
                f" parent reference found for conn host {self._quic.host_cid.hex()}"
            )

        except Exception as e:
            logger.error(f"Error notifying parent of connection termination: {e}")

    async def _cleanup_by_connection_id(self, connection_id: bytes) -> None:
        """Cleanup using connection ID as a fallback method."""
        try:
            for listener in self._transport._listeners:
                for tracked_cid, tracked_conn in list(listener._connections.items()):
                    if tracked_conn is self:
                        await listener._remove_connection(tracked_cid)
                        logger.debug(f"Removed connection {tracked_cid.hex()}")
                        return

            logger.debug("Fallback cleanup by connection ID completed")
        except Exception as e:
            logger.error(f"Error in fallback cleanup: {e}")

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
        Read data from the stream.

        Args:
            n: Maximum number of bytes to read. -1 means read all available.

        Returns:
            Data bytes read from the stream.

        Raises:
            QUICStreamClosedError: If stream is closed for reading.
            QUICStreamResetError: If stream was reset.
            QUICStreamTimeoutError: If read timeout occurs.

        """
        # It's here for interface compatibility but should not be used
        raise NotImplementedError(
            "Use streams for reading data from QUIC connections. "
            "Call accept_stream() or open_stream() instead."
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
            "cache_size": len(
                self._stream_cache
            ),  # Include cache metrics for monitoring
        }

    def get_active_streams(self) -> list[QUICStream]:
        """Get list of active streams."""
        return [stream for stream in self._streams.values() if not stream.is_closed()]

    def get_streams_by_protocol(self, protocol: str) -> list[QUICStream]:
        """Get streams filtered by protocol."""
        return [
            stream
            for stream in self._streams.values()
            if hasattr(stream, "protocol")
            and stream.protocol == protocol
            and not stream.is_closed()
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
        current_cid: str | None = (
            self._current_connection_id.hex() if self._current_connection_id else None
        )
        return (
            f"QUICConnection(peer={self._remote_peer_id}, "
            f"addr={self._remote_addr}, "
            f"initiator={self._is_initiator}, "
            f"verified={self._peer_verified}, "
            f"established={self._established}, "
            f"streams={len(self._streams)}, "
            f"current_cid={current_cid})"
        )

    def __str__(self) -> str:
        return f"QUICConnection({self._remote_peer_id})"
