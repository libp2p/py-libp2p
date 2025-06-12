"""
QUIC Connection implementation for py-libp2p.
Uses aioquic's sans-IO core with trio for async operations.
"""

import logging
import socket
import time
from typing import TYPE_CHECKING

from aioquic.quic import (
    events,
)
from aioquic.quic.connection import (
    QuicConnection,
)
import multiaddr
import trio

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    IRawConnection,
)
from libp2p.custom_types import TQUICStreamHandlerFn
from libp2p.peer.id import (
    ID,
)

from .exceptions import (
    QUICConnectionError,
    QUICStreamError,
)
from .stream import (
    QUICStream,
)

if TYPE_CHECKING:
    from .transport import (
        QUICTransport,
    )

logger = logging.getLogger(__name__)


class QUICConnection(IRawConnection, IMuxedConn):
    """
    QUIC connection implementing both raw connection and muxed connection interfaces.

    Uses aioquic's sans-IO core with trio for native async support.
    QUIC natively provides stream multiplexing, so this connection acts as both
    a raw connection (for transport layer) and muxed connection (for upper layers).

    Updated to work properly with the QUIC listener for server-side connections.
    """

    def __init__(
        self,
        quic_connection: QuicConnection,
        remote_addr: tuple[str, int],
        peer_id: ID | None,
        local_peer_id: ID,
        is_initiator: bool,
        maddr: multiaddr.Multiaddr,
        transport: "QUICTransport",
    ):
        self._quic = quic_connection
        self._remote_addr = remote_addr
        self._peer_id = peer_id
        self._local_peer_id = local_peer_id
        self.__is_initiator = is_initiator
        self._maddr = maddr
        self._transport = transport

        # Trio networking - socket may be provided by listener
        self._socket: trio.socket.SocketType | None = None
        self._connected_event = trio.Event()
        self._closed_event = trio.Event()

        # Stream management
        self._streams: dict[int, QUICStream] = {}
        self._next_stream_id: int = self._calculate_initial_stream_id()
        self._stream_handler: TQUICStreamHandlerFn | None = None
        self._stream_id_lock = trio.Lock()

        # Connection state
        self._closed = False
        self._established = False
        self._started = False

        # Background task management
        self._background_tasks_started = False
        self._nursery: trio.Nursery | None = None

        logger.debug(
            f"Created QUIC connection to {peer_id} (initiator: {is_initiator})"
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

    @property
    def is_initiator(self) -> bool:  # type: ignore
        return self.__is_initiator

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

        # If this is a client connection, we need to establish the connection
        if self.__is_initiator:
            await self._initiate_connection()
        else:
            # For server connections, we're already connected via the listener
            self._established = True
            self._connected_event.set()

        logger.debug(f"QUIC connection to {self._peer_id} started")

    async def _initiate_connection(self) -> None:
        """Initiate client-side connection establishment."""
        try:
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

            # For client connections, we need to manage our own background tasks
            # In a real implementation, this would be managed by the transport
            # For now, we'll start them here
            if not self._background_tasks_started:
                # We would need a nursery to start background tasks
                # This is a limitation of the current design
                logger.warning(
                    "Background tasks need nursery - connection may not work properly"
                )

        except Exception as e:
            logger.error(f"Failed to initiate connection: {e}")
            raise QUICConnectionError(f"Connection initiation failed: {e}") from e

    async def connect(self, nursery: trio.Nursery) -> None:
        """
        Establish the QUIC connection using trio.

        Args:
            nursery: Trio nursery for background tasks

        """
        if not self.__is_initiator:
            raise QUICConnectionError(
                "connect() should only be called by client connections"
            )

        try:
            # Store nursery for background tasks
            self._nursery = nursery

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

            # Start background tasks
            await self._start_background_tasks(nursery)

            # Wait for connection to be established
            await self._connected_event.wait()

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise QUICConnectionError(f"Connection failed: {e}") from e

    async def _start_background_tasks(self, nursery: trio.Nursery) -> None:
        """Start background tasks for connection management."""
        if self._background_tasks_started:
            return

        self._background_tasks_started = True

        # Start background tasks
        nursery.start_soon(self._handle_incoming_data)
        nursery.start_soon(self._handle_timer)

    async def _handle_incoming_data(self) -> None:
        """Handle incoming UDP datagrams in trio."""
        while not self._closed:
            try:
                if self._socket:
                    data, addr = await self._socket.recvfrom(65536)
                    self._quic.receive_datagram(data, addr, now=time.time())
                await self._process_events()
                await self._transmit()

                # Small delay to prevent busy waiting
                await trio.sleep(0.001)

            except trio.ClosedResourceError:
                break
            except Exception as e:
                logger.error(f"Error handling incoming data: {e}")
                break

    async def _handle_timer(self) -> None:
        """Handle QUIC timer events in trio."""
        while not self._closed:
            try:
                timer_at = self._quic.get_timer()
                if timer_at is None:
                    await trio.sleep(0.1)  # No timer set, check again later
                    continue

                now = time.time()
                if timer_at <= now:
                    self._quic.handle_timer(now=now)
                    await self._process_events()
                    await self._transmit()
                    await trio.sleep(0.001)  # Small delay
                else:
                    # Sleep until timer fires, but check periodically
                    sleep_time = min(timer_at - now, 0.1)
                    await trio.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in timer handler: {e}")
                await trio.sleep(0.1)

    async def _process_events(self) -> None:
        """Process QUIC events from aioquic core."""
        while True:
            event = self._quic.next_event()
            if event is None:
                break

            if isinstance(event, events.ConnectionTerminated):
                logger.info(f"QUIC connection terminated: {event.reason_phrase}")
                self._closed = True
                self._closed_event.set()
                break

            elif isinstance(event, events.HandshakeCompleted):
                logger.debug("QUIC handshake completed")
                self._established = True
                self._connected_event.set()

            elif isinstance(event, events.StreamDataReceived):
                await self._handle_stream_data(event)

            elif isinstance(event, events.StreamReset):
                await self._handle_stream_reset(event)

    async def _handle_stream_data(self, event: events.StreamDataReceived) -> None:
        """Handle incoming stream data."""
        stream_id = event.stream_id

        # Get or create stream
        if stream_id not in self._streams:
            # Determine if this is an incoming stream
            is_incoming = self._is_incoming_stream(stream_id)

            stream = QUICStream(
                connection=self,
                stream_id=stream_id,
                is_initiator=not is_incoming,
            )
            self._streams[stream_id] = stream

            # Notify stream handler for incoming streams
            if is_incoming and self._stream_handler:
                # Start stream handler in background
                # In a real implementation, you might want to use the nursery
                # passed to the connection, but for now we'll handle it directly
                try:
                    await self._stream_handler(stream)
                except Exception as e:
                    logger.error(f"Error in stream handler: {e}")

        # Forward data to stream
        stream = self._streams[stream_id]
        await stream.handle_data_received(event.data, event.end_stream)

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
        """Handle stream reset."""
        stream_id = event.stream_id
        if stream_id in self._streams:
            stream = self._streams[stream_id]
            await stream.handle_reset(event.error_code)
            del self._streams[stream_id]

    async def _transmit(self) -> None:
        """Send pending datagrams using trio."""
        socket = self._socket
        if socket is None:
            return

        try:
            for data, addr in self._quic.datagrams_to_send(now=time.time()):
                await socket.sendto(data, addr)
        except Exception as e:
            logger.error(f"Failed to send datagram: {e}")

    # IRawConnection interface

    async def write(self, data: bytes) -> None:
        """
        Write data to the connection.
        For QUIC, this creates a new stream for each write operation.
        """
        if self._closed:
            raise QUICConnectionError("Connection is closed")

        stream = await self.open_stream()
        await stream.write(data)
        await stream.close()

    async def read(self, n: int | None = -1) -> bytes:
        """
        Read data from the connection.
        For QUIC, this reads from the next available stream.
        """
        if self._closed:
            raise QUICConnectionError("Connection is closed")

        # For raw connection interface, we need to handle this differently
        # In practice, upper layers will use the muxed connection interface
        raise NotImplementedError(
            "Use muxed connection interface for stream-based reading"
        )

    async def close(self) -> None:
        """Close the connection and all streams."""
        if self._closed:
            return

        self._closed = True
        logger.debug(f"Closing QUIC connection to {self._peer_id}")

        # Close all streams
        stream_close_tasks = []
        for stream in list(self._streams.values()):
            stream_close_tasks.append(stream.close())

        if stream_close_tasks:
            # Close streams concurrently
            async with trio.open_nursery() as nursery:
                for task in stream_close_tasks:
                    nursery.start_soon(lambda t=task: t)

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

    @property
    def is_closed(self) -> bool:
        """Check if connection is closed."""
        return self._closed

    @property
    def is_established(self) -> bool:
        """Check if connection is established (handshake completed)."""
        return self._established

    @property
    def is_started(self) -> bool:
        """Check if connection has been started."""
        return self._started

    def multiaddr(self) -> multiaddr.Multiaddr:
        """Get the multiaddr for this connection."""
        return self._maddr

    def local_peer_id(self) -> ID:
        """Get the local peer ID."""
        return self._local_peer_id

    def remote_peer_id(self) -> ID | None:
        """Get the remote peer ID."""
        return self._peer_id

    # IMuxedConn interface

    async def open_stream(self) -> IMuxedStream:
        """
        Open a new stream on this connection.

        Returns:
            New QUIC stream

        """
        if self._closed:
            raise QUICStreamError("Connection is closed")

        if not self._started:
            raise QUICStreamError("Connection not started")

        async with self._stream_id_lock:
            # Generate next stream ID
            stream_id = self._next_stream_id
            self._next_stream_id += 4  # Increment by 4 for bidirectional streams

            # Create stream
            stream = QUICStream(connection=self, stream_id=stream_id, is_initiator=True)

            self._streams[stream_id] = stream

        logger.debug(f"Opened QUIC stream {stream_id}")
        return stream

    def set_stream_handler(self, handler_function: TQUICStreamHandlerFn) -> None:
        """
        Set handler for incoming streams.

        Args:
            handler_function: Function to handle new incoming streams

        """
        self._stream_handler = handler_function

    async def accept_stream(self) -> IMuxedStream:
        """
        Accept an incoming stream.

        Returns:
            Accepted stream

        """
        # This is handled automatically by the event processing
        # Upper layers should use set_stream_handler instead
        raise NotImplementedError("Use set_stream_handler for incoming streams")

    async def verify_peer_identity(self) -> None:
        """
        Verify the remote peer's identity using TLS certificate.
        This implements the libp2p TLS handshake verification.
        """
        # Extract peer ID from TLS certificate
        # This should match the expected peer ID
        try:
            cert_peer_id = self._extract_peer_id_from_cert()

            if self._peer_id and cert_peer_id != self._peer_id:
                raise QUICConnectionError(
                    f"Peer ID mismatch: expected {self._peer_id}, got {cert_peer_id}"
                )

            if not self._peer_id:
                self._peer_id = cert_peer_id

            logger.debug(f"Verified peer identity: {self._peer_id}")

        except NotImplementedError:
            logger.warning("Peer identity verification not implemented - skipping")
            # For now, we'll skip verification during development

    def _extract_peer_id_from_cert(self) -> ID:
        """Extract peer ID from TLS certificate."""
        # This should extract the peer ID from the TLS certificate
        # following the libp2p TLS specification
        # Implementation depends on how the certificate is structured

        # Placeholder - implement based on libp2p TLS spec
        # The certificate should contain the peer ID in a specific extension
        raise NotImplementedError("Certificate peer ID extraction not implemented")

    # TODO: Define type for stats
    def get_stats(self) -> dict[str, object]:
        """Get connection statistics."""
        stats: dict[str, object] = {
            "peer_id": str(self._peer_id),
            "remote_addr": self._remote_addr,
            "is_initiator": self.__is_initiator,
            "is_established": self._established,
            "is_closed": self._closed,
            "is_started": self._started,
            "active_streams": len(self._streams),
            "next_stream_id": self._next_stream_id,
        }
        return stats

    def get_remote_address(self) -> tuple[str, int]:
        return self._remote_addr

    def __str__(self) -> str:
        """String representation of the connection."""
        id = self._peer_id
        estb = self._established
        stream_len = len(self._streams)
        return f"QUICConnection(peer={id}, streams={stream_len}".__add__(
            f"established={estb}, started={self._started})"
        )
