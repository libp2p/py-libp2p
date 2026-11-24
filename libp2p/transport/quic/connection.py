"""
QUIC Connection implementation.
Manages bidirectional QUIC connections with integrated stream multiplexing.
"""

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
import logging
import os
import socket
import time
from typing import TYPE_CHECKING, Any, Optional

from aioquic.quic import events
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent
from cryptography import x509
import multiaddr
from multiaddr import Multiaddr
import trio

from libp2p.abc import ConnectionType, IMuxedConn, IRawConnection
from libp2p.custom_types import TQUICStreamHandlerFn
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction
from libp2p.stream_muxer.exceptions import MuxedConnUnavailable

from . import aioquic_compat
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
    from .listener import QUICListener
    from .security import QUICTLSConfigManager
    from .transport import QUICTransport

logger = logging.getLogger(__name__)

# Event-loop cadence for QUIC connections.  The sans-IO aioquic core needs
# periodic pumping for timers and queued events, but the old fixed 1-10ms
# polling (and a zero-sleep yield while events were being processed) made
# every connection — including fully idle ones and in-flight handshakes —
# Event-loop pacing: idle connections sleep up to _IDLE_POLL_INTERVAL (waking
# sooner when aioquic reports a pending timer that includes pacing). Active
# connections yield cooperatively; avoid a fixed 1ms sleep after every batch
# (that inflated ACK→send RTT), but use a short _ACTIVE_POLL_INTERVAL when
# spinning without a sooner timer so peer packet tasks are not starved.
_IDLE_POLL_INTERVAL = 2.0  # seconds: max idle gap between event-loop polls
_ACTIVE_POLL_INTERVAL = 0.0001  # seconds: yield gap when actively draining
# Grace period before an aioquic stream that no longer has a py-libp2p wrapper
# is discarded unconditionally. Long enough for a healthy peer to answer our
# FIN/STOP_SENDING, short enough to bound the memory of a stuck stream.
_ABANDONED_STREAM_TIMEOUT = 120.0


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
        listener: "QUICListener | None" = None,
        listener_connection_id: bytes | None = None,
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
            listener: Owning listener for server-side connections (enables O(1)
                Connection ID registration).
            listener_connection_id: Listener's primary Connection ID for this
                connection (used as the base CID when registering new CIDs).

        """
        self._quic = quic_connection
        self._remote_addr = remote_addr
        self._remote_peer_id = remote_peer_id
        self._local_peer_id = local_peer_id
        self.peer_id = remote_peer_id or local_peer_id
        # Derive initiator/client role from aioquic configuration when available.
        # Only trust `is_client` when it's a real bool
        #  (mocks may return truthy objects).
        is_client = getattr(
            getattr(quic_connection, "configuration", None), "is_client", None
        )
        self._is_initiator = is_client if isinstance(is_client, bool) else is_initiator
        self._maddr = maddr
        self._transport = transport
        self._security_manager = security_manager
        self._resource_scope = resource_scope
        # Owning listener context (server-side). Used to register newly-issued
        # Connection IDs in O(1) for correct packet routing.
        self._listener: "QUICListener | None" = listener
        self._listener_connection_id: bytes | None = listener_connection_id

        # Trio networking - socket may be provided by listener
        self._socket = listener_socket if listener_socket else None
        self._owns_socket = listener_socket is None
        self._connected_event = trio.Event()
        self._closed_event = trio.Event()

        self._streams: dict[int, QUICStream] = {}
        self._stream_cache: dict[int, QUICStream] = {}  # Cache for frequent lookups
        self._recently_closed_streams: deque[int] = deque(maxlen=128)
        # aioquic streams whose wrapper was removed, keyed by the monotonic
        # time of removal. aioquic only discards a stream once both halves are
        # finished, so wrappers must not be dropped while a half is still open.
        self._abandoned_streams: dict[int, float] = {}
        self._credit_waiter: trio.Event | None = None
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

        # Negotiation semaphores to limit concurrent multiselect negotiations
        # Separate semaphores for client (outbound) and server (inbound) to prevent
        # deadlocks where client holds all slots and server can't respond.
        # This prevents overwhelming the connection with too many simultaneous
        # negotiations, which can cause timeouts under high concurrency.
        # Limit is configurable via transport config to allow tuning for
        # different use cases. The separate client/server semaphores prevent
        # deadlocks while maintaining reasonable resource usage. In CI/CD
        # environments with limited resources, this helps prevent contention.
        # Get negotiation limit from config, defaulting to 5 if not available
        # or if it's a Mock object (in tests)
        negotiation_limit = getattr(
            self._transport._config, "NEGOTIATION_SEMAPHORE_LIMIT", 5
        )
        # Ensure it's an int (handles Mock objects in tests)
        if not isinstance(negotiation_limit, int):
            negotiation_limit = 5
        self._client_negotiation_semaphore = trio.Semaphore(negotiation_limit)
        self._server_negotiation_semaphore = trio.Semaphore(negotiation_limit)
        # Keep _negotiation_semaphore for backward compatibility (maps to client)
        self._negotiation_semaphore = self._client_negotiation_semaphore

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
        self._cancel_scope: trio.CancelScope = trio.CancelScope()
        self._task_cancel_scopes: list[trio.CancelScope] = []
        self._event_processing_task: Any | None = None
        self.on_close: Callable[[], Awaitable[None]] | None = None
        self.event_started = trio.Event()
        self._activity_event: trio.Event = trio.Event()
        self._last_cc_stats_log: float = 0.0

        self._available_connection_ids: set[bytes] = set()
        self._current_connection_id: bytes | None = None
        self._retired_connection_ids: set[bytes] = set()
        self._cid_history_limit = 128
        self._retired_connection_id_order: deque[bytes] = deque()
        self._connection_id_sequence_numbers: set[int] = set()
        # Sequence number counter for tracking Connection IDs (inspired by quinn)
        # Starts at 0 for initial CID, increments for each new CID issued
        self._connection_id_sequence_counter: int = 0

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
        self.STREAM_OPEN_TIMEOUT = self._transport._config.STREAM_OPEN_TIMEOUT

        # Bound the inbound accept backlog. Closed streams stay queued so a
        # late acceptor can still drain unread reply data, and nothing else
        # limits how many (or how many buffered bytes) a peer can pile up.
        self.MAX_QUEUED_INBOUND_STREAMS = 128
        self.MAX_QUEUED_INBOUND_BYTES = 4 * 1024 * 1024

        # Performance monitoring thresholds
        self.SLOW_NOTIFICATION_THRESHOLD_SECONDS = 0.01  # 10ms

        # Keep-alive: send PING frames on idle connections (kubo parity:
        # quic-go sends a PING every 15 s and closes connections idle for 30 s).
        keepalive_enabled = getattr(self._transport._config, "KEEPALIVE_ENABLED", True)
        if not isinstance(keepalive_enabled, bool):
            keepalive_enabled = True
        keepalive_interval = getattr(
            self._transport._config, "KEEPALIVE_INTERVAL", 15.0
        )
        if not isinstance(keepalive_interval, (int, float)):
            keepalive_interval = 15.0
        self._keepalive_interval = (
            float(keepalive_interval) if keepalive_enabled else 0.0
        )
        self._last_transmit_time = time.time()
        self._ping_uid_counter = 0

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
            "keepalive_pings_sent": 0,
        }

        logger.debug(
            f"Created QUIC connection to {self._remote_peer_id} "
            f"(initiator: {self._is_initiator}, addr: {self._remote_addr}, "
            f"security: {self._security_manager is not None})"
        )

    def set_listener_context(
        self, listener: "QUICListener | None", listener_connection_id: bytes | None
    ) -> None:
        """
        Set owning listener context for O(1) Connection ID registration.

        For server-side connections, the listener is responsible for packet routing.
        """
        self._listener = listener
        self._listener_connection_id = listener_connection_id

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
            "recent_cid_history_limit": self._cid_history_limit,
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
        Signal that this connection is ready for use by the Swarm.

        This method implements the IMuxedConn.start() interface and is the
        EXCLUSIVE responsibility of Swarm.add_conn(). All raw transport
        setup (handshake, background tasks, peer verification) is handled
        by connect(), which sets _started=True when the connection is
        operational. start() then completes the Swarm lifecycle by setting
        event_started, which add_conn() waits on.
        """
        if self.event_started.is_set():
            logger.debug("Connection already signalled to Swarm")
            return

        if self._closed:
            logger.debug("Cannot start a closed connection (shutdown race), silencing.")
            self.event_started.set()
            return

        self._started = True
        logger.debug(f"QUIC connection ready for Swarm: {self._remote_peer_id}")
        self.event_started.set()

    async def _initiate_connection(self) -> None:
        """Initiate client-side connection, reusing listener socket if available."""
        try:
            with QUICErrorContext("connection_initiation", "connection"):
                if not self._socket:
                    logger.debug("Creating new socket for outbound connection")
                    family = (
                        socket.AF_INET6
                        if ":" in self._remote_addr[0]
                        else socket.AF_INET
                    )
                    self._socket = trio.socket.socket(
                        family=family, type=socket.SOCK_DGRAM
                    )

                bind_addr = "::" if family == socket.AF_INET6 else "0.0.0.0"
                await self._socket.bind((bind_addr, 0))

                self._quic.connect(self._remote_addr, now=time.time())

                # Send initial packet(s)
                await self._transmit()

                logger.debug(f"Initiated QUIC connection to {self._remote_addr}")

        except BaseException as e:
            if self._socket and self._owns_socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            if isinstance(e, Exception) and not isinstance(e, trio.Cancelled):
                logger.error(f"Failed to initiate connection: {e}")
                raise QUICConnectionError(f"Connection initiation failed: {e}") from e
            raise

    async def connect(self, nursery: trio.Nursery) -> None:
        """
        Establish the QUIC connection using trio nursery for background tasks.

        This method handles all raw transport setup: physical connection
        initiation (for clients), background event-loop tasks, TLS handshake
        completion, and peer identity verification. It intentionally does NOT
        call start() or set event_started — those are exclusively owned by
        Swarm.add_conn() to maintain a uniform lifecycle contract across all
        transports.

        Args:
            nursery: Trio nursery for managing connection background tasks

        """
        if self._closed:
            raise QUICConnectionClosedError("Connection is closed")

        self._nursery = nursery

        try:
            with QUICErrorContext("connection_establishment", "connection"):
                # Raw transport setup — inlined directly instead of delegating
                # to start(), so that start() remains a pure Swarm signal.
                if self._is_initiator:
                    # Client: initiate the UDP handshake
                    await self._initiate_connection()
                else:
                    # Server: already physically connected via the listener socket
                    self._established = True
                    self._connected_event.set()

                # Start background event processing
                if not self._background_tasks_started:
                    await self._start_background_tasks()

                # Wait for TLS handshake completion with timeout
                with trio.move_on_after(
                    self.CONNECTION_HANDSHAKE_TIMEOUT
                ) as cancel_scope:
                    await self._connected_event.wait()

                if cancel_scope.cancelled_caught:
                    raise QUICConnectionTimeoutError(
                        "Connection handshake timed out after "
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
                self._started = True  # Connection is fully set up and operational
                logger.debug(f"QUIC connection established with {self._remote_peer_id}")
                # NOTE: event_started is NOT set here. Swarm.add_conn() calls
                # start() which is the sole setter of event_started for the
                # Swarm lifecycle contract.

        except BaseException as e:
            if not isinstance(e, trio.Cancelled):
                logger.error(f"Failed to establish connection: {e}")
            with trio.CancelScope() as close_scope:
                close_scope.shield = True
                await self.close()
            raise

    async def _start_background_tasks(self) -> None:
        """Start background tasks for connection management."""
        if self._background_tasks_started or not self._nursery:
            return

        self._background_tasks_started = True

        async def _run_scoped(fn: Callable[[], Awaitable[None]]) -> None:
            scope = trio.CancelScope()
            self._task_cancel_scopes.append(scope)
            try:
                with scope:
                    await fn()
            except trio.Cancelled:
                pass
            except Exception as e:
                logger.debug(f"QUIC background task exited: {e}")
            finally:
                if scope in self._task_cancel_scopes:
                    self._task_cancel_scopes.remove(scope)

        if self._is_initiator:
            self._nursery.start_soon(_run_scoped, self._client_packet_receiver)

        self._nursery.start_soon(_run_scoped, self._event_processing_loop)
        self._nursery.start_soon(_run_scoped, self._periodic_maintenance)

        logger.debug("Started background tasks for QUIC connection")

    def _signal_activity(self) -> None:
        """Signal that new datagram or stream activity occurred."""
        if self._credit_waiter is not None and (
            self._closed
            or self._next_stream_id // 4 < self._quic._remote_max_streams_bidi
        ):
            self._credit_waiter.set()
            self._credit_waiter = None
        if hasattr(self, "_activity_event") and not self._activity_event.is_set():
            self._activity_event.set()

    async def _event_processing_loop(self) -> None:
        """Main event processing loop for the connection."""
        logger.debug(
            f"Started QUIC event processing loop for connection id: {id(self)} "
            f"and local peer id {str(self.local_peer_id())}"
        )

        try:
            while not self._closed:
                # Batch process events - returns True if events were processed
                events_processed = await self._process_quic_events_batched()

                # Handle timer events
                await self._handle_timer_events()

                # Transmit any pending data
                await self._transmit()
                self._maybe_log_congestion_stats()

                if events_processed:
                    # Cooperative yield without a fixed 1ms RTT tax.
                    await trio.sleep(_ACTIVE_POLL_INTERVAL)
                    continue

                # Calculate next sleep duration based on pending aioquic timer
                # (includes pacing delay). Idle connections sleep up to
                # _IDLE_POLL_INTERVAL; wake earlier on datagram activity.
                timer = self._quic.get_timer()
                now = time.time()
                if timer is not None:
                    delay = min(max(0.0, timer - now), _IDLE_POLL_INTERVAL)
                else:
                    delay = _IDLE_POLL_INTERVAL

                if delay > 0.0:
                    with trio.move_on_after(delay):
                        await self._activity_event.wait()
                    if self._activity_event.is_set():
                        self._activity_event = trio.Event()
                else:
                    # Timer already due; cooperative yield, then drain again.
                    await trio.sleep(_ACTIVE_POLL_INTERVAL)

        except Exception as e:
            if not self._closed:
                logger.error(f"Error in event processing loop: {e}")
                await self._handle_connection_error(e)
        finally:
            logger.debug("QUIC event processing loop finished")

    async def _periodic_maintenance(self) -> None:
        """Perform periodic connection maintenance."""
        maintenance_count = 0
        try:
            while not self._closed:
                maintenance_count += 1

                # Update connection statistics
                self._update_stats()

                # Check for idle streams that can be cleaned up
                await self._cleanup_idle_streams()

                # Check for orphaned streams (active but no activity for a long time)
                await self._cleanup_orphaned_streams()

                # Discard streams whose wrapper is gone but whose aioquic half
                # was never answered by the peer.
                await self._cleanup_abandoned_quic_streams()

                if logger.isEnabledFor(logging.DEBUG):
                    cid_stats = self.get_connection_id_stats()
                    logger.debug(f"Connection ID stats: {cid_stats}")

                # Clean cache periodically
                await self._cleanup_cache()

                # Periodically force glibc to release free memory back to the
                # OS. Without this, malloc fragmentation from OpenSSL
                # encrypt/decrypt cycles causes RSS to grow indefinitely even
                # though logical objects are properly freed.
                if maintenance_count % 5 == 0:
                    try:
                        import ctypes

                        libc = ctypes.CDLL("libc.so.6")
                        libc.malloc_trim(0)
                    except Exception:
                        pass

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
                    self._signal_activity()

                    # Batch process events
                    await self._process_quic_events_batched()

                    # Send any response packets
                    await self._transmit()

                except (trio.ClosedResourceError, OSError):
                    logger.debug("Client socket closed")
                    break
                except Exception as e:
                    if self._closed or not self._socket:
                        break
                    logger.error(f"Error receiving client packet: {e}")
                    await trio.sleep(0.01)

        except trio.Cancelled:
            logger.debug("Client packet receiver cancelled")
            raise
        finally:
            logger.debug("Client packet receiver terminated")
            # If the receiver exits while connection is not closed, trigger
            # cleanup. This handles the silent socket death case where OSError
            # breaks the loop but nobody calls close().
            if not self._closed:
                logger.warning(
                    "Client packet receiver exited unexpectedly for peer %s, "
                    "triggering connection cleanup",
                    self._remote_peer_id,
                )
                try:
                    await self._handle_connection_error(
                        OSError("Packet receiver terminated unexpectedly")
                    )
                except Exception as e:
                    logger.debug(f"Error triggering cleanup from receiver exit: {e}")

    # Security and identity methods

    async def _verify_peer_identity_with_security(self) -> ID | None:
        """
        Verify peer identity using integrated security manager.

        Raises:
            QUICPeerVerificationError: If peer verification fails

        """
        if not self._security_manager:
            logger.debug("No security manager available for peer verification")
            return None

        try:
            if not self._peer_certificate:
                # Inbound (server-side) connections MUST present a peer
                # certificate so the remote libp2p identity can be established.
                # Accepting a connection without one would allow unauthenticated
                # peers to reach the application callback — the libp2p QUIC
                # trust boundary requires verified peer identity before promotion.
                if not self._is_initiator:
                    raise QUICPeerVerificationError(
                        "Inbound QUIC connection has no peer certificate: "
                        "remote peer identity cannot be established. "
                        "Connection rejected."
                    )
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
                    f"got {verified_peer_id}"
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

    async def get_peer_certificate(self) -> x509.Certificate | None:
        """
        Get the peer's TLS certificate.

        Returns:
            The peer's X.509 certificate, or None if not available

        """
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
                info["tls_debug"] = tls_info
            else:
                info["tls_debug"] = {"tls_context_available": False}

        except Exception as e:
            info["tls_debug"] = {"error": str(e)}

        return info

    # Stream management methods (IMuxedConn interface)

    async def open_stream(self, timeout: float | None = None) -> QUICStream:
        """
        Open a new outbound stream

        Args:
            timeout: Timeout for stream creation
                (defaults to STREAM_OPEN_TIMEOUT from config)

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

        # Use config timeout if not specified
        if timeout is None:
            timeout = self.STREAM_OPEN_TIMEOUT

        # Use single lock for all stream operations
        with trio.move_on_after(timeout):
            while True:
                async with self._stream_lock:
                    if self._closed:
                        raise QUICConnectionClosedError("Connection is closed")
                    if self._outbound_stream_count >= self.MAX_OUTGOING_STREAMS:
                        raise QUICStreamLimitError("Maximum outbound streams reached")
                    # MAX_STREAMS is cumulative. Even an empty local registry
                    # cannot open a stream whose ordinal exceeds peer credit.
                    if self._next_stream_id // 4 < self._quic._remote_max_streams_bidi:
                        return self._allocate_outbound_stream()
                    if self._credit_waiter is None:
                        self._credit_waiter = trio.Event()
                    waiter = self._credit_waiter
                await waiter.wait()

        raise QUICStreamTimeoutError(f"Stream creation timed out after {timeout}s")

    def _allocate_outbound_stream(self) -> QUICStream:
        """Allocate an admitted stream while holding the stream lock."""
        # Generate next stream ID
        stream_id = self._next_stream_id

        # Acquire stream scope from resource manager if available
        stream_scope = None
        if self._resource_scope and hasattr(self._resource_scope, "_resource_manager"):
            try:
                stream_scope = self._resource_scope._resource_manager.open_stream(
                    peer_id=self._remote_peer_id,
                    direction=Direction.OUTBOUND,
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

        self._next_stream_id += 4
        self._streams[stream_id] = stream
        self._stream_cache[stream_id] = stream  # Add to cache

        self._outbound_stream_count += 1
        self._stats["streams_opened"] += 1

        logger.debug(f"Opened outbound QUIC stream {stream_id}")
        return stream

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
                    if stream.is_reset() is True:
                        # Defensive: a reset stream must never be handed to
                        # the application as if it were a live stream.
                        logger.debug(
                            "Skipping reset inbound stream %s",
                            stream.stream_id,
                        )
                        continue
                    logger.debug(f"Accepted inbound stream {stream.stream_id}")
                    return stream

                # If the event is already set but the queue is empty, reset it to avoid
                # a busy loop that can starve the QUIC event loop under load.
                if self._stream_accept_event.is_set():
                    self._stream_accept_event = trio.Event()
                    continue

                accept_event = self._stream_accept_event

            if self._closed:
                raise MuxedConnUnavailable("Connection closed while accepting stream")

            # Wait for new streams indefinitely
            await accept_event.wait()

        raise QUICConnectionError("Error occurred while waiting to accept stream")

    def set_stream_handler(self, handler_function: TQUICStreamHandlerFn) -> None:
        """
        Set handler for incoming streams.

        Args:
            handler_function: Function to handle new incoming streams

        """
        self._stream_handler = handler_function
        logger.debug("Set stream handler for incoming streams")

    def _discard_pending_stream(self, stream_id: int) -> bool:
        """
        Unlink a terminated stream from the pending accept queue.

        A reset/aborted inbound stream can be removed from ``_streams`` and
        ``_stream_cache`` while still waiting in ``_stream_accept_queue``.
        The queue then retains the closed stream object (and its buffers)
        until the consumer drains it. Terminal streams can never be accepted
        usefully, so drop them eagerly. Gracefully FIN-closed streams are
        deliberately kept: they may still hold unread reply data.
        """
        queue = self._stream_accept_queue
        for index, queued in enumerate(queue):
            if queued._stream_id == stream_id:
                del queue[index]
                return True
        return False

    async def _release_dropped_queued_stream(self, stream: QUICStream) -> None:
        """Release a queued inbound stream that overflowed the accept backlog."""
        stream_id = int(stream._stream_id)
        # Release the bytes before reset can yield to network I/O. Reset also
        # releases the resource scope and prevents later batched events from
        # refilling a wrapper that no longer belongs to the accept queue.
        stream._receive_buffer.clear()
        self._stats["inbound_streams_dropped"] = (
            self._stats.get("inbound_streams_dropped", 0) + 1
        )
        await stream.reset()
        # Already-cleaned FIN wrappers no longer call _remove_stream during
        # reset, but their native halves may still need retirement.
        self._abandon_quic_stream(stream_id)
        logger.warning(
            "Dropped queued inbound stream %s: accept backlog exceeded", stream_id
        )

    async def _enforce_accept_queue_bounds(self) -> None:
        """
        Keep the inbound accept backlog bounded independently of wrappers.

        A stream whose wrapper was cleaned up (FIN, then STOP_SENDING) stays
        queued so a late acceptor can drain remaining data, but the queue had
        no entry or byte limit: a peer that opens streams the application
        never accepts could pin unbounded buffers and resource scopes. Drop
        the oldest entries first. Recheck after data delivery as well as queue
        insertion: an already-queued stream can grow without another insertion.
        """
        # Cancellation after buffering data must not skip the budget check or
        # strand the resources of an entry already removed from the queue.
        with trio.CancelScope(shield=True):
            queue = self._stream_accept_queue
            while queue:
                buffered = sum(len(stream._receive_buffer) for stream in queue)
                if (
                    len(queue) <= self.MAX_QUEUED_INBOUND_STREAMS
                    and buffered <= self.MAX_QUEUED_INBOUND_BYTES
                ):
                    break
                await self._release_dropped_queued_stream(queue.pop(0))

    async def _deliver_stream_data(
        self, stream: QUICStream, data: bytes, end_stream: bool
    ) -> None:
        """Deliver one event and bound unread data still waiting for acceptance."""
        try:
            await stream.handle_data_received(data, end_stream)
        finally:
            await self._enforce_accept_queue_bounds()

    def _abandon_quic_stream(self, stream_id: int, error_code: int = 0) -> None:
        """
        Release an aioquic stream that py-libp2p will never wrap.

        aioquic only discards a stream from ``QuicConnection._streams`` once
        both halves report finished, and the send half finishes only when its
        FIN or RESET is acknowledged. When a late, duplicate or unexpected
        event is ignored and no wrapper is created, nothing ever closes that
        send half, so the stream and its receiver, sender and range sets stay
        reachable for the lifetime of the connection. Stopping the receive
        side and resetting the send side is what lets aioquic discard it.
        """
        quic = getattr(self, "_quic", None)
        if quic is None:
            return
        streams = getattr(quic, "_streams", None)
        if isinstance(streams, dict) and stream_id not in streams:
            # aioquic already discarded the stream, nothing to release.
            return
        for name, operation in (
            ("stop_stream", quic.stop_stream),
            ("reset_stream", quic.reset_stream),
        ):
            try:
                operation(stream_id, error_code)
            except Exception as error:
                # StreamTypeError (peer-initiated unidirectional) and
                # StreamStateError (not open yet) mean there is nothing this
                # side can close.
                logger.debug(
                    "Cannot release abandoned QUIC stream %s via %s: %s",
                    stream_id,
                    name,
                    error,
                )

    def _remove_stream(self, stream_id: int) -> None:
        """
        Remove stream from connection registry.
        Called by stream cleanup process.
        """
        if stream_id in self._streams:
            stream = self._streams.pop(stream_id)
            self._stream_cache.pop(stream_id, None)
            self._recently_closed_streams.append(stream_id)

            # The wrapper is gone, so nothing can read or write this stream any
            # more. aioquic still may be tracking it with a half open, and it
            # only discards a stream once both halves finish. Close what is left
            # open here, otherwise the stream (and its buffers) stays reachable
            # for the lifetime of the connection.
            self._release_unfinished_quic_stream(stream_id)

            # A remotely reset stream may still be queued for acceptance.
            # Leaving it there retains the closed object (and any receive
            # buffer) for as long as acceptance is paused.
            if stream.is_reset() is True:
                self._discard_pending_stream(stream_id)

            # Capture only the direction (not the stream object) to avoid
            # keeping a reference to the QUICStream (and its receive buffer)
            # alive in the closure until the task runs.
            is_outbound = stream.direction == StreamDirection.OUTBOUND

            async def update_counts() -> None:
                async with self._stream_lock:
                    if is_outbound:
                        self._outbound_stream_count = max(
                            0, self._outbound_stream_count - 1
                        )
                    else:
                        self._inbound_stream_count = max(
                            0, self._inbound_stream_count - 1
                        )
                    self._stats["streams_closed"] += 1

            if self._nursery:
                self._nursery.start_soon(update_counts)

            logger.debug(f"Removed stream {stream_id} from connection")

    def _release_unfinished_quic_stream(self, stream_id: int) -> None:
        """
        Close the aioquic halves of a stream whose wrapper was just removed.

        aioquic discards a stream from ``QuicConnection._streams`` only when
        both halves report finished, and a half finishes only when its FIN or
        RESET is acknowledged. A wrapper can be removed while one half is still
        open: a ``close_write`` that failed after the send side was reset, a
        close driven by STOP_SENDING, or a peer reset that left our send side
        untouched. Nothing owns the stream afterwards, so finish what is open.
        """
        quic = getattr(self, "_quic", None)
        streams = getattr(quic, "_streams", None)
        if not isinstance(streams, dict):
            return
        quic_stream = streams.get(stream_id)
        if quic_stream is None:
            return

        sender = getattr(quic_stream, "sender", None)
        if sender is not None and not getattr(sender, "is_finished", False):
            # A FIN or RESET already queued is retransmitted by aioquic while
            # the stream stays in its service queue. Only a send half that was
            # never closed needs a new frame.
            if (
                getattr(sender, "_buffer_fin", None) is None
                and getattr(sender, "_reset_error_code", None) is None
            ):
                try:
                    quic.send_stream_data(stream_id, b"", end_stream=True)
                except Exception as error:
                    logger.debug(
                        "Cannot finish QUIC stream %s gracefully: %s",
                        stream_id,
                        error,
                    )
                    self._abandon_quic_stream(stream_id)

        receiver = getattr(quic_stream, "receiver", None)
        if (
            receiver is not None
            and not getattr(receiver, "is_finished", False)
            and getattr(receiver, "_stop_error_code", None) is None
        ):
            try:
                quic.stop_stream(stream_id, 0)
            except Exception as error:
                logger.debug(
                    "Cannot stop receiving on QUIC stream %s: %s", stream_id, error
                )

        # aioquic drops streams it has nothing left to send for out of
        # ``_streams_queue``, so a lost STOP_SENDING/RESET is never retransmitted
        # even though its delivery callback re-arms the pending flag. Hand the
        # stream back once so those frames go out; the sweeper below force-
        # finishes anything a peer still never answers.
        queue = getattr(quic, "_streams_queue", None)
        if isinstance(queue, list) and quic_stream not in queue:
            queue.append(quic_stream)
        self._abandoned_streams.setdefault(stream_id, time.monotonic())

    async def _cleanup_abandoned_quic_streams(self) -> None:
        """
        Discard aioquic streams that no wrapper owns and that never finished.

        Healthy peers answer FIN/RESET/STOP_SENDING quickly and aioquic drops
        the stream itself. A peer that is gone, black-holed or lost the answer
        leaves the stream in ``_streams`` forever, and each one costs its
        sender, receiver and range sets. Marking both halves finished and
        letting aioquic's writer discard the stream keeps that population
        bounded without reaching into its bookkeeping.
        """
        quic = getattr(self, "_quic", None)
        streams = getattr(quic, "_streams", None)
        if not isinstance(streams, dict):
            return

        # aioquic never removes a finished stream from its blocked-direction
        # lists, so prune them even when the native registry is already empty:
        # that is exactly the state a connection with no credit reaches while
        # the blocked entries keep the finished streams alive.
        self._prune_finished_blocked_streams()

        if not streams:
            self._abandoned_streams.clear()
            return

        now = time.monotonic()
        queue = getattr(quic, "_streams_queue", None)
        owned = set(self._streams)
        for stream_id in list(streams):
            if stream_id not in owned:
                # First time this connection notices the stream has no owner.
                self._abandoned_streams.setdefault(stream_id, now)

        discarded = 0
        for stream_id, abandoned_at in list(self._abandoned_streams.items()):
            quic_stream = streams.get(stream_id)
            if quic_stream is None:
                self._abandoned_streams.pop(stream_id, None)
                continue
            if quic_stream.is_finished:
                if isinstance(queue, list) and quic_stream not in queue:
                    queue.append(quic_stream)
                continue
            if now - abandoned_at < _ABANDONED_STREAM_TIMEOUT:
                continue

            quic_stream.receiver.is_finished = True
            quic_stream.sender.is_finished = True
            if isinstance(queue, list) and quic_stream not in queue:
                queue.append(quic_stream)
            self._abandoned_streams.pop(stream_id, None)
            discarded += 1

        if discarded:
            # The streams just finished are still referenced by aioquic's
            # blocked-direction lists until the peer grants more credit.
            self._prune_finished_blocked_streams()
            logger.info(
                "Discarded %d abandoned QUIC stream(s) on connection to %s",
                discarded,
                self._remote_peer_id,
            )

    def _prune_finished_blocked_streams(self) -> int:
        """
        Drop terminal streams aioquic leaves in its blocked-direction lists.

        ``QuicConnection._get_or_create_stream_for_send`` appends every stream
        that exceeds the peer's cumulative MAX_STREAMS allowance to
        ``_streams_blocked_bidi``/``_streams_blocked_uni``.  aioquic discards a
        finished stream from ``_streams`` and ``_streams_queue`` while writing a
        packet, but removes it from the blocked list only from
        ``_unblock_streams``, which runs when the peer grants more credit.  A
        connection whose credit never advances therefore keeps every blocked
        stream that ever timed out for as long as it lives.

        Only entries that are terminal are removed: a stream finished on both
        halves (so aioquic has discarded it) or one already absent from the
        registry.  Live blocked streams and their order are preserved, because
        ``_unblock_streams`` pops them from the front by stream id.
        """
        quic = getattr(self, "_quic", None)
        streams = getattr(quic, "_streams", None)
        if not isinstance(streams, dict):
            return 0

        pruned = 0
        for attribute in ("_streams_blocked_bidi", "_streams_blocked_uni"):
            blocked = getattr(quic, attribute, None)
            if not isinstance(blocked, list) or not blocked:
                continue
            live = [
                stream
                for stream in blocked
                if not getattr(stream, "is_finished", False)
                and getattr(stream, "stream_id", None) in streams
            ]
            if len(live) != len(blocked):
                pruned += len(blocked) - len(live)
                blocked[:] = live
        if pruned:
            logger.debug(
                "Pruned %d finished QUIC stream(s) from the blocked-direction "
                "lists of the connection to %s",
                pruned,
                self._remote_peer_id,
            )
        return pruned

    # Batched event processing to reduce overhead
    async def _process_quic_events_batched(self) -> bool:
        """
        Process QUIC events in batches for better performance.

        Returns:
            True if events were processed, False if no events available

        """
        if self._event_processing_active:
            return False  # Prevent recursion

        self._event_processing_active = True
        result = False  # Default to False if no events processed

        try:
            # Periodically trim aioquic's _streams_finished set which grows
            # unboundedly (one int per completed stream, never cleaned by
            # aioquic itself). With400 connections doing 1 stream/15s,
            # this adds ~96k entries/hour (~2.7 MiB Python int objects).
            if self._quic is not None:
                finished = getattr(self._quic, "_streams_finished", None)
                if finished is not None and len(finished) > 10000:
                    # Keep only the most recent half (higher stream IDs =
                    # more recent, since IDs are monotonically increasing).
                    threshold = max(finished) - len(finished) // 2
                    finished_copy = {sid for sid in finished if sid > threshold}
                    finished.clear()
                    finished.update(finished_copy)

            current_time = time.time()
            events_processed = 0

            # Collect events into batch
            while events_processed < self._event_batch_size:
                event = self._quic.next_event()
                if event is None:
                    break

                self._event_batch.append(event)
                events_processed += 1

            # Process batch if we have events
            if self._event_batch:
                await self._process_event_batch()
                self._event_batch.clear()
                self._last_event_time = current_time
                result = True
        finally:
            self._event_processing_active = False

        return result

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
                # After _remove_stream(), late FIN-only events must not recreate
                # wrappers (inbound ghosts starve accept_stream under load).
                if self._is_fin_only_events(stream_events):
                    direction = (
                        "inbound" if self._is_incoming_stream(stream_id) else "outbound"
                    )
                    logger.debug(
                        "Ignoring late FIN on closed %s stream %s "
                        "(is_initiator=%s, quic.is_client=%s)",
                        direction,
                        stream_id,
                        self._is_initiator,
                        getattr(
                            getattr(self._quic, "configuration", None),
                            "is_client",
                            None,
                        ),
                    )
                    self._abandon_quic_stream(stream_id)
                    continue

                if self._is_incoming_stream(stream_id):
                    if stream_id in self._recently_closed_streams:
                        # Late event for a stream we already handled and
                        # closed (e.g. queued FIN/reset retransmission).
                        # Re-creating a wrapper here spawns a "ghost" inbound
                        # stream whose writes fail (aioquic may have reset the
                        # send side) and shows up as an instantly-reset
                        # negotiation.
                        logger.debug(
                            "Ignoring late event for closed inbound stream %s",
                            stream_id,
                        )
                        self._abandon_quic_stream(stream_id)
                        continue
                    if stream_id not in self._quic._streams:
                        # Late/duplicate events for a stream aioquic already
                        # discarded (e.g. queued FIN after the stream finished
                        # and was GC'd). Re-creating a wrapper here spawns a
                        # "ghost" inbound stream whose writes fail with
                        # "Cannot send data on unknown peer-initiated stream"
                        # and shows up as an instantly-reset negotiation.
                        logger.debug(
                            "Ignoring late event for discarded inbound stream %s "
                            "(aioquic no longer tracks it, %d streams left)",
                            stream_id,
                            len(self._quic._streams),
                        )
                        continue
                    try:
                        stream = await self._create_inbound_stream(stream_id)
                    except QUICStreamLimitError:
                        # _create_inbound_stream() already stopped/reset the
                        # aioquic stream it refused; just push the frames out.
                        await self._transmit()
                        continue
                else:
                    is_client = getattr(
                        getattr(self._quic, "configuration", None), "is_client", None
                    )
                    parity = "even" if stream_id % 2 == 0 else "odd"
                    logger.error(
                        f"Unexpected outbound stream {stream_id} in data event "
                        f"(parity={parity}, is_initiator={self._is_initiator}, "
                        f"quic.is_client={is_client}, streams={len(self._streams)}, "
                        f"cached={stream_id in self._stream_cache})"
                    )
                    self._abandon_quic_stream(stream_id)
                    continue

            # Process all events for this stream
            for received_event in stream_events:
                if hasattr(received_event, "data"):
                    self._stats["bytes_received"] += len(received_event.data)  # type: ignore

                    if hasattr(received_event, "end_stream"):
                        await self._deliver_stream_data(
                            stream,
                            received_event.data,  # type: ignore
                            received_event.end_stream,  # type: ignore
                        )

    async def _create_inbound_stream(self, stream_id: int) -> QUICStream:
        """Create inbound stream with proper limit checking."""
        if stream_id in self._recently_closed_streams:
            # Late event for a stream we already handled and closed (e.g.
            # queued FIN/reset retransmission). Re-creating a wrapper here
            # spawns a "ghost" inbound stream whose writes fail - aioquic may
            # have already reset the send side ("cannot call write() after
            # reset()") or dropped the stream entirely.
            logger.debug("Ignoring late event for closed inbound stream %s", stream_id)
            self._abandon_quic_stream(stream_id)
            raise QUICStreamError(f"Closed inbound stream {stream_id}")

        quic_streams = getattr(self._quic, "_streams", None)
        if isinstance(quic_streams, dict) and stream_id not in quic_streams:
            # Late event for an already-discarded stream (see
            # _handle_stream_data_batch): aioquic no longer tracks it, so any
            # wrapper is a ghost whose writes fail with "Cannot send data on
            # unknown peer-initiated stream".
            logger.debug(
                "Ignoring late event for discarded inbound stream %s "
                "(aioquic no longer tracks it, %d streams left)",
                stream_id,
                len(quic_streams),
            )
            raise QUICStreamError(f"Discarded inbound stream {stream_id}")

        async with self._stream_lock:
            # Double-check stream doesn't exist
            existing_stream = self._streams.get(stream_id)
            if existing_stream:
                return existing_stream

            # Check limits
            if self._inbound_stream_count >= self.MAX_INCOMING_STREAMS:
                logger.warning(f"Rejecting inbound stream {stream_id}: limit reached")
                # The peer still holds this stream open. Refusing it without
                # stopping the receive side and resetting the send side leaves
                # an aioquic stream that nothing owns and that aioquic can
                # never discard (same defect as the ignored-event paths).
                self._abandon_quic_stream(stream_id)
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
                    self._abandon_quic_stream(stream_id)
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

        # Eviction can run close callbacks; do not hold the stream lock across
        # cleanup, since those callbacks may themselves access the connection.
        await self._enforce_accept_queue_bounds()
        logger.debug(f"Created inbound stream {stream_id}")
        return stream

    async def _process_quic_events(self) -> None:
        """Process all pending QUIC events."""
        # Delegate to batched processing for better performance
        await self._process_quic_events_batched()

    async def _handle_quic_event(self, event: events.QuicEvent) -> None:
        """
        Handle a single QUIC event with complete event type coverage.

        NOTE: This is called by the connection's event loop for established connections.
        For pending connections, the listener's _process_quic_events handles events
        until the connection is promoted. This separation prevents double-processing
        of events.
        """
        logger.debug(f"Handling QUIC event: {type(event).__name__}")

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
            # Connection ID event handlers - critical for proper packet routing
            elif isinstance(event, events.ConnectionIdIssued):
                await self._handle_connection_id_issued(event)
            elif isinstance(event, events.ConnectionIdRetired):
                await self._handle_connection_id_retired(event)
            # Additional event handlers for completeness
            elif isinstance(event, events.PingAcknowledged):
                await self._handle_ping_acknowledged(event)
            elif isinstance(event, events.ProtocolNegotiated):
                await self._handle_protocol_negotiated(event)
            elif isinstance(event, events.StopSendingReceived):
                await self._handle_stop_sending_received(event)
            else:
                logger.debug(f"Unhandled QUIC event type: {type(event).__name__}")

        except Exception as e:
            logger.error(f"Error handling QUIC event {type(event).__name__}: {e}")

    def _connection_id_sequence_number(self, connection_id: bytes) -> int:
        """
        Return the sequence number aioquic assigned to an issued Connection ID.

        ``ConnectionIdIssued`` carries only the connection ID, but aioquic
        tracks the authoritative sequence in ``_host_cids``. Falling back to a
        local counter keeps the handler working if that internal layout ever
        changes, but the native value keeps local and peer view consistent.
        """
        quic = self._quic
        host_cids = getattr(quic, "_host_cids", None)
        if not isinstance(host_cids, (list, tuple)):
            host_cids = ()
        for host_cid in host_cids:
            if getattr(host_cid, "cid", None) == connection_id:
                sequence = int(getattr(host_cid, "sequence_number", 0))
                if sequence >= self._connection_id_sequence_counter:
                    self._connection_id_sequence_counter = sequence + 1
                return sequence

        sequence = self._connection_id_sequence_counter
        self._connection_id_sequence_counter += 1
        return sequence

    async def _handle_connection_id_issued(
        self, event: events.ConnectionIdIssued
    ) -> None:
        """
        Handle new connection ID issued by peer.

        This is the CRITICAL missing functionality that was causing your issue!
        Tracks sequence numbers for proper Connection ID retirement ordering
        (inspired by quinn).
        """
        new_connection_id = event.connection_id

        # aioquic re-emits ConnectionIdIssued when a NEW_CONNECTION_ID frame is
        # retransmitted after loss, with the same connection ID. Registering it
        # again would add a second, fictitious sequence entry (and a second
        # routing alias) for a CID this connection already tracks.
        if new_connection_id in self._available_connection_ids:
            logger.debug(
                "Ignoring duplicate ConnectionIdIssued for %s",
                new_connection_id.hex()[:8],
            )
            return

        # Prefer aioquic's sequence number: that is the value the peer sees in
        # the NEW_CONNECTION_ID frame, and a retransmission must reuse it.
        sequence = self._connection_id_sequence_number(new_connection_id)
        self._connection_id_sequence_numbers.add(sequence)
        if len(self._connection_id_sequence_numbers) > self._cid_history_limit:
            self._connection_id_sequence_numbers.remove(
                min(self._connection_id_sequence_numbers)
            )

        logger.debug(
            f"NEW CONNECTION ID ISSUED: {new_connection_id.hex()} (sequence {sequence})"
        )

        # Add to available connection IDs
        self._available_connection_ids.add(new_connection_id)

        # If we don't have a current connection ID, use this one
        if self._current_connection_id is None:
            self._current_connection_id = new_connection_id
            logger.debug(f"Set current connection ID to: {new_connection_id.hex()}")

        # CRITICAL FIX: Notify listener to register this new Connection ID
        # with sequence number. This ensures packets with the new Connection ID
        # can be routed correctly
        await self._notify_listener_of_new_connection_id(new_connection_id, sequence)

        # Update statistics
        self._stats["connection_ids_issued"] += 1

        logger.debug(f"Available connection IDs: {len(self._available_connection_ids)}")

    async def _notify_listener_of_new_connection_id(
        self, new_connection_id: bytes, sequence: int
    ) -> None:
        """
        Notify the parent listener to register a new Connection ID.

        This is critical for proper packet routing when the peer issues
        new Connection IDs after the handshake completes.

        Args:
            new_connection_id: New Connection ID to register
            sequence: Sequence number for this Connection ID

        """
        notification_start = time.time()
        try:
            if self._listener and self._listener_connection_id:
                await self._listener._registry.add_connection_id(
                    new_connection_id, self._listener_connection_id, sequence
                )
                notification_duration = time.time() - notification_start
                if notification_duration > self.SLOW_NOTIFICATION_THRESHOLD_SECONDS:
                    logger.debug(
                        f"Slow Connection ID notification: "
                        f"{notification_duration * 1000:.2f}ms "
                        f"for Connection ID {new_connection_id.hex()[:8]}"
                    )
                return

            if not self._transport:
                return

            # Find the listener that owns this connection
            for listener in self._transport._listeners:
                # Find this connection in the listener's registry
                cids = await listener._registry.get_all_cids_for_connection(self)
                if cids:
                    # Use the first Connection ID found as the original Connection ID
                    original_connection_id = cids[0]
                    # Register new Connection ID using the registry with sequence number
                    await listener._registry.add_connection_id(
                        new_connection_id, original_connection_id, sequence
                    )
                    notification_duration = time.time() - notification_start
                    if notification_duration > 0.01:  # Log slow notifications (>10ms)
                        logger.debug(
                            f"Slow Connection ID notification: "
                            f"{notification_duration * 1000:.2f}ms "
                            f"for Connection ID {new_connection_id.hex()[:8]}"
                        )
                    logger.debug(
                        f"Registered new Connection ID {new_connection_id.hex()[:8]} "
                        f"(sequence {sequence}) for connection "
                        f"{original_connection_id.hex()[:8]}"
                    )
                    return

            logger.debug(
                f"Could not find listener to register new Connection ID "
                f"{new_connection_id.hex()[:8]}"
            )
        except Exception as e:
            logger.error(f"Error notifying listener of new CID: {e}")

    async def _handle_connection_id_retired(
        self, event: events.ConnectionIdRetired
    ) -> None:
        """
        Handle connection ID retirement.

        This handles when the peer tells us to stop using a connection ID.
        The listener will handle proper retirement ordering via the registry.
        """
        logger.debug(f"CONNECTION ID RETIRED: {event.connection_id.hex()}")

        # Remove from available IDs and add to retired set
        self._available_connection_ids.discard(event.connection_id)
        # This is diagnostic history, not routing or replay-protection state.
        # Lifetime totals remain in _stats; retain only recent identities.
        if event.connection_id not in self._retired_connection_ids:
            if len(self._retired_connection_id_order) >= self._cid_history_limit:
                oldest = self._retired_connection_id_order.popleft()
                self._retired_connection_ids.discard(oldest)
            self._retired_connection_id_order.append(event.connection_id)
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

        # aioquic already refuses datagrams addressed to a retired CID, so the
        # listener's routing entry can never be used again. Leaving it in the
        # registry keeps this connection (and its crypto state) reachable even
        # after the peer retires every CID it learned.
        await self._retire_listener_connection_id(event.connection_id)

    async def _retire_listener_connection_id(self, connection_id: bytes) -> None:
        """Drop a retired Connection ID from the listener's routing registry."""
        listener = self._listener
        registry = getattr(listener, "_registry", None)
        if registry is None:
            return

        try:
            await registry.remove_connection_id(connection_id)
        except Exception as error:
            logger.debug(
                "Error retiring Connection ID %s from listener: %s",
                connection_id.hex()[:8],
                error,
            )
            return

        if self._listener_connection_id != connection_id:
            return

        # New issuances are attached to ``_listener_connection_id``; point it at
        # a CID that is still registered so they do not get dropped.
        self._listener_connection_id = None
        try:
            live_cids = await registry.get_all_cids_for_connection(self)
        except Exception:
            live_cids = []
        live_cids = [cid for cid in live_cids if cid != connection_id]
        if self._current_connection_id in live_cids:
            self._listener_connection_id = self._current_connection_id
        elif live_cids:
            self._listener_connection_id = live_cids[0]

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
        else:
            # Without a wrapper nothing will close our receive half, so the
            # stream would stay in aioquic's registry forever.
            self._abandon_quic_stream(event.stream_id)

    async def _handle_handshake_completed(
        self, event: events.HandshakeCompleted
    ) -> None:
        """Handle handshake completion with security integration."""
        logger.debug("QUIC handshake completed")
        self._handshake_completed = True

        # Store handshake event for security verification
        self._handshake_events.append(event)

        # The first certificate is the peer's own, the others its chain.
        if event.peer_certificates:
            self._peer_certificate = event.peer_certificates[0]

        logger.debug("✅ Setting connected event")
        self._connected_event.set()

    async def _handle_connection_terminated(
        self, event: events.ConnectionTerminated
    ) -> None:
        """Handle connection termination."""
        logger.debug(f"QUIC connection terminated: {event.reason_phrase}")

        # Shield termination cleanup from caller cancellation so stream cleanup,
        # callbacks, parent notification, and socket close are never aborted.
        with trio.CancelScope() as cleanup_scope:
            cleanup_scope.shield = True
            try:
                # Close all streams
                for stream in list(self._streams.values()):
                    try:
                        if event.error_code:
                            await stream.handle_reset(event.error_code)
                        else:
                            await stream.close()
                    except Exception as e:
                        logger.debug(f"Error resetting stream on termination: {e}")
            finally:
                self._streams.clear()
                self._stream_cache.clear()  # Clear cache too
                self._abandoned_streams.clear()
                self._closed = True
                self._signal_activity()
                self._closed_event.set()

                # Release resource scope if present (mirrors close())
                try:
                    scope = getattr(self, "_resource_scope", None)
                    if scope is not None:
                        if hasattr(scope, "close"):
                            scope.close()
                        elif hasattr(scope, "release"):
                            scope.release()
                        elif hasattr(scope, "done"):
                            scope.done()
                except Exception as e:
                    logger.debug(f"Error releasing resource scope: {e}")

                self._stream_accept_event.set()
                logger.debug(f"Woke up pending accept_stream() calls, {id(self)}")

                # Ensure socket is closed immediately on connection termination
                if self._socket and self._owns_socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None

                # Cancel background tasks
                if hasattr(self, "_task_cancel_scopes"):
                    for s in list(self._task_cancel_scopes):
                        try:
                            s.cancel()
                        except Exception:
                            pass
                if hasattr(self, "_cancel_scope") and self._cancel_scope is not None:
                    try:
                        self._cancel_scope.cancel()
                    except Exception:
                        pass

                try:
                    await self._notify_parent_of_termination()
                except Exception as e:
                    logger.debug(f"Error in _notify_parent_of_termination: {e}")

                # Notify swarm/on_close listeners so peer bookkeeping is cleaned
                # up too — close() does this but this termination path bypassed it.
                #
                # getattr, not self.on_close: SwarmConnection deletes the hook
                # when it tears down, so the attribute can legitimately be gone
                # by the time a late ConnectionTerminated event is processed.
                on_close = getattr(self, "on_close", None)
                if on_close:
                    try:
                        await on_close()
                    except Exception as e:
                        logger.debug(f"Error in on_close during termination: {e}")

    async def _handle_stream_data(self, event: events.StreamDataReceived) -> None:
        """Handle stream data events - create streams and add to accept queue."""
        stream_id = event.stream_id
        self._stats["bytes_received"] += len(event.data)

        try:
            # Use fast lookup
            stream = self._get_stream_fast(stream_id)

            if not stream:
                # After _remove_stream(), late FIN-only events must not recreate
                # wrappers (inbound ghosts starve accept_stream under load).
                if self._is_fin_only_event(event):
                    direction = (
                        "inbound" if self._is_incoming_stream(stream_id) else "outbound"
                    )
                    logger.debug(
                        "Ignoring late FIN on closed %s stream %s "
                        "(is_initiator=%s, quic.is_client=%s)",
                        direction,
                        stream_id,
                        self._is_initiator,
                        getattr(
                            getattr(self._quic, "configuration", None),
                            "is_client",
                            None,
                        ),
                    )
                    return

                if self._is_incoming_stream(stream_id):
                    logger.debug(f"Creating new incoming stream {stream_id}")
                    stream = await self._create_inbound_stream(stream_id)
                else:
                    is_client = getattr(
                        getattr(self._quic, "configuration", None), "is_client", None
                    )
                    parity = "even" if stream_id % 2 == 0 else "odd"
                    logger.error(
                        f"Unexpected outbound stream {stream_id} in data event "
                        f"(parity={parity}, is_initiator={self._is_initiator}, "
                        f"quic.is_client={is_client}, streams={len(self._streams)}, "
                        f"cached={stream_id in self._stream_cache})"
                    )
                    return

            await self._deliver_stream_data(stream, event.data, event.end_stream)

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
            self._abandon_quic_stream(stream_id)
            raise QUICStreamError(
                f"Received data for unknown outbound stream {stream_id}"
            )

        if stream_id in self._recently_closed_streams:
            # Late event for a stream we already handled and closed.
            logger.debug("Ignoring late event for closed inbound stream %s", stream_id)
            self._abandon_quic_stream(stream_id)
            raise QUICStreamError(f"Closed inbound stream {stream_id}")

        quic_streams = getattr(self._quic, "_streams", None)
        if isinstance(quic_streams, dict) and stream_id not in quic_streams:
            # Late event for an already-discarded stream (see
            # _handle_stream_data_batch): aioquic no longer tracks it.
            logger.debug(
                "Ignoring late event for discarded inbound stream %s "
                "(aioquic no longer tracks it)",
                stream_id,
            )
            raise QUICStreamError(f"Discarded inbound stream {stream_id}")

        # Create new inbound stream
        return await self._create_inbound_stream(stream_id)

    @staticmethod
    def _is_fin_only_event(event: events.StreamDataReceived) -> bool:
        """Return True when the event is an empty end-of-stream (FIN-only)."""
        return (not event.data) and bool(event.end_stream)

    @staticmethod
    def _is_fin_only_events(events_list: list[QuicEvent]) -> bool:
        """Return True when every event in the batch is FIN-only."""
        if not events_list:
            return False
        for event in events_list:
            data = getattr(event, "data", b"")
            end_stream = getattr(event, "end_stream", False)
            if data or not end_stream:
                return False
        return True

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
            self._abandon_quic_stream(stream_id)

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

        # Send keep-alive PING if the connection has been idle too long.
        self._maybe_send_keepalive()

    def _maybe_send_keepalive(self) -> None:
        """
        Send a PING frame if the connection is idle past the keep-alive interval.

        aioquic has no built-in keep-alive; quic-go (used by kubo) sends a PING
        every KeepAlivePeriod (15 s) to keep idle connections open past the
        negotiated idle timeout. We mirror that here.
        """
        interval = self._keepalive_interval
        if interval <= 0.0 or self._closed or not self._handshake_completed:
            return
        now = time.time()
        if now - self._last_transmit_time >= interval:
            self._quic.send_ping(self._ping_uid_counter)
            self._ping_uid_counter += 1
            self._last_transmit_time = now
            self._stats["keepalive_pings_sent"] += 1

    # Network transmission

    async def _transmit(self) -> None:
        """Transmit pending QUIC packets using available socket."""
        sock = self._socket
        quic = self._quic
        if not sock or quic is None:
            # Teardown clears ``_quic`` before background tasks are cancelled.
            # Raising here (AttributeError: 'NoneType' has no attribute
            # 'datagrams_to_send') aborted the drain and turned routine
            # shutdown into a connection error, with the ACKs/RESETs for a
            # closing connection never sent.
            logger.debug("No socket or QUIC state to transmit")
            return

        try:
            current_time = time.time()
            datagrams = quic.datagrams_to_send(now=current_time)

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
                self._last_transmit_time = current_time

        except Exception as e:
            logger.error(f"Transmission error: {e}")
            await self._handle_connection_error(e)
            return

        # Every receive path (client receiver, listener routing, event loop)
        # ends here after aioquic has consumed incoming ACKs, so this is the
        # single place to wake writers blocked on send backpressure.
        self._refresh_send_backpressure()

    # Send-side backpressure support

    def stream_send_buffer_size(self, stream_id: int) -> int:
        """Bytes written to ``stream_id`` that the peer has not acknowledged yet."""
        return aioquic_compat.stream_send_buffer_size(self._quic, stream_id)

    def _refresh_send_backpressure(self) -> None:
        """Release streams whose un-ACKed send buffer dropped below the watermark."""
        for stream in list(self._streams.values()):
            # Writers re-arm backpressure themselves after each write step;
            # here we only need to look at streams that are currently blocked.
            if not stream._backpressure_event.is_set():
                stream._update_send_backpressure()

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
        if self._closed:
            # Nothing left to tear down: a task raced with close() and hit
            # state that close() had already released. Logging ERROR here
            # buried real faults under one line per shutdown.
            logger.debug(f"Ignoring error on already-closed connection: {error}")
            return

        logger.error(f"Connection error: {error}")

        try:
            await self.close()
        except Exception as close_error:
            logger.error(f"Error during connection close: {close_error}")

    # Connection close

    async def close(self) -> None:
        """Connection close with proper stream cleanup."""
        if self._closed:
            if self._socket and self._owns_socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            return

        self._closed = True
        self._signal_activity()
        if hasattr(self, "_task_cancel_scopes"):
            for s in list(self._task_cancel_scopes):
                try:
                    s.cancel()
                except Exception:
                    pass
        logger.debug(f"Closing QUIC connection to {self._remote_peer_id}")

        # Shield entire cleanup from caller cancellation so stream cleanup,
        # callbacks, and socket close are never aborted prematurely.
        with trio.CancelScope() as cleanup_scope:
            cleanup_scope.shield = True
            try:
                # Close all streams gracefully, but limit concurrency to prevent
                # excessive CPU usage when many streams fail simultaneously
                stream_close_tasks = []
                for stream in list(self._streams.values()):
                    if stream.can_write() or stream.can_read():
                        stream_close_tasks.append(stream.close)

                if stream_close_tasks and self._nursery:
                    try:
                        # Close streams in batches to prevent overwhelming the system
                        # when many streams fail simultaneously (e.g., 100 streams)
                        batch_size = 20  # Close streams in batches of 20
                        with trio.move_on_after(self.CONNECTION_CLOSE_TIMEOUT):
                            for i in range(0, len(stream_close_tasks), batch_size):
                                batch = stream_close_tasks[i : i + batch_size]
                                async with trio.open_nursery() as close_nursery:
                                    for task in batch:
                                        close_nursery.start_soon(task)
                    except Exception as e:
                        logger.warning(f"Error during graceful stream close: {e}")
                        # Force reset remaining streams quickly without batching
                        # to prevent resource leaks
                        for stream in list(self._streams.values()):
                            try:
                                # Use move_on_after to prevent hanging on stuck streams
                                with trio.move_on_after(0.1):  # 100ms per stream max
                                    await stream.reset(error_code=0)
                            except Exception:
                                pass

                on_close = getattr(self, "on_close", None)
                if on_close:
                    try:
                        await on_close()
                    except Exception as e:
                        logger.debug(f"Error in on_close callback: {e}")

                # Close QUIC connection
                try:
                    self._quic.close()
                except Exception:
                    pass

                # Best-effort transmit close frame (bounded with 0.1s timeout)
                if self._socket:
                    try:
                        with trio.move_on_after(0.1):
                            await self._transmit()
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Error during connection close: {e}")
            finally:
                # Guaranteed socket close regardless of any errors/exceptions
                if self._socket and self._owns_socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None

                self._streams.clear()
                self._stream_cache.clear()  # Clear cache
                self._abandoned_streams.clear()
                self._closed_event.set()
                self._stream_accept_event.set()

                # Cancel background tasks (receiver, event loop, maintenance)
                if hasattr(self, "_task_cancel_scopes"):
                    for s in list(self._task_cancel_scopes):
                        try:
                            s.cancel()
                        except Exception:
                            pass
                if hasattr(self, "_cancel_scope") and self._cancel_scope is not None:
                    try:
                        self._cancel_scope.cancel()
                    except Exception:
                        pass

                # Always notify parent transport and listener to remove this connection
                # from their connection tracking dictionaries to prevent memory leaks.
                try:
                    await self._notify_parent_of_termination()
                except Exception as e:
                    logger.debug(
                        f"Error notifying parent of connection termination: {e}"
                    )

                logger.debug(f"QUIC connection to {self._remote_peer_id} closed")

                # Release resource scope if present
                try:
                    scope = getattr(self, "_resource_scope", None)
                    if scope is not None:
                        if hasattr(scope, "close"):
                            scope.close()
                        elif hasattr(scope, "release"):
                            scope.release()
                        elif hasattr(scope, "done"):
                            scope.done()
                        self._resource_scope = None
                except Exception as e:
                    logger.debug(f"Error releasing resource scope: {e}")

                # Aggressively release ALL C-level state held by the aioquic
                # QuicConnection to prevent unbounded memory growth.
                # Without this, OpenSSL key schedules, recovery buffers, crypto
                # streams, and TLS session state remain allocated until Python GC
                # collects the object — which may never happen if any reference
                # lingers in the listener/registry tracking dicts.
                if self._quic is not None:
                    # Null out TLS context — frees OpenSSL key schedule, peer
                    # certificate chains, EC private keys, and receive buffers.
                    try:
                        self._quic.tls = None
                    except Exception:
                        pass
                    # Null out loss/recovery state — frees packet number space,
                    # ACK tracking, congestion controller, and pacer buffers.
                    try:
                        self._quic._loss = None
                    except Exception:
                        pass
                    # Clear crypto stream state — these hold bytearrays for
                    # handshake data that are never freed otherwise.
                    for attr in (
                        "_crypto_streams",
                        "_crypto_buffers",
                        "_cryptos",
                        "_cryptos_initial",
                    ):
                        if hasattr(self._quic, attr):
                            try:
                                val = getattr(self._quic, attr)
                                if hasattr(val, "clear"):
                                    val.clear()
                                elif hasattr(val, "values"):
                                    for v in val.values():
                                        if hasattr(v, "clear"):
                                            v.clear()
                            except Exception:
                                pass
                    # Clear datagram and network path state
                    for attr in (
                        "_events",
                        "_streams",
                        "_streams_finished",
                        "_datagrams_pending",
                        "_network_paths",
                        "_host_cids",
                        "_peer_cid_available",
                    ):
                        if hasattr(self._quic, attr):
                            try:
                                val = getattr(self._quic, attr)
                                if hasattr(val, "clear"):
                                    val.clear()
                            except Exception:
                                pass
                    # Null the quic_logger to prevent it holding buffered log data
                    try:
                        self._quic._quic_logger = None
                    except Exception:
                        pass
                    # Release the aioquic QuicConnection object entirely so
                    # Python GC can reclaim it immediately.
                    self._quic = None

                self._stream_accept_queue.clear()
                self._handshake_events.clear()
                self._peer_certificate = None
                self._stream_handler = None

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
                # Also try to remove from listeners
                for listener in self._transport._listeners:
                    try:
                        await listener._remove_connection_by_object(self)
                        logger.debug(
                            "Found and notified listener of connection termination"
                        )
                        break
                    except Exception:
                        continue
                return

            # Method 4: Use connection ID if we have one (most reliable)
            if self._current_connection_id:
                await self._cleanup_by_connection_id(self._current_connection_id)
                return

            host_cid_hex = ""
            if self._quic is not None and hasattr(self._quic, "host_cid"):
                try:
                    host_cid_hex = self._quic.host_cid.hex()
                except Exception:
                    pass
            logger.warning(
                "Could not notify parent of connection termination - no"
                f" parent reference found for conn host {host_cid_hex}"
            )

        except Exception as e:
            logger.error(f"Error notifying parent of connection termination: {e}")

    async def _cleanup_by_connection_id(self, connection_id: bytes) -> None:
        """Cleanup using connection ID as a fallback method."""
        try:
            for listener in self._transport._listeners:
                # Find this connection in the listener's registry
                cids = await listener._registry.get_all_cids_for_connection(self)
                if cids:
                    # Remove using the first Connection ID found
                    tracked_cid = cids[0]
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

    def get_congestion_stats(self) -> dict[str, float | int | None]:
        """
        Snapshot aioquic congestion-control state for throughput diagnosis.

        Returns congestion_window, bytes_in_flight, and smoothed_rtt when the
        underlying QuicConnection exposes ``_loss`` (aioquic private API).
        """
        loss = getattr(self._quic, "_loss", None)
        if loss is None:
            return {
                "congestion_window": None,
                "bytes_in_flight": None,
                "smoothed_rtt": None,
            }
        return {
            "congestion_window": int(getattr(loss, "congestion_window", 0) or 0),
            "bytes_in_flight": int(getattr(loss, "bytes_in_flight", 0) or 0),
            "smoothed_rtt": float(getattr(loss, "_rtt_smoothed", 0.0) or 0.0),
        }

    def _maybe_log_congestion_stats(self) -> None:
        """Periodically log CWND/RTT when LIBP2P_QUIC_CC_STATS is set."""
        if not os.environ.get("LIBP2P_QUIC_CC_STATS", "").strip():
            return
        now = time.monotonic()
        if now - self._last_cc_stats_log < 0.05:
            return
        self._last_cc_stats_log = now
        stats = self.get_congestion_stats()
        logger.info(
            "QUIC CC stats cwnd=%s bif=%s srtt=%.6f peer=%s",
            stats["congestion_window"],
            stats["bytes_in_flight"],
            float(stats["smoothed_rtt"] or 0.0),
            self._remote_peer_id,
        )

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

    async def _cleanup_orphaned_streams(self) -> None:
        """
        Detect and close orphaned streams that have no activity for too long.

        Orphaned streams are streams that are open but have not had any data
        flow for ORPHANED_STREAM_TIMEOUT seconds. This handles the case where
        a connection dies but streams remain in _streams dict.
        """
        ORPHANED_STREAM_TIMEOUT = 300  # 5 minutes
        current_time = time.time()
        streams_to_reset = []

        for stream in list(self._streams.values()):
            if stream.is_closed() or stream.is_reset():
                continue

            # Check if stream has been inactive for too long
            if hasattr(stream, "_timeline"):
                last_activity = stream._timeline.last_activity
                age = current_time - last_activity
                if age > ORPHANED_STREAM_TIMEOUT:
                    streams_to_reset.append(stream)
                    logger.debug(
                        "Found orphaned stream %s (age=%.0fs, direction=%s)",
                        stream.stream_id,
                        age,
                        stream.direction,
                    )

        if streams_to_reset:
            logger.warning(
                "Resetting %d orphaned streams on connection to %s",
                len(streams_to_reset),
                self._remote_peer_id,
            )
            for stream in streams_to_reset:
                try:
                    with trio.move_on_after(0.5):
                        await stream.reset(error_code=0)
                except Exception:
                    # Force remove if reset fails
                    self._remove_stream(int(stream.stream_id))

    def get_transport_addresses(self) -> list[Multiaddr]:
        """
        Get the actual transport addresses used by this connection.

        Returns the real IP/port addresses, not peerstore addresses.
        For relayed connections, should include /p2p-circuit in the path.
        """
        return [self._maddr]

    def get_connection_type(self) -> ConnectionType:
        """
        Get the type of connection (direct, relayed, etc.)
        """
        # For QUIC connections, assume direct
        return ConnectionType.DIRECT

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
