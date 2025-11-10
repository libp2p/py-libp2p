from enum import (
    Enum,
    auto,
)
import logging
from typing import (
    TYPE_CHECKING,
)

import trio

from libp2p.abc import (
    IMuxedStream,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamError,
    MuxedStreamReset,
)
from libp2p.transport.quic.exceptions import QUICStreamClosedError, QUICStreamResetError

if TYPE_CHECKING:
    from libp2p.network.connection.swarm_connection import SwarmConn


from .exceptions import (
    StreamClosed,
    StreamEOF,
    StreamError,
    StreamReset,
)


class StreamState(Enum):
    INIT = auto()
    OPEN = auto()
    CLOSE_READ = auto()
    CLOSE_WRITE = auto()
    CLOSE_BOTH = auto()
    RESET = auto()
    ERROR = auto()


class NetStream(INetStream):
    """
    A Network stream implementation with comprehensive state management.

    NetStream wraps a muxed stream and provides proper state tracking, resource cleanup,
    and event notification capabilities with thread-safe operations.

    State Machine
    _____________

    .. code:: markdown

        [INIT] → OPEN → CLOSE_READ → CLOSE_BOTH → [CLEANUP]
                      ↓         ↗           ↗
                 CLOSE_WRITE → ←          ↗
                      ↓                   ↗
                    RESET ────────────────┘
                      ↓
                    ERROR ────────────────┘

    State Transitions
    _________________
        - INIT → OPEN: Stream establishment
        - OPEN → CLOSE_READ: EOF encountered during read() or explicit close_read()
        - OPEN → CLOSE_WRITE: Explicit close_write() call
        - OPEN → RESET: reset() call or critical stream error
        - OPEN → ERROR: Unexpected error during I/O operations
        - CLOSE_READ → CLOSE_BOTH: Explicit close_write() call
        - CLOSE_WRITE → CLOSE_BOTH: EOF encountered during read()
        - Any state → ERROR: Unrecoverable error condition
        - Any state → RESET: reset() call (for cleanup)

        **Terminal States**: RESET and ERROR are terminal - no further transitions

    Stream States
    _____________
        INIT: Stream is created but not yet established
        OPEN: Stream is established and ready for I/O operations
        CLOSE_READ: Read side is closed, write side may still be open
        CLOSE_WRITE: Write side is closed, read side may still be open
        CLOSE_BOTH: Both sides are closed, stream is terminated
        RESET: Stream was reset by remote peer or locally
        ERROR: Stream encountered an unrecoverable error

    Operation Validity by State
    ___________________________
        OPEN:        read() ✓  write() ✓  close_read() ✓  close_write() ✓  reset() ✓
        CLOSE_READ:  read() ✗  write() ✓  close_read() ✓  close_write() ✓  reset() ✓
        CLOSE_WRITE: read() ✓  write() ✗  close_read() ✓  close_write() ✓  reset() ✓
        CLOSE_BOTH:  read() ✗  write() ✗  close_read() ✓  close_write() ✓  reset() ✓
        RESET:       read() ✗  write() ✗  close_read() ✗  close_write() ✗  reset() ✓
        ERROR:       read() ✗  write() ✗  close_read() ✗  close_write() ✗  reset() ✓

    Thread Safety
    _____________
        All state operations are protected by trio.Lock() for safe concurrent access.
        State checks and modifications are atomic operations preventing race conditions.

    QUIC Compatibility
    __________________
        Half-closed states (CLOSE_READ, CLOSE_WRITE) are essential for QUIC transport
        where streams can independently close read or write sides.

    Error Handling
    ______________
        ERROR state is triggered by unexpected exceptions during I/O operations.
        Known exceptions (EOF, Reset, etc.) are handled gracefully without ERROR state.
        Recovery from ERROR state is possible but not guaranteed.

    :param muxed_stream: The underlying muxed stream
    :param swarm_conn: Optional swarm connection for stream management
    """

    muxed_stream: IMuxedStream
    protocol_id: TProtocol | None

    def __init__(
        self, muxed_stream: IMuxedStream, swarm_conn: "SwarmConn | None"
    ) -> None:
        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None
        self._state = StreamState.INIT
        self.swarm_conn = swarm_conn
        self.logger = logging.getLogger(__name__)

        # Thread safety for state operations (following AkMo3's approach)
        self._state_lock = trio.Lock()

    def get_protocol(self) -> TProtocol | None:
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        """
        self.protocol_id = protocol_id

    @property
    async def state(self) -> StreamState:
        """
        :return: current state of the stream
        """
        async with self._state_lock:
            return self._state

    async def set_state(self, state: StreamState) -> None:
        """
        Set the current state of the stream.

        :param state: new state of the stream
        """
        async with self._state_lock:
            old_state = self._state
            self._state = state

            # Log state transition for debugging and monitoring
            self.logger.debug(
                f"Stream state transition: {old_state.name} → {state.name}"
            )

            # Log important state changes at info level
            if state in [StreamState.ERROR, StreamState.RESET, StreamState.CLOSE_BOTH]:
                self.logger.info(
                    f"Stream entered {state.name} state (from {old_state.name})"
                )

    async def read(self, n: int | None = None) -> bytes:
        """
        Read from stream.

        :param n: number of bytes to read
        :return: Bytes read from the stream
        """
        # Check state atomically to prevent race conditions
        async with self._state_lock:
            if self._state == StreamState.ERROR:
                raise StreamError("Cannot read from stream; stream is in error state")
            elif self._state == StreamState.RESET:
                raise StreamReset("Cannot read from stream; stream is reset")
            elif self._state == StreamState.CLOSE_READ:
                # Only block reads if explicitly closed for reading
                # Allow reads from streams that might still have buffered data
                pass
            # Note: Allow reading from CLOSE_BOTH state - buffered data may exist

        # Perform I/O operation without holding the lock to prevent deadlocks
        try:
            return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
            # Handle state transitions when EOF is encountered
            async with self._state_lock:
                if self._state == StreamState.CLOSE_WRITE:
                    self._state = StreamState.CLOSE_BOTH
                elif self._state == StreamState.OPEN:
                    self._state = StreamState.CLOSE_READ
            raise StreamEOF() from error
        except (
            MuxedStreamReset,
            QUICStreamClosedError,
            QUICStreamResetError,
        ) as error:
            async with self._state_lock:
                self._state = StreamState.RESET
            raise StreamReset() from error
        except Exception as error:
            # Only set ERROR state for truly unexpected errors
            # Known exceptions (MuxedStreamEOF, MuxedStreamReset, etc.)
            # are handled above
            if not isinstance(
                error,
                (
                    MuxedStreamEOF,
                    MuxedStreamReset,
                    QUICStreamClosedError,
                    QUICStreamResetError,
                    StreamEOF,
                    StreamReset,
                    StreamClosed,
                    ValueError,  # QUIC stream errors
                ),
            ):
                async with self._state_lock:
                    self._state = StreamState.ERROR
                raise StreamError(f"Read operation failed: {error}") from error
            # Re-raise known exceptions as-is
            raise

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :param data: bytes to write
        """
        # Check state atomically to prevent race conditions
        async with self._state_lock:
            if self._state == StreamState.ERROR:
                raise StreamError("Cannot write to stream; stream is in error state")
            elif self._state == StreamState.RESET:
                raise StreamReset("Cannot write to stream; stream is reset")
            elif self._state in [StreamState.CLOSE_WRITE, StreamState.CLOSE_BOTH]:
                raise StreamClosed("Cannot write to stream; closed for writing")

        # Perform I/O operation without holding the lock to prevent deadlocks
        try:
            await self.muxed_stream.write(data)
        except (
            MuxedStreamClosed,
            QUICStreamClosedError,
            QUICStreamResetError,
        ) as error:
            async with self._state_lock:
                if self._state == StreamState.CLOSE_READ:
                    self._state = StreamState.CLOSE_BOTH
                elif self._state == StreamState.OPEN:
                    self._state = StreamState.CLOSE_WRITE
            raise StreamClosed() from error
        except (MuxedStreamReset, MuxedStreamError) as error:
            async with self._state_lock:
                self._state = StreamState.RESET
            raise StreamReset() from error
        except Exception as error:
            # Only set ERROR state for truly unexpected errors
            # Known exceptions are handled above
            if not isinstance(
                error,
                (
                    MuxedStreamClosed,
                    MuxedStreamReset,
                    MuxedStreamError,
                    QUICStreamClosedError,
                    QUICStreamResetError,
                    StreamClosed,
                    StreamReset,
                    ValueError,  # QUIC stream errors
                ),
            ):
                async with self._state_lock:
                    self._state = StreamState.ERROR
                raise StreamError(f"Write operation failed: {error}") from error
            # Re-raise known exceptions as-is
            raise

    async def close(self) -> None:
        """Close stream completely and clean up resources."""
        await self.muxed_stream.close()
        await self.set_state(StreamState.CLOSE_BOTH)
        await self.remove()

    async def close_read(self) -> None:
        """Close the stream for reading only."""
        async with self._state_lock:
            if self._state == StreamState.ERROR:
                raise StreamError(
                    "Cannot close read on stream; stream is in error state"
                )
            elif self._state == StreamState.OPEN:
                self._state = StreamState.CLOSE_READ
            elif self._state == StreamState.CLOSE_WRITE:
                self._state = StreamState.CLOSE_BOTH
                await self.remove()

    async def close_write(self) -> None:
        """Close the stream for writing only."""
        async with self._state_lock:
            if self._state == StreamState.ERROR:
                raise StreamError(
                    "Cannot close write on stream; stream is in error state"
                )

        await self.muxed_stream.close()

        async with self._state_lock:
            if self._state == StreamState.OPEN:
                self._state = StreamState.CLOSE_WRITE
            elif self._state == StreamState.CLOSE_READ:
                self._state = StreamState.CLOSE_BOTH
                await self.remove()

    async def reset(self) -> None:
        """Reset stream."""
        # Allow reset even from ERROR state for cleanup purposes
        try:
            await self.muxed_stream.reset()
        except Exception:
            # If reset fails, we still want to mark the stream as reset
            # This allows cleanup to proceed even if the underlying stream is broken
            pass
        async with self._state_lock:
            self._state = StreamState.RESET
        await self.remove()

    async def remove(self) -> None:
        """
        Remove the stream from the connection and notify swarm that stream was closed.
        """
        if self.swarm_conn is not None:
            self.swarm_conn.remove_stream(self)
            await self.swarm_conn.swarm.notify_closed_stream(self)

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

    async def is_operational(self) -> bool:
        """
        Check if stream is in an operational state.

        :return: True if stream can perform I/O operations
        """
        async with self._state_lock:
            return self._state not in [
                StreamState.ERROR,
                StreamState.RESET,
                StreamState.CLOSE_BOTH,
            ]
