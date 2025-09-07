import logging
import time
from typing import Any

import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException

logger = logging.getLogger(__name__)


class P2PWebSocketConnection(ReadWriteCloser):
    """
    Wraps a WebSocketConnection to provide the raw stream interface
    that libp2p protocols expect.
    """

    def __init__(
        self, ws_connection: Any, ws_context: Any = None, is_secure: bool = False
    ) -> None:
        self._ws_connection = ws_connection
        self._ws_context = ws_context
        self._is_secure = is_secure
        self._read_buffer = b""
        self._read_lock = trio.Lock()
        self._connection_start_time = time.time()
        self._bytes_read = 0
        self._bytes_written = 0
        self._closed = False
        self._close_lock = trio.Lock()

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise IOException("Connection is closed")

        try:
            logger.debug(f"WebSocket writing {len(data)} bytes")
            # Send as a binary WebSocket message
            await self._ws_connection.send_message(data)
            self._bytes_written += len(data)
            logger.debug(f"WebSocket wrote {len(data)} bytes successfully")
        except Exception as e:
            logger.error(f"WebSocket write failed: {e}")
            raise IOException from e

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes (if n is given), else read up to 64KiB.
        This implementation provides byte-level access to WebSocket messages,
        which is required for Noise protocol handshake.
        """
        if self._closed:
            raise IOException("Connection is closed")

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
                        self._bytes_read += len(result)
                        logger.debug(
                            f"WebSocket read returning all buffered data: "
                            f"{len(result)} bytes"
                        )
                        return result
                    else:
                        if len(self._read_buffer) >= n:
                            result = self._read_buffer[:n]
                            self._read_buffer = self._read_buffer[n:]
                            self._bytes_read += len(result)
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
                    self._bytes_read += len(result)
                    logger.debug(
                        f"WebSocket read returning all data: {len(result)} bytes"
                    )
                    return result
                else:
                    if len(self._read_buffer) >= n:
                        result = self._read_buffer[:n]
                        self._read_buffer = self._read_buffer[n:]
                        self._bytes_read += len(result)
                        logger.debug(
                            f"WebSocket read returning exact {len(result)} bytes"
                        )
                        return result
                    else:
                        # This should never happen due to the while loop above
                        result = self._read_buffer
                        self._read_buffer = b""
                        self._bytes_read += len(result)
                        logger.debug(
                            f"WebSocket read returning remaining {len(result)} bytes"
                        )
                        return result

            except Exception as e:
                logger.error(f"WebSocket read failed: {e}")
                raise IOException from e

    async def close(self) -> None:
        """Close the WebSocket connection. This method is idempotent."""
        async with self._close_lock:
            if self._closed:
                return  # Already closed

            try:
                # Close the WebSocket connection
                await self._ws_connection.aclose()
                # Exit the context manager if we have one
                if self._ws_context is not None:
                    await self._ws_context.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"WebSocket close error: {e}")
                # Don't raise here, as close() should be idempotent
            finally:
                self._closed = True

    def conn_state(self) -> dict[str, Any]:
        """
        Return connection state information similar to Go's ConnState() method.

        :return: Dictionary containing connection state information
        """
        current_time = time.time()
        return {
            "transport": "websocket",
            "secure": self._is_secure,
            "connection_duration": current_time - self._connection_start_time,
            "bytes_read": self._bytes_read,
            "bytes_written": self._bytes_written,
            "total_bytes": self._bytes_read + self._bytes_written,
        }

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
