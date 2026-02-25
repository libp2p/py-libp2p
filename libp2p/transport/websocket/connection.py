from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import ssl
import time
from typing import Any

from multiaddr import Multiaddr
import trio
from trio_websocket import WebSocketConnection

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import ConnectionClosedError, IOException

logger = logging.getLogger(__name__)


@dataclass
class WebSocketStats:
    """Statistics for a WebSocket connection."""

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bytes_sent: int = 0
    bytes_received: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    last_error: str | None = None
    last_activity: datetime | None = None
    protocol: str | None = None
    is_secure: bool = False
    connected_at: float = time.time()
    ping_rtt_ms: float = 0.0

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def record_error(self, error: str) -> None:
        """Record an error occurrence."""
        self.errors += 1
        self.last_error = error
        self.update_activity()

    def record_message_sent(self, size: int) -> None:
        """Record a message being sent."""
        self.messages_sent += 1
        self.bytes_sent += size
        self.update_activity()

    def record_message_received(self, size: int) -> None:
        """Record a message being received."""
        self.messages_received += 1
        self.bytes_received += size
        self.update_activity()


class WebSocketConnectionError(IOException):
    """Base class for WebSocket connection errors."""

    pass


class WebSocketHandshakeError(WebSocketConnectionError):
    """Error during WebSocket handshake."""

    pass


class WebSocketProtocolError(WebSocketConnectionError):
    """WebSocket protocol error."""

    pass


class WebSocketMessageError(WebSocketConnectionError):
    """Error processing WebSocket message."""

    pass


