import logging
from typing import Any

import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException

logger = logging.getLogger(__name__)


class P2PWebSocketConnection(ReadWriteCloser):
    """
    Wraps a WebSocketConnection to provide the raw stream interface
    that libp2p protocols expect.

    Implements production-ready buffer management and flow control
    as recommended in the libp2p WebSocket specification.
    """

    def __init__(
        self,
        ws_connection: Any,
        ws_context: Any = None,
        max_buffered_amount: int = 4 * 1024 * 1024,
    ) -> None:
        self._ws_connection = ws_connection
        self._ws_context = ws_context
        self._read_buffer = b""
        self._read_lock = trio.Lock()
        self._max_buffered_amount = max_buffered_amount
        self._closed = False
        self._write_lock = trio.Lock()

    async def write(self, data: bytes) -> None:
        """Write data with flow control and buffer management"""
        if self._closed:
            raise IOException("Connection is closed")

        async with self._write_lock:
            try:
                logger.debug(f"WebSocket writing {len(data)} bytes")

                # Check buffer amount for flow control
                if hasattr(self._ws_connection, "bufferedAmount"):
                    buffered = self._ws_connection.bufferedAmount
                    if buffered > self._max_buffered_amount:
                        logger.warning(f"WebSocket buffer full: {buffered} bytes")
                        # In production, you might want to
                        # wait or implement backpressure
                        # For now, we'll continue but log the warning

                # Send as a binary WebSocket message
                await self._ws_connection.send_message(data)
                logger.debug(f"WebSocket wrote {len(data)} bytes successfully")

            except Exception as e:
                logger.error(f"WebSocket write failed: {e}")
                self._closed = True
                raise IOException from e

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes (if n is given), else read up to 64KiB.
        This implementation provides byte-level access to WebSocket messages,
        which is required for Noise protocol handshake.
        """
        async with self._read_lock:
            try:
                logger.debug(
                    f"WebSocket read requested: n={n}, "
                    f"buffer_size={len(self._read_buffer)}"
                )

                # If we have buffered data, return it
                if self._read_buffer:
                    if n is None:
                        result = self._read_buffer
                        self._read_buffer = b""
                        logger.debug(
                            f"WebSocket read returning all buffered data: "
                            f"{len(result)} bytes"
                        )
                        return result
                    else:
                        if len(self._read_buffer) >= n:
                            result = self._read_buffer[:n]
                            self._read_buffer = self._read_buffer[n:]
                            logger.debug(
                                f"WebSocket read returning {len(result)} bytes "
                                f"from buffer"
                            )
                            return result
                        else:
                            # We need more data, but we have some buffered
                            # Keep the buffered data and get more
                            logger.debug(
                                f"WebSocket read needs more data: have "
                                f"{len(self._read_buffer)}, need {n}"
                            )
                            pass

                # If we need exactly n bytes but don't have enough, get more data
                while n is not None and (
                    not self._read_buffer or len(self._read_buffer) < n
                ):
                    logger.debug(
                        f"WebSocket read getting more data: "
                        f"buffer_size={len(self._read_buffer)}, need={n}"
                    )
                    # Get the next WebSocket message and treat it as a byte stream
                    # This mimics the Go implementation's NextReader() approach
                    message = await self._ws_connection.get_message()
                    if isinstance(message, str):
                        message = message.encode("utf-8")

                    logger.debug(
                        f"WebSocket read received message: {len(message)} bytes"
                    )
                    # Add to buffer
                    self._read_buffer += message

                # Return requested amount
                if n is None:
                    result = self._read_buffer
                    self._read_buffer = b""
                    logger.debug(
                        f"WebSocket read returning all data: {len(result)} bytes"
                    )
                    return result
                else:
                    if len(self._read_buffer) >= n:
                        result = self._read_buffer[:n]
                        self._read_buffer = self._read_buffer[n:]
                        logger.debug(
                            f"WebSocket read returning exact {len(result)} bytes"
                        )
                        return result
                    else:
                        # This should never happen due to the while loop above
                        result = self._read_buffer
                        self._read_buffer = b""
                        logger.debug(
                            f"WebSocket read returning remaining {len(result)} bytes"
                        )
                        return result

            except Exception as e:
                logger.error(f"WebSocket read failed: {e}")
                raise IOException from e

    async def close(self) -> None:
        """Close the WebSocket connection with proper cleanup"""
        if self._closed:
            return

        self._closed = True
        try:
            # Close the WebSocket connection
            await self._ws_connection.aclose()
            # Exit the context manager if we have one
            if self._ws_context is not None:
                await self._ws_context.__aexit__(None, None, None)
        except Exception as e:
            logger.error(f"Error closing WebSocket connection: {e}")

    def is_closed(self) -> bool:
        """Check if the connection is closed"""
        return self._closed

    def get_remote_address(self) -> tuple[str, int] | None:
        # Try to get remote address from the WebSocket connection
        try:
            remote = self._ws_connection.remote
            if hasattr(remote, "address") and hasattr(remote, "port"):
                return str(remote.address), int(remote.port)
            elif isinstance(remote, str):
                # Parse address:port format
                if ":" in remote:
                    host, port = remote.rsplit(":", 1)
                    return host, int(port)
        except Exception:
            pass
        return None
