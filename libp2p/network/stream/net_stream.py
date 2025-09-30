from enum import (
    Enum,
    auto,
)
import logging
from typing import (
    TYPE_CHECKING,
)

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
    def state(self) -> StreamState:
        """
        :return: current state of the stream
        """
        return self._state

    def set_state(self, state: StreamState) -> None:
        """
        Set the current state of the stream.

        :param state: new state of the stream
        """
        old_state = self._state
        self._state = state

        # Log state transition for debugging and monitoring
        self.logger.debug(f"Stream state transition: {old_state.name} → {state.name}")

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
        if self.state == StreamState.ERROR:
            raise StreamError("Cannot read from stream; stream is in error state")
        elif self.state == StreamState.RESET:
            raise StreamReset("Cannot read from stream; stream is reset")
        elif self.state == StreamState.CLOSE_READ:
            raise StreamClosed("Cannot read from stream; closed for reading")
        # Note: Allow reading from CLOSE_BOTH state - there might still be buffered data

        try:
            return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
            # Handle state transitions when EOF is encountered
            if self.state == StreamState.CLOSE_WRITE:
                self.set_state(StreamState.CLOSE_BOTH)
            elif self.state == StreamState.OPEN:
                self.set_state(StreamState.CLOSE_READ)
            raise StreamEOF() from error
        except (MuxedStreamReset, QUICStreamClosedError, QUICStreamResetError) as error:
            self.set_state(StreamState.RESET)
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
                self.set_state(StreamState.ERROR)
                raise StreamError(f"Read operation failed: {error}") from error
            # Re-raise known exceptions as-is
            raise

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :param data: bytes to write
        """
        try:
            if self.state == StreamState.ERROR:
                raise StreamError("Cannot write to stream; stream is in error state")
            elif self.state == StreamState.RESET:
                raise StreamReset("Cannot write to stream; stream is reset")
            elif self.state in [StreamState.CLOSE_WRITE, StreamState.CLOSE_BOTH]:
                raise StreamClosed("Cannot write to stream; closed for writing")
            else:
                await self.muxed_stream.write(data)
        except (
            MuxedStreamClosed,
            QUICStreamClosedError,
            QUICStreamResetError,
        ) as error:
            if self.state == StreamState.CLOSE_READ:
                self.set_state(StreamState.CLOSE_BOTH)
            elif self.state == StreamState.OPEN:
                self.set_state(StreamState.CLOSE_WRITE)
            raise StreamClosed() from error
        except (MuxedStreamReset, MuxedStreamError) as error:
            self.set_state(StreamState.RESET)
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
                self.set_state(StreamState.ERROR)
                raise StreamError(f"Write operation failed: {error}") from error
            # Re-raise known exceptions as-is
            raise

    async def close(self) -> None:
        """Close stream completely and clean up resources."""
        await self.muxed_stream.close()
        self.set_state(StreamState.CLOSE_BOTH)
        await self.remove()

    async def close_read(self) -> None:
        """Close the stream for reading only."""
        if self.state == StreamState.ERROR:
            raise StreamError("Cannot close read on stream; stream is in error state")
        elif self.state == StreamState.OPEN:
            self.set_state(StreamState.CLOSE_READ)
        elif self.state == StreamState.CLOSE_WRITE:
            self.set_state(StreamState.CLOSE_BOTH)
            await self.remove()

    async def close_write(self) -> None:
        """Close the stream for writing only."""
        if self.state == StreamState.ERROR:
            raise StreamError("Cannot close write on stream; stream is in error state")
        await self.muxed_stream.close()
        if self.state == StreamState.OPEN:
            self.set_state(StreamState.CLOSE_WRITE)
        elif self.state == StreamState.CLOSE_READ:
            self.set_state(StreamState.CLOSE_BOTH)
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
        self.set_state(StreamState.RESET)
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

    def is_operational(self) -> bool:
        """
        Check if stream is in an operational state.

        :return: True if stream can perform I/O operations
        """
        return self.state not in [
            StreamState.ERROR,
            StreamState.RESET,
            StreamState.CLOSE_BOTH,
        ]

    async def recover_from_error(self) -> None:
        """
        Attempt to recover from error state.

        This method attempts to reset the underlying muxed stream
        and transition back to OPEN state if successful.
        """
        if self.state != StreamState.ERROR:
            return

        try:
            # Attempt to reset the underlying muxed stream
            await self.muxed_stream.reset()
            self.set_state(StreamState.OPEN)
        except Exception:
            # If recovery fails, keep ERROR state
            # The stream remains in ERROR state
            pass

    def get_state_transition_summary(self) -> str:
        """
        Get a summary of the stream's current state and operational status.

        :return: Human-readable summary of stream state
        """
        if self.is_operational():
            return f"Stream is operational in {self.state.name} state"
        else:
            return f"Stream is non-operational in {self.state.name} state"

    def get_valid_transitions(self) -> list[StreamState]:
        """
        Get valid next states from the current state.

        :return: List of valid next states
        """
        valid_transitions = {
            StreamState.INIT: [StreamState.OPEN, StreamState.ERROR],
            StreamState.OPEN: [
                StreamState.CLOSE_READ,
                StreamState.CLOSE_WRITE,
                StreamState.RESET,
                StreamState.ERROR,
            ],
            StreamState.CLOSE_READ: [StreamState.CLOSE_BOTH, StreamState.ERROR],
            StreamState.CLOSE_WRITE: [StreamState.CLOSE_BOTH, StreamState.ERROR],
            StreamState.RESET: [StreamState.ERROR],  # RESET is terminal
            StreamState.CLOSE_BOTH: [StreamState.ERROR],  # CLOSE_BOTH is terminal
            StreamState.ERROR: [],  # ERROR is terminal
        }
        return valid_transitions.get(self.state, [])

    def get_state_transition_documentation(self) -> str:
        """
        Get comprehensive documentation about stream state transitions.

        :return: Documentation string explaining state transitions
        """
        return """
Stream State Lifecycle Documentation:

INIT: Stream is created but not yet established
OPEN: Stream is established and ready for I/O operations
CLOSE_READ: Read side is closed, write side may still be open
CLOSE_WRITE: Write side is closed, read side may still be open
CLOSE_BOTH: Both sides are closed, stream is terminated
RESET: Stream was reset by remote peer or locally
ERROR: Stream encountered an unrecoverable error

State Transitions:
- INIT → OPEN: Stream establishment
- OPEN → CLOSE_READ/CLOSE_WRITE: Partial closure
- OPEN → RESET: Stream reset
- OPEN → ERROR: Error condition
- CLOSE_READ/CLOSE_WRITE → CLOSE_BOTH: Complete closure
- Any → ERROR: Unrecoverable error

Current State: {current_state}
Valid Next States: {valid_states}
Operational Status: {operational}
        """.format(
            current_state=self.state.name,
            valid_states=", ".join([s.name for s in self.get_valid_transitions()]),
            operational="Yes" if self.is_operational() else "No",
        ).strip()