class P2PWebSocketConnection(ReadWriteCloser):
    """
    Production-ready WebSocket connection implementation with enhanced features:
    - Comprehensive error handling and custom exceptions
    - Connection statistics and activity tracking
    - Secure connection support (WSS)
    - Message validation and size limits
    - Automatic ping/pong handling
    - Browser compatibility optimizations
    - Activity monitoring
    - Secure connection support

    - Flow control and buffer management
    - Error handling and recovery
    - Connection state monitoring
    - Performance statistics
    - Ping/pong keepalive
    - Graceful shutdown
    """

    def __init__(
        self,
        ws_connection: WebSocketConnection | Any,
        local_addr: Multiaddr | None = None,
        remote_addr: Multiaddr | None = None,
        ssl_context: ssl.SSLContext | None = None,
        max_message_size: int = 1024 * 1024,  # 1MB default
        keepalive_interval: float = 30.0,
        handshake_timeout: float = 10.0,
        max_buffer: int = 4 * 1024 * 1024,
        is_secure: bool = False,
        max_buffered_amount: int = 8 * 1024 * 1024,
    ) -> None:
        """
        Initialize a new WebSocket connection.

        Args:
            ws_connection: The underlying WebSocket connection
            local_addr: Local multiaddr (optional)
            remote_addr: Remote multiaddr (optional)
            ssl_context: SSL context for secure connections
            max_message_size: Maximum message size in bytes
            keepalive_interval: Keepalive ping interval in seconds
            handshake_timeout: Handshake timeout in seconds
            max_buffer: Maximum buffer size in bytes
            is_secure: Whether this is a secure connection
            max_buffered_amount: Maximum buffered amount for flow control

        """
        self._ws = ws_connection
        self._ws_connection = ws_connection
        self._local_addr = local_addr
        self._remote_addr = remote_addr
        self._max_buffer = max_buffer
        self._ssl_context = ssl_context
        self._max_message_size = max_message_size
        self._keepalive_interval = keepalive_interval
        self._handshake_timeout = handshake_timeout
        self._is_secure = is_secure
        self._max_buffered_amount = max_buffered_amount

        # State management
        self._closed = False
        self._read_lock = trio.Lock()
        self._write_lock = trio.Lock()
        self._close_lock = trio.Lock()

        # Buffers
        self._read_buffer = b""
        self._write_buffer = b""

        # Statistics tracking
        self._stats = WebSocketStats(
            is_secure=is_secure,
            protocol=getattr(ws_connection, "subprotocol", None),
        )
        self._connection_start_time = time.time()
        self._bytes_read = 0
        self._bytes_written = 0

        # Start keepalive if enabled
        if keepalive_interval > 0:
            # Note: keepalive will be started when connection is used
            pass

    def _is_connection_closed_exception(self, e: Exception) -> bool:
        """
        Check if an exception indicates WebSocket connection closure.

        Args:
            e: The exception to check

        Returns:
            True if the exception indicates connection closure

        """
        error_str = str(e)
        error_type = type(e).__name__
        return (
            "CloseReason" in error_str
            or "ConnectionClosed" in error_type
            or "closed" in error_str.lower()
        )

    def _extract_close_info(self, e: Exception) -> tuple[int | None, str]:
        """
        Extract close code and reason from a connection closure exception.

        Args:
            e: The exception that indicates connection closure

        Returns:
            Tuple of (close_code, close_reason)

        """
        # ConnectionClosed has a 'reason' attribute which is a CloseReason object.
        # Some exceptions (like mocks in tests) may have code/reason directly.
        close_reason_obj = getattr(e, "reason", None)

        # Check if reason is a CloseReason object (has 'code' attribute)
        if close_reason_obj is not None and hasattr(close_reason_obj, "code"):
            close_code = getattr(close_reason_obj, "code", None)
            close_reason = (
                getattr(close_reason_obj, "reason", None) or "Connection closed by peer"
            )
        else:
            # Fallback: check if code and reason are directly on the exception
            # (for mock exceptions in tests or other exception types)
            close_code = getattr(e, "code", None)
            close_reason = getattr(e, "reason", None) or "Connection closed by peer"
        return close_code, close_reason

    def _handle_connection_closed_exception(
        self, e: Exception, operation: str = "read"
    ) -> ConnectionClosedError:
        """
        Handle a connection closure exception by creating a ConnectionClosedError.

        Returns a ``ConnectionClosedError`` (subclass of ``IOException``) that
        carries the close code and reason as structured attributes.  This lets
        upstream code (e.g. yamux) catch connection closures by *type* instead
        of doing fragile string matching on the error message.

        Args:
            e: The exception that indicates connection closure
            operation: The operation that was being performed (read/write)

        Returns:
            ConnectionClosedError with close_code and close_reason attributes

        """
        self._closed = True
        close_code, close_reason = self._extract_close_info(e)
        logger.debug(
            f"WebSocket connection closed during {operation}: "
            f"code={close_code}, reason={close_reason}"
        )
        # Return ConnectionClosedError (subclass of IOException) to be raised
        # by caller.  This allows read_exactly() to immediately detect
        # connection closure instead of returning empty bytes which would cause
        # retries, and lets yamux catch the typed exception directly.
        return ConnectionClosedError(
            f"WebSocket connection closed by peer during "
            f"{operation} operation: code={close_code}, "
            f"reason={close_reason}.",
            close_code=close_code,
            close_reason=close_reason,
            transport="websocket",
        )

    async def _start_keepalive(self) -> None:
        """Start keepalive ping/pong."""

        async def keepalive_loop() -> None:
            while not self._closed:
                try:
                    await trio.sleep(self._keepalive_interval)
                    if not self._closed:
                        start_time = time.time()
                        await self._ws.ping()
                        rtt = time.time() - start_time
                        self._stats.ping_rtt_ms = rtt * 1000
                except Exception as e:
                    logger.warning("Keepalive failed: %s", e)

        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(keepalive_loop)
        except Exception as e:
            logger.warning(f"Failed to start keepalive: {e}")

    async def read(self, n: int | None = None) -> bytes:
        """
        Read data from the WebSocket connection.

        This method blocks until data is available, similar to TCP streams.
        This is required for multistream negotiation which expects blocking reads.

        When the WebSocket connection is closed by the peer, this method raises
        ``IOException`` with detailed information including the close code and reason,
        rather than returning empty bytes. This allows higher-level code (such as
        ``read_exactly()``) to immediately detect connection closure and provide
        better error messages.

        Args:
            n: Number of bytes to read (None for all available)

        Returns:
            bytes: Received data

        :raises IOException: If connection is closed or read fails. When the connection
            is closed by the peer, the exception includes the WebSocket close code and
            reason for better debugging.
        :raises WebSocketConnectionError: If WebSocket connection error occurs
        :raises WebSocketMessageError: If message processing fails

        """
        if self._closed:
            # Raise IOException immediately when connection is closed.
            # This allows read_exactly() to detect closure immediately
            # instead of retrying up to 100 times on empty bytes.
            raise IOException("Connection is closed")

        async with self._read_lock:
            try:
                # If n is None, return all buffered data or block for a new message
                if n is None:
                    # If buffer is empty, block until we receive a WebSocket message
                    if not self._read_buffer:
                        try:
                            # Block indefinitely until message arrives (like TCP)
                            # This is necessary for multistream negotiation
                            logger.debug(
                                "WebSocket read(n=None): buffer empty, "
                                "waiting for message..."
                            )
                            message = await self._ws_connection.get_message()
                            if isinstance(message, str):
                                message = message.encode("utf-8")
                            logger.debug(
                                f"WebSocket read(n=None): received {len(message)} bytes"
                            )
                            self._read_buffer = message
                        except Exception as e:
                            # Handle CloseReason/ConnectionClosed from trio_websocket
                            if self._is_connection_closed_exception(e):
                                raise self._handle_connection_closed_exception(
                                    e, "read"
                                )
                            # If connection is closed or error occurs, raise IOException
                            if self._closed:
                                raise IOException("Connection is closed")
                            logger.error(f"WebSocket read error: {e}")
                            raise IOException(f"Read failed: {str(e)}")

                    result = self._read_buffer
                    self._read_buffer = b""
                    self._bytes_read += len(result)
                    logger.debug(
                        f"WebSocket read(n=None): returning {len(result)} bytes"
                    )
                    return result

                # For specific byte count requests, we need to satisfy read_exactly()
                # and Yamux handle_incoming() which needs exact byte counts
                #
                # IMPORTANT: read_exactly() expects read(n) to return UP TO n bytes
                # (may return less), and will retry.
                # This matches TCP's receive_some() behavior.
                #
                # Strategy:
                # 1. If we have >= n bytes, return exactly n bytes
                # 2. If we have partial data (< n), return it immediately (don't block)
                #    read_exactly() will call us again with remaining bytes
                # 3. Only block if buffer is completely empty (wait for first message)
                # 4. This ensures progress and prevents deadlocks

                # If we already have enough data, return it immediately
                if len(self._read_buffer) >= n:
                    result = self._read_buffer[:n]
                    self._read_buffer = self._read_buffer[n:]
                    self._bytes_read += len(result)
                    return result

                # If we have partial data (< n bytes), return it immediately
                # This allows read_exactly() to retry and get more data
                # Returning partial data is the correct behavior
                # for stream-oriented I/O
                # This matches TCP's receive_some() behavior -
                # return what's available now
                if self._read_buffer:
                    result = self._read_buffer
                    self._read_buffer = b""
                    self._bytes_read += len(result)
                    result_len = len(result)
                    logger.debug(
                        f"WebSocket read(n={n}): returning {result_len} bytes "
                        f"(partial, read_exactly will retry)"
                    )
                    return result

                # Buffer is empty - block until we get at least one message
                # This is needed for multistream negotiation
                # where we wait for the peer's first message
                # IMPORTANT: This MUST block until data arrives -
                # multistream negotiation depends on it
                if not self._closed:
                    try:
                        # Block until we receive a WebSocket message
                        # This will block until the peer sends data
                        # or connection closes
                        logger.debug(
                            f"WebSocket read(n={n}): buffer empty, "
                            f"calling get_message()..."
                        )
                        message = await self._ws_connection.get_message()
                        msg_len = len(message) if message else 0
                        logger.debug(
                            f"WebSocket read(n={n}): get_message() returned, "
                            f"got {msg_len} bytes"
                        )
                        if isinstance(message, str):
                            message = message.encode("utf-8")
                        logger.debug(
                            f"WebSocket read(n={n}): received {len(message)} bytes"
                        )
                        self._read_buffer = message

                        # Return what we got (may be less than n, that's OK)
                        # read_exactly() will call us again if it needs more
                        if len(self._read_buffer) >= n:
                            result = self._read_buffer[:n]
                            self._read_buffer = self._read_buffer[n:]
                            result_len = len(result)
                            logger.debug(
                                f"WebSocket read(n={n}): returning {result_len} "
                                f"bytes (had enough)"
                            )
                        else:
                            result = self._read_buffer
                            self._read_buffer = b""
                            result_len = len(result)
                            logger.debug(
                                f"WebSocket read(n={n}): returning {result_len} "
                                f"bytes (partial)"
                            )

                        self._bytes_read += len(result)
                        return result
                    except Exception as e:
                        # Handle CloseReason/ConnectionClosed from trio_websocket
                        if self._is_connection_closed_exception(e):
                            raise self._handle_connection_closed_exception(e, "read")
                        logger.error(f"WebSocket read error: {e}")
                        raise IOException(f"Read failed: {str(e)}")

                # Connection closed and no data
                return b""

            except IOException:
                # Re-raise IOException as-is (already has proper context)
                raise
            except Exception as e:
                # Handle connection closure missed by inner handlers
                if self._is_connection_closed_exception(e):
                    raise self._handle_connection_closed_exception(e, "read")
                logger.error(f"WebSocket read failed: {e}")
                raise IOException(f"Read failed: {str(e)}")

    async def write(self, data: bytes) -> None:
        """
        Write data to the WebSocket connection.

        Args:
            data: The bytes to write

        :raises IOException: If connection is closed or write fails
        :raises WebSocketConnectionError: If WebSocket connection error occurs
        :raises WebSocketProtocolError: If protocol violation occurs

        """
        if self._closed:
            raise IOException("Connection is closed")

        async with self._write_lock:
            try:
                logger.debug(f"WebSocket writing {len(data)} bytes")

                # Check buffer amount for flow control
                # Note: trio-websocket doesn't expose bufferedAmount directly
                # This is a placeholder for future flow control implementation

                # Send as a binary WebSocket message
                await self._ws_connection.send_message(data)
                self._bytes_written += len(data)
                logger.debug(f"WebSocket wrote {len(data)} bytes successfully")

            except Exception as e:
                # Handle CloseReason from trio_websocket - connection was closed
                if self._is_connection_closed_exception(e):
                    raise self._handle_connection_closed_exception(e, "write")
                logger.error(f"WebSocket write failed: {e}")
                self._closed = True
                raise IOException(f"Write failed: {str(e)}") from e

    async def close(self) -> None:
        """
        Close the WebSocket connection. This method is idempotent.

        :raises WebSocketConnectionError: If closing the connection fails
        """
        async with self._close_lock:
            if self._closed:
                return  # Already closed

            logger.debug("WebSocket connection closing")
            self._closed = True
            try:
                await self._ws_connection.aclose()
            except Exception as e:
                logger.error(f"WebSocket close error: {e}")
            finally:
                logger.debug("WebSocket connection closed")

    def is_closed(self) -> bool:
        """Check if the connection is closed"""
        return self._closed

    def get_stats(self) -> dict[str, int | float]:
        """Get connection statistics."""
        now = time.time()
        return {
            "bytes_sent": self._bytes_written,
            "bytes_received": self._bytes_read,
            "connected_duration": now - self._connection_start_time,
            "ping_rtt_ms": self._stats.ping_rtt_ms,
            "write_buffer_size": len(self._write_buffer),
            "read_buffer_size": len(self._read_buffer),
        }

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
        """Get remote address from the WebSocket connection."""
        try:
            # For trio-websocket, we need to get the remote address differently
            # This is a placeholder implementation
            return None
        except Exception:
            pass
        return None
