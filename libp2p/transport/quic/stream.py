"""
QUIC Stream implementation
"""

from types import (
    TracebackType,
)

import trio

from libp2p.abc import (
    IMuxedStream,
)

from .connection import (
    QUICConnection,
)
from .exceptions import (
    QUICStreamError,
)


class QUICStream(IMuxedStream):
    """
    Basic QUIC stream implementation for Module 1.

    This is a minimal implementation to make Module 1 self-contained.
    Will be moved to a separate stream.py module in Module 3.
    """

    def __init__(
        self, connection: "QUICConnection", stream_id: int, is_initiator: bool
    ):
        self._connection = connection
        self._stream_id = stream_id
        self._is_initiator = is_initiator
        self._closed = False

        # Trio synchronization
        self._receive_buffer = bytearray()
        self._receive_event = trio.Event()
        self._close_event = trio.Event()

    async def read(self, n: int = -1) -> bytes:
        """Read data from the stream."""
        if self._closed:
            raise QUICStreamError("Stream is closed")

        # Wait for data if buffer is empty
        while not self._receive_buffer and not self._closed:
            await self._receive_event.wait()
            self._receive_event = trio.Event()  # Reset for next read

        if n == -1:
            data = bytes(self._receive_buffer)
            self._receive_buffer.clear()
        else:
            data = bytes(self._receive_buffer[:n])
            self._receive_buffer = self._receive_buffer[n:]

        return data

    async def write(self, data: bytes) -> None:
        """Write data to the stream."""
        if self._closed:
            raise QUICStreamError("Stream is closed")

        # Send data using the underlying QUIC connection
        self._connection._quic.send_stream_data(self._stream_id, data)
        await self._connection._transmit()

    async def close(self, error_code: int = 0) -> None:
        """Close the stream."""
        if self._closed:
            return

        self._closed = True

        # Close the QUIC stream
        self._connection._quic.reset_stream(self._stream_id, error_code)
        await self._connection._transmit()

        # Remove from connection's stream list
        self._connection._streams.pop(self._stream_id, None)

        self._close_event.set()

    def is_closed(self) -> bool:
        """Check if stream is closed."""
        return self._closed

    async def handle_data_received(self, data: bytes, end_stream: bool) -> None:
        """Handle data received from the QUIC connection."""
        if self._closed:
            return

        self._receive_buffer.extend(data)
        self._receive_event.set()

        if end_stream:
            await self.close()

    async def handle_reset(self, error_code: int) -> None:
        """Handle stream reset."""
        self._closed = True
        self._close_event.set()

    def set_deadline(self, ttl: int) -> bool:
        """
        Set the deadline
        """
        raise NotImplementedError("Yamux does not support setting read deadlines")

    async def reset(self) -> None:
        """
        Reset the stream
        """
        self.handle_reset(0)

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._connection._remote_addr

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
        await self.close()
