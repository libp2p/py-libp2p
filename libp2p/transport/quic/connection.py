"""
QUIC Connection implementation for py-libp2p.
Uses aioquic's sans-IO core with trio for async operations.
"""

import logging
import socket
import time

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
from libp2p.custom_types import (
    StreamHandlerFn,
)
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
    """

    def __init__(
        self,
        quic_connection: QuicConnection,
        remote_addr: tuple[str, int],
        peer_id: ID,
        local_peer_id: ID,
        initiator: bool,
        maddr: multiaddr.Multiaddr,
        transport: QUICTransport,
    ):
        self._quic = quic_connection
        self._remote_addr = remote_addr
        self._peer_id = peer_id
        self._local_peer_id = local_peer_id
        self.__is_initiator = initiator
        self._maddr = maddr
        self._transport = transport

        # Trio networking
        self._socket: trio.socket.SocketType | None = None
        self._connected_event = trio.Event()
        self._closed_event = trio.Event()

        # Stream management
        self._streams: dict[int, QUICStream] = {}
        self._next_stream_id: int = (
            0 if initiator else 1
        )  # Even for initiator, odd for responder
        self._stream_handler: StreamHandlerFn | None = None

        # Connection state
        self._closed = False
        self._timer_task = None

        logger.debug(f"Created QUIC connection to {peer_id}")

    @property
    def is_initiator(self) -> bool:  # type: ignore
        return self.__is_initiator

    async def connect(self) -> None:
        """Establish the QUIC connection using trio."""
        try:
            # Create UDP socket using trio
            self._socket = trio.socket.socket(
                family=socket.AF_INET, type=socket.SOCK_DGRAM
            )

            # Start the connection establishment
            self._quic.connect(self._remote_addr, now=time.time())

            # Send initial packet(s)
            await self._transmit()

            # Start background tasks using trio nursery
            async with trio.open_nursery() as nursery:
                nursery.start_soon(
                    self._handle_incoming_data, None, "QUIC INCOMING DATA"
                )
                nursery.start_soon(self._handle_timer, None, "QUIC TIMER HANDLER")

                # Wait for connection to be established
                await self._connected_event.wait()

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise QUICConnectionError(f"Connection failed: {e}") from e

    async def _handle_incoming_data(self) -> None:
        """Handle incoming UDP datagrams in trio."""
        while not self._closed:
            try:
                if self._socket:
                    data, addr = await self._socket.recvfrom(65536)
                    self._quic.receive_datagram(data, addr, now=time.time())
                await self._process_events()
                await self._transmit()
            except trio.ClosedResourceError:
                break
            except Exception as e:
                logger.error(f"Error handling incoming data: {e}")
                break

    async def _handle_timer(self) -> None:
        """Handle QUIC timer events in trio."""
        while not self._closed:
            timer_at = self._quic.get_timer()
            if timer_at is None:
                await trio.sleep(1.0)  # No timer set, check again later
                continue

            now = time.time()
            if timer_at <= now:
                self._quic.handle_timer(now=now)
                await self._process_events()
                await self._transmit()
            else:
                await trio.sleep(timer_at - now)

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
                self._connected_event.set()

            elif isinstance(event, events.StreamDataReceived):
                await self._handle_stream_data(event)

            elif isinstance(event, events.StreamReset):
                await self._handle_stream_reset(event)

    async def _handle_stream_data(self, event: events.StreamDataReceived) -> None:
        """Handle incoming stream data."""
        stream_id = event.stream_id

        if stream_id not in self._streams:
            # Create new stream for incoming data
            stream = QUICStream(
                connection=self,
                stream_id=stream_id,
                is_initiator=False,  # pyrefly: ignore
            )
            self._streams[stream_id] = stream

            # Notify stream handler if available
            if self._stream_handler:
                # Use trio nursery to start stream handler
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self._stream_handler, stream)

        # Forward data to stream
        stream = self._streams[stream_id]
        await stream.handle_data_received(event.data, event.end_stream)

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

        for data, addr in self._quic.datagrams_to_send(now=time.time()):
            try:
                await socket.sendto(data, addr)
            except Exception as e:
                logger.error(f"Failed to send datagram: {e}")

    # IRawConnection interface

    async def write(self, data: bytes):
        """
        Write data to the connection.
        For QUIC, this creates a new stream for each write operation.
        """
        if self._closed:
            raise QUICConnectionError("Connection is closed")

        stream = await self.open_stream()
        await stream.write(data)
        await stream.close()

    async def read(self, n: int = -1) -> bytes:
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

        # Close all streams using trio nursery
        async with trio.open_nursery() as nursery:
            for stream in self._streams.values():
                nursery.start_soon(stream.close)

        # Close QUIC connection
        self._quic.close()
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

    def multiaddr(self) -> multiaddr.Multiaddr:
        """Get the multiaddr for this connection."""
        return self._maddr

    def local_peer_id(self) -> ID:
        """Get the local peer ID."""
        return self._local_peer_id

    # IMuxedConn interface

    async def open_stream(self) -> IMuxedStream:
        """
        Open a new stream on this connection.

        Returns:
            New QUIC stream

        """
        if self._closed:
            raise QUICStreamError("Connection is closed")

        # Generate next stream ID
        stream_id = self._next_stream_id
        self._next_stream_id += (
            2  # Increment by 2 to maintain initiator/responder distinction
        )

        # Create stream
        stream = QUICStream(
            connection=self, stream_id=stream_id, is_initiator=True
        )  # pyrefly: ignore

        self._streams[stream_id] = stream

        logger.debug(f"Opened QUIC stream {stream_id}")
        return stream

    def set_stream_handler(self, handler_function: StreamHandlerFn) -> None:
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
        cert_peer_id = self._extract_peer_id_from_cert()

        if self._peer_id and cert_peer_id != self._peer_id:
            raise QUICConnectionError(
                f"Peer ID mismatch: expected {self._peer_id}, got {cert_peer_id}"
            )

        if not self._peer_id:
            self._peer_id = cert_peer_id

        logger.debug(f"Verified peer identity: {self._peer_id}")

    def _extract_peer_id_from_cert(self) -> ID:
        """Extract peer ID from TLS certificate."""
        # This should extract the peer ID from the TLS certificate
        # following the libp2p TLS specification
        # Implementation depends on how the certificate is structured

        # Placeholder - implement based on libp2p TLS spec
        # The certificate should contain the peer ID in a specific extension
        raise NotImplementedError("Certificate peer ID extraction not implemented")

    def __str__(self) -> str:
        """String representation of the connection."""
        return f"QUICConnection(peer={self._peer_id}, streams={len(self._streams)})"
