"""
QUIC Stream implementation
Provides stream interface over QUIC's native multiplexing.
"""

from enum import Enum
import logging
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, cast

import trio

from .exceptions import (
    QUICStreamBackpressureError,
    QUICStreamClosedError,
    QUICStreamResetError,
    QUICStreamTimeoutError,
)

if TYPE_CHECKING:
    from libp2p.abc import IMuxedStream
    from libp2p.custom_types import TProtocol

    from .connection import QUICConnection
else:
    IMuxedStream = cast(type, object)
    TProtocol = cast(type, object)

logger = logging.getLogger(__name__)


class StreamState(Enum):
    """Stream lifecycle states following libp2p patterns."""

    OPEN = "open"
    WRITE_CLOSED = "write_closed"
    READ_CLOSED = "read_closed"
    CLOSED = "closed"
    RESET = "reset"


class StreamDirection(Enum):
    """Stream direction for tracking initiator."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class StreamTimeline:
    """Track stream lifecycle events for debugging and monitoring."""

    def __init__(self) -> None:
        self.created_at = time.time()
        self.opened_at: float | None = None
        self.first_data_at: float | None = None
        self.closed_at: float | None = None
        self.reset_at: float | None = None
        self.error_code: int | None = None

    def record_open(self) -> None:
        self.opened_at = time.time()

    def record_first_data(self) -> None:
        if self.first_data_at is None:
            self.first_data_at = time.time()

    def record_close(self) -> None:
        self.closed_at = time.time()

    def record_reset(self, error_code: int) -> None:
        self.reset_at = time.time()
        self.error_code = error_code


class QUICStream(IMuxedStream):
    """
    QUIC Stream implementation following libp2p IMuxedStream interface.

    Based on patterns from go-libp2p and js-libp2p, this implementation:
    - Leverages QUIC's native multiplexing and flow control
    - Integrates with libp2p resource management
    - Provides comprehensive error handling with QUIC-specific codes
    - Supports bidirectional communication with independent close semantics
    - Implements proper stream lifecycle management
    """

    def __init__(
        self,
        connection: "QUICConnection",
        stream_id: int,
        direction: StreamDirection,
        remote_addr: tuple[str, int],
        resource_scope: Any | None = None,
    ):
        """
        Initialize QUIC stream.

        Args:
            connection: Parent QUIC connection
            stream_id: QUIC stream identifier
            direction: Stream direction (inbound/outbound)
            resource_scope: Resource manager scope for memory accounting
            remote_addr: Remote addr stream is connected to

        """
        self._connection = connection
        self._stream_id = stream_id
        self._direction = direction
        self._resource_scope = resource_scope

        # libp2p interface compliance
        self._protocol: TProtocol | None = None
        self._metadata: dict[str, Any] = {}
        self._remote_addr = remote_addr

        # Stream state management
        self._state = StreamState.OPEN
        self._state_lock = trio.Lock()

        # Flow control and buffering
        self._receive_buffer = bytearray()
        self._receive_buffer_lock = trio.Lock()
        self._receive_event = trio.Event()
        self._backpressure_event = trio.Event()
        self._backpressure_event.set()  # Initially no backpressure

        # Close/reset state
        self._write_closed = False
        self._read_closed = False
        self._close_event = trio.Event()
        self._reset_error_code: int | None = None

        # Lifecycle tracking
        self._timeline = StreamTimeline()
        self._timeline.record_open()

        # Resource accounting
        self._memory_reserved = 0

        # Stream constant configurations
        self.READ_TIMEOUT = connection._transport._config.STREAM_READ_TIMEOUT
        self.WRITE_TIMEOUT = connection._transport._config.STREAM_WRITE_TIMEOUT
        self.FLOW_CONTROL_WINDOW_SIZE = (
            connection._transport._config.STREAM_FLOW_CONTROL_WINDOW
        )
        self.MAX_RECEIVE_BUFFER_SIZE = (
            connection._transport._config.MAX_STREAM_RECEIVE_BUFFER
        )

        if self._resource_scope:
            self._reserve_memory(self.FLOW_CONTROL_WINDOW_SIZE)

        logger.debug(
            f"Created QUIC stream {stream_id} "
            f"({direction.value}, connection: {connection.remote_peer_id()})"
        )

    # Properties for libp2p interface compliance

    @property
    def protocol(self) -> TProtocol | None:
        """Get the protocol identifier for this stream."""
        return self._protocol

    @protocol.setter
    def protocol(self, protocol_id: TProtocol) -> None:
        """Set the protocol identifier for this stream."""
        self._protocol = protocol_id
        self._metadata["protocol"] = protocol_id
        logger.debug(f"Stream {self.stream_id} protocol set to: {protocol_id}")

    @property
    def stream_id(self) -> str:
        """Get stream ID as string for libp2p compatibility."""
        return str(self._stream_id)

    @property
    def muxed_conn(self) -> "QUICConnection":  # type: ignore
        """Get the parent muxed connection."""
        return self._connection

    @property
    def state(self) -> StreamState:
        """Get current stream state."""
        return self._state

    @property
    def direction(self) -> StreamDirection:
        """Get stream direction."""
        return self._direction

    @property
    def is_initiator(self) -> bool:
        """Check if this stream was locally initiated."""
        return self._direction == StreamDirection.OUTBOUND

    # Core stream operations

    async def read(self, n: int | None = None) -> bytes:
        """
        Read data from the stream with QUIC flow control.

        Args:
            n: Maximum number of bytes to read. If None or -1, read all available.

        Returns:
            Data read from stream

        Raises:
            QUICStreamClosedError: Stream is closed
            QUICStreamResetError: Stream was reset
            QUICStreamTimeoutError: Read timeout exceeded

        """
        if n is None:
            n = -1

        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                raise QUICStreamClosedError(f"Stream {self.stream_id} is closed")

            if self._read_closed:
                # Return any remaining buffered data, then EOF
                async with self._receive_buffer_lock:
                    if self._receive_buffer:
                        data = self._extract_data_from_buffer(n)
                        self._timeline.record_first_data()
                        return data
                return b""

        # Wait for data with timeout
        timeout = self.READ_TIMEOUT
        try:
            with trio.move_on_after(timeout) as cancel_scope:
                while True:
                    async with self._receive_buffer_lock:
                        if self._receive_buffer:
                            data = self._extract_data_from_buffer(n)
                            self._timeline.record_first_data()
                            return data

                        # Check if stream was closed while waiting
                        if self._read_closed:
                            return b""

                    # Wait for more data
                    await self._receive_event.wait()
                    self._receive_event = trio.Event()  # Reset for next wait

            if cancel_scope.cancelled_caught:
                raise QUICStreamTimeoutError(f"Read timeout on stream {self.stream_id}")

            return b""
        except QUICStreamResetError:
            # Stream was reset while reading
            raise
        except Exception as e:
            logger.error(f"Error reading from stream {self.stream_id}: {e}")
            await self._handle_stream_error(e)
            raise

    async def write(self, data: bytes) -> None:
        """
        Write data to the stream with QUIC flow control.

        Args:
            data: Data to write

        Raises:
            QUICStreamClosedError: Stream is closed for writing
            QUICStreamBackpressureError: Flow control window exhausted
            QUICStreamResetError: Stream was reset

        """
        if not data:
            return

        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                raise QUICStreamClosedError(f"Stream {self.stream_id} is closed")

            if self._write_closed:
                raise QUICStreamClosedError(
                    f"Stream {self.stream_id} write side is closed"
                )

        try:
            # Handle flow control backpressure
            await self._backpressure_event.wait()

            # Send data through QUIC connection
            self._connection._quic.send_stream_data(self._stream_id, data)
            await self._connection._transmit()

            self._timeline.record_first_data()
            logger.debug(f"Wrote {len(data)} bytes to stream {self.stream_id}")

        except Exception as e:
            logger.error(f"Error writing to stream {self.stream_id}: {e}")
            # Convert QUIC-specific errors
            if "flow control" in str(e).lower():
                raise QUICStreamBackpressureError(f"Flow control limit reached: {e}")
            await self._handle_stream_error(e)
            raise

    async def close(self) -> None:
        """
        Close the stream gracefully (both read and write sides).

        This implements proper close semantics where both sides
        are closed and resources are cleaned up.
        """
        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                return

            logger.debug(f"Closing stream {self.stream_id}")

        # Close both sides
        if not self._write_closed:
            await self.close_write()
        if not self._read_closed:
            await self.close_read()

        # Update state and cleanup
        async with self._state_lock:
            self._state = StreamState.CLOSED

        await self._cleanup_resources()
        self._timeline.record_close()
        self._close_event.set()

        logger.debug(f"Stream {self.stream_id} closed")

    async def close_write(self) -> None:
        """Close the write side of the stream."""
        if self._write_closed:
            return

        try:
            # Send FIN to close write side
            self._connection._quic.send_stream_data(
                self._stream_id, b"", end_stream=True
            )
            await self._connection._transmit()

            self._write_closed = True

            async with self._state_lock:
                if self._read_closed:
                    self._state = StreamState.CLOSED
                else:
                    self._state = StreamState.WRITE_CLOSED

            logger.debug(f"Stream {self.stream_id} write side closed")

        except Exception as e:
            logger.error(f"Error closing write side of stream {self.stream_id}: {e}")

    async def close_read(self) -> None:
        """Close the read side of the stream."""
        if self._read_closed:
            return

        try:
            self._read_closed = True

            async with self._state_lock:
                if self._write_closed:
                    self._state = StreamState.CLOSED
                else:
                    self._state = StreamState.READ_CLOSED

            # Wake up any pending reads
            self._receive_event.set()

            logger.debug(f"Stream {self.stream_id} read side closed")

        except Exception as e:
            logger.error(f"Error closing read side of stream {self.stream_id}: {e}")

    async def reset(self, error_code: int = 0) -> None:
        """
        Reset the stream with the given error code.

        Args:
            error_code: QUIC error code for the reset

        """
        async with self._state_lock:
            if self._state == StreamState.RESET:
                return

            logger.debug(
                f"Resetting stream {self.stream_id} with error code {error_code}"
            )

            self._state = StreamState.RESET
            self._reset_error_code = error_code

        try:
            # Send QUIC reset frame
            self._connection._quic.reset_stream(self._stream_id, error_code)
            await self._connection._transmit()

        except Exception as e:
            logger.error(f"Error sending reset for stream {self.stream_id}: {e}")
        finally:
            # Always cleanup resources
            await self._cleanup_resources()
            self._timeline.record_reset(error_code)
            self._close_event.set()

    def is_closed(self) -> bool:
        """Check if stream is completely closed."""
        return self._state in (StreamState.CLOSED, StreamState.RESET)

    def is_reset(self) -> bool:
        """Check if stream was reset."""
        return self._state == StreamState.RESET

    def can_read(self) -> bool:
        """Check if stream can be read from."""
        return not self._read_closed and self._state not in (
            StreamState.CLOSED,
            StreamState.RESET,
        )

    def can_write(self) -> bool:
        """Check if stream can be written to."""
        return not self._write_closed and self._state not in (
            StreamState.CLOSED,
            StreamState.RESET,
        )

    async def handle_data_received(self, data: bytes, end_stream: bool) -> None:
        """
        Handle data received from the QUIC connection.

        Args:
            data: Received data
            end_stream: Whether this is the last data (FIN received)

        """
        if self._state == StreamState.RESET:
            return

        if data:
            async with self._receive_buffer_lock:
                if len(self._receive_buffer) + len(data) > self.MAX_RECEIVE_BUFFER_SIZE:
                    logger.warning(
                        f"Stream {self.stream_id} receive buffer overflow, "
                        f"dropping {len(data)} bytes"
                    )
                    return

                self._receive_buffer.extend(data)
                self._timeline.record_first_data()

            # Notify waiting readers
            self._receive_event.set()

            logger.debug(f"Stream {self.stream_id} received {len(data)} bytes")

        if end_stream:
            self._read_closed = True
            async with self._state_lock:
                if self._write_closed:
                    self._state = StreamState.CLOSED
                else:
                    self._state = StreamState.READ_CLOSED

            # Wake up readers to process remaining data and EOF
            self._receive_event.set()

            logger.debug(f"Stream {self.stream_id} received FIN")

    async def handle_stop_sending(self, error_code: int) -> None:
        """
        Handle STOP_SENDING frame from remote peer.

        When a STOP_SENDING frame is received, the peer is requesting that we
        stop sending data on this stream. We respond by resetting the stream.

        Args:
            error_code: Error code from the STOP_SENDING frame

        """
        logger.debug(
            f"Stream {self.stream_id} handling STOP_SENDING (error_code={error_code})"
        )

        self._write_closed = True

        # Wake up any pending write operations
        self._backpressure_event.set()

        async with self._state_lock:
            if self.direction == StreamDirection.OUTBOUND:
                self._state = StreamState.CLOSED
            elif self._read_closed:
                self._state = StreamState.CLOSED
            else:
                # Only write side closed - add WRITE_CLOSED state if needed
                self._state = StreamState.WRITE_CLOSED

        # Send RESET_STREAM in response (QUIC protocol requirement)
        try:
            self._connection._quic.reset_stream(int(self.stream_id), error_code)
            await self._connection._transmit()
            logger.debug(f"Sent RESET_STREAM for stream {self.stream_id}")
        except Exception as e:
            logger.warning(
                f"Could not send RESET_STREAM for stream {self.stream_id}: {e}"
            )

    async def handle_reset(self, error_code: int) -> None:
        """
        Handle stream reset from remote peer.

        Args:
            error_code: QUIC error code from reset frame

        """
        logger.debug(
            f"Stream {self.stream_id} reset by peer with error code {error_code}"
        )

        async with self._state_lock:
            self._state = StreamState.RESET
            self._reset_error_code = error_code

        await self._cleanup_resources()
        self._timeline.record_reset(error_code)
        self._close_event.set()

        # Wake up any pending operations
        self._receive_event.set()
        self._backpressure_event.set()

    async def handle_flow_control_update(self, available_window: int) -> None:
        """
        Handle flow control window updates.

        Args:
            available_window: Available flow control window size

        """
        if available_window > 0:
            self._backpressure_event.set()
            logger.debug(
                f"Stream {self.stream_id} flow control".__add__(
                    f"window updated: {available_window}"
                )
            )
        else:
            self._backpressure_event = trio.Event()  # Reset to blocking state
            logger.debug(f"Stream {self.stream_id} flow control window exhausted")

    def _extract_data_from_buffer(self, n: int) -> bytes:
        """Extract data from receive buffer with specified limit."""
        if n == -1:
            # Read all available data
            data = bytes(self._receive_buffer)
            self._receive_buffer.clear()
        else:
            # Read up to n bytes
            data = bytes(self._receive_buffer[:n])
            self._receive_buffer = self._receive_buffer[n:]

        return data

    async def _handle_stream_error(self, error: Exception) -> None:
        """Handle errors by resetting the stream."""
        logger.error(f"Stream {self.stream_id} error: {error}")
        await self.reset(error_code=1)  # Generic error code

    def _reserve_memory(self, size: int) -> None:
        """Reserve memory with resource manager."""
        if self._resource_scope:
            try:
                self._resource_scope.reserve_memory(size)
                self._memory_reserved += size
            except Exception as e:
                logger.warning(
                    f"Failed to reserve memory for stream {self.stream_id}: {e}"
                )

    def _release_memory(self, size: int) -> None:
        """Release memory with resource manager."""
        if self._resource_scope and size > 0:
            try:
                self._resource_scope.release_memory(size)
                self._memory_reserved = max(0, self._memory_reserved - size)
            except Exception as e:
                logger.warning(
                    f"Failed to release memory for stream {self.stream_id}: {e}"
                )

    async def _cleanup_resources(self) -> None:
        """Clean up stream resources."""
        # Release all reserved memory
        if self._memory_reserved > 0:
            self._release_memory(self._memory_reserved)

        # Clear receive buffer
        async with self._receive_buffer_lock:
            self._receive_buffer.clear()

        # Release resource scope if present
        if self._resource_scope and hasattr(self._resource_scope, "done"):
            try:
                self._resource_scope.done()
            except Exception as e:
                logger.warning(f"Error releasing resource scope: {e}")
            self._resource_scope = None

        # Remove from connection's stream registry
        self._connection._remove_stream(self._stream_id)

        logger.debug(f"Stream {self.stream_id} resources cleaned up")

    # Abstact implementations

    def get_remote_address(self) -> tuple[str, int]:
        return self._remote_addr

    async def __aenter__(self) -> "QUICStream":
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager and close the stream."""
        logger.debug("Exiting the context and closing the stream")
        await self.close()

    def set_deadline(self, ttl: int) -> bool:
        """
        Set a deadline for the stream. QUIC does not support deadlines natively,
        so this method always returns False to indicate the operation is unsupported.

        :param ttl: Time-to-live in seconds (ignored).
        :return: False, as deadlines are not supported.
        """
        raise NotImplementedError("QUIC does not support setting read deadlines")

    # String representation for debugging

    def __repr__(self) -> str:
        return (
            f"QUICStream(id={self.stream_id}, "
            f"state={self._state.value}, "
            f"direction={self._direction.value}, "
            f"protocol={self._protocol})"
        )

    def __str__(self) -> str:
        return f"QUICStream({self.stream_id})"
