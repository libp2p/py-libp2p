from dataclasses import dataclass
from datetime import datetime
import logging
import ssl
import threading
import time
from typing import Any

from multiaddr import Multiaddr
import trio
from trio_websocket import ConnectionClosed, HandshakeError, WebSocketConnection
from websockets.exceptions import (
    ConnectionClosed,
)

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException

logger = logging.getLogger(__name__)


@dataclass
class WebSocketStats:
    """Statistics for a WebSocket connection."""

    created_at: datetime = datetime.utcnow()
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

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()

    def record_error(self, error: str):
        """Record an error occurrence."""
        self.errors += 1
        self.last_error = error
        self.update_activity()

    def record_message_sent(self, size: int):
        """Record a message being sent."""
        self.messages_sent += 1
        self.bytes_sent += size
        self.update_activity()

    def record_message_received(self, size: int):
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
    ) -> None:
        """
        Initialize a new WebSocket connection.

        Args:
            ws_connection: The underlying WebSocket connection
            local_addr: Local multiaddr (optional)
            remote_addr: Remote multiaddr (optional)
            max_buffer: Maximum buffer size in bytes

        """
        self._ws = ws_connection
        self._local_addr = local_addr
        self._remote_addr = remote_addr
        self._max_buffer = max_buffer
        self._ssl_context = ssl_context
        self._max_message_size = max_message_size
        self._keepalive_interval = keepalive_interval
        self._handshake_timeout = handshake_timeout

        # State management
        self._closed = False
        self._read_lock = trio.Lock()
        self._write_lock = trio.Lock()
        self._close_lock = trio.Lock()

        # Statistics tracking
        self.stats = WebSocketStats(
            is_secure=bool(ssl_context),
            protocol=getattr(ws_connection, "subprotocol", None),
        )

        # Start keepalive if enabled
        if keepalive_interval > 0:
            self._start_keepalive()

    async def _start_keepalive(self):
        """Start keepalive ping/pong."""

        async def keepalive_loop():
            while not self._closed:
                try:
                    await trio.sleep(self._keepalive_interval)
                    if not self._closed:
                        start_time = time.time()
                        await self._ws.ping()
                        rtt = time.time() - start_time
                        self.stats.ping_rtt_ms = rtt * 1000
                except Exception as e:
                    logger.warning("Keepalive failed: %s", e)

        nursery = trio.open_nursery()
        await nursery.start(keepalive_loop)

    async def read(self, n: int = -1) -> bytes:
        """
        Read data from the WebSocket connection with enhanced error handling.

        Args:
            n: Number of bytes to read (ignored for WebSocket)

        Returns:
            bytes: Received data

        Raises:
            WebSocketConnectionError: If connection is closed
            WebSocketMessageError: If message is too large
            WebSocketProtocolError: If protocol error occurs

        """
        if self._closed:
            raise WebSocketConnectionError("Connection is closed")

        async with self._read_lock:
            try:
                message = await self._ws.receive()

                # Size validation
                if len(message) > self._max_message_size:
                    raise WebSocketMessageError(
                        f"Message size {len(message)} exceeds maximum {self._max_message_size}"
                    )

                # Update statistics
                self.stats.record_message_received(len(message))

                # Handle binary vs text messages
                if isinstance(message, str):
                    return message.encode()
                return message

            except ConnectionClosed as e:
                self._closed = True
                raise WebSocketConnectionError(f"Connection closed: {e}")

            except HandshakeError as e:
                self.stats.record_error(str(e))
                raise WebSocketHandshakeError(f"Handshake failed: {e}")

            except Exception as e:
                self.stats.record_error(str(e))
                logger.error("Error reading from WebSocket: %s", e)
                raise WebSocketConnectionError(f"Read error: {e}")

    async def write(self, data: bytes) -> int:
        """
        Write data to the WebSocket connection with enhanced error handling.

        Args:
            data: Data to write

        Returns:
            int: Number of bytes written

        Raises:
            WebSocketConnectionError: If connection is closed
            WebSocketMessageError: If message is too large
            WebSocketProtocolError: If protocol error occurs

        """
        if self._closed:
            raise WebSocketConnectionError("Connection is closed")

        async with self._write_lock:
            try:
                # Size validation
                if len(data) > self._max_message_size:
                    raise WebSocketMessageError(
                        f"Message size {len(data)} exceeds maximum {self._max_message_size}"
                    )

                # Send message
                await self._ws.send_bytes(data)

                # Update statistics
                self.stats.record_message_sent(len(data))

                return len(data)

            except ConnectionClosed as e:
                self._closed = True
                raise WebSocketConnectionError(f"Connection closed: {e}")

            except HandshakeError as e:
                self.stats.record_error(str(e))
                raise WebSocketHandshakeError(f"Handshake failed: {e}")

            except Exception as e:
                self.stats.record_error(str(e))
                logger.error("Error writing to WebSocket: %s", e)
                raise WebSocketConnectionError(f"Write error: {e}")

        # State tracking
        self._closed = False
        self._close_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()

        # Buffers
        self._read_buffer = bytearray()
        self._write_buffer = bytearray()

        # Statistics
        self._stats = WebSocketStats(connected_at=time.time())

        # Start monitoring
        self._start_monitoring()

    def _start_monitoring(self) -> None:
        """Start connection monitoring."""

        async def monitor():
            while not self._closed:
                try:
                    # Measure ping RTT
                    start_time = time.time()
                    await self._ws.ping()
                    self._stats.ping_rtt_ms = (time.time() - start_time) * 1000

                    # Wait before next ping
                    await trio.sleep(20.0)  # 20 second ping interval

                except Exception as e:
                    if not self._closed:
                        logger.warning(f"Ping failed: {e}")
                    break

        # Start monitoring in background
        try:
            trio.from_thread.run(monitor)
        except Exception as e:
            logger.warning(f"Failed to start monitoring: {e}")

    async def read(self, n: int = -1) -> bytes:
        """
        Read data from the connection.

        Args:
            n: Number of bytes to read (-1 for all available)

        Returns:
            The read bytes

        Raises:
            IOException: If connection is closed or read fails

        """
        with self._read_lock:
            try:
                # Check if closed
                if self._closed:
                    raise IOException("Connection is closed")

                # Read from buffer first
                if self._read_buffer:
                    if n < 0:
                        data = bytes(self._read_buffer)
                        self._read_buffer.clear()
                        return data
                    else:
                        data = bytes(self._read_buffer[:n])
                        self._read_buffer = self._read_buffer[n:]
                        return data

                # Read from WebSocket
                try:
                    message = await self._ws.receive_message()
                    if not message:
                        return b""

                    # Update stats
                    self._stats.bytes_received += len(message)
                    self._stats.messages_received += 1
                    self._stats.last_message_at = time.time()

                    # Handle partial reads
                    if n < 0:
                        return message
                    else:
                        self._read_buffer.extend(message[n:])
                        return message[:n]

                except ConnectionClosed as e:
                    if not self._closed:
                        logger.warning(f"Connection closed during read: {e}")
                    raise IOException("Connection closed")

            except Exception as e:
                if not self._closed:
                    logger.error(f"Read failed: {e}")
                raise IOException(f"Read failed: {str(e)}")

    async def write(self, data: bytes) -> None:
        """
        Write data to the connection.

        Args:
            data: The bytes to write

        Raises:
            IOException: If connection is closed or write fails

        """
        with self._write_lock:
            try:
                # Check if closed
                if self._closed:
                    raise IOException("Connection is closed")

                # Check buffer limits
                if len(self._write_buffer) + len(data) > self._max_buffer:
                    raise IOException("Write buffer full")

                # Buffer data
                self._write_buffer.extend(data)

                # Write in chunks to avoid large frames
                chunk_size = 16 * 1024  # 16KB chunks
                while self._write_buffer:
                    chunk = bytes(self._write_buffer[:chunk_size])
                    await self._ws.send_message(chunk)

                    # Update stats
                    self._stats.bytes_sent += len(chunk)
                    self._stats.messages_sent += 1

                    # Remove sent data from buffer
                    self._write_buffer = self._write_buffer[chunk_size:]

            except ConnectionClosed as e:
                if not self._closed:
                    logger.warning(f"Connection closed during write: {e}")
                raise IOException("Connection closed")

            except Exception as e:
                if not self._closed:
                    logger.error(f"Write failed: {e}")
                raise IOException(f"Write failed: {str(e)}")

    async def close(self) -> None:
        """Close the connection gracefully."""
        with self._close_lock:
            if self._closed:
                return

            self._closed = True
            try:
                # Close WebSocket connection
                await self._ws.close()

            except Exception as e:
                logger.warning(f"Error closing connection: {e}")

    @property
    def is_closed(self) -> bool:
        """Check if connection is closed."""
        return self._closed

    def get_stats(self) -> dict[str, int | float]:
        """Get connection statistics."""
        now = time.time()
        return {
            "bytes_sent": self._stats.bytes_sent,
            "bytes_received": self._stats.bytes_received,
            "messages_sent": self._stats.messages_sent,
            "messages_received": self._stats.messages_received,
            "connected_duration": now - self._stats.connected_at,
            "last_message_age": now - self._stats.last_message_at
            if self._stats.last_message_at > 0
            else 0,
            "ping_rtt_ms": self._stats.ping_rtt_ms,
            "write_buffer_size": len(self._write_buffer),
            "read_buffer_size": len(self._read_buffer),
        }
        self._is_secure = is_secure
        self._read_buffer = b""
        self._read_lock = trio.Lock()
        self._connection_start_time = time.time()
        self._bytes_read = 0
        self._bytes_written = 0
        self._closed = False
        self._close_lock = trio.Lock()
        self._max_buffered_amount = max_buffered_amount
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
                self._bytes_written += len(data)
                logger.debug(f"WebSocket wrote {len(data)} bytes successfully")

            except Exception as e:
                logger.error(f"WebSocket write failed: {e}")
                self._closed = True
                raise IOException from e

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes (if n is given), else read up to 64KiB.
        This implementation provides byte-level access to WebSocket messages,
        which is required for libp2p protocol compatibility.

        For WebSocket compatibility with libp2p protocols, this method:
        1. Buffers incoming WebSocket messages
        2. Returns exactly the requested number of bytes when n is specified
        3. Accumulates multiple WebSocket messages if needed to satisfy the request
        4. Returns empty bytes (not raises) when connection is closed and no data
           available
        """
        if self._closed:
            raise IOException("Connection is closed")

        async with self._read_lock:
            try:
                # If n is None, read at least one message and return all buffered data
                if n is None:
                    if not self._read_buffer:
                        try:
                            # Use a short timeout to avoid blocking indefinitely
                            with trio.fail_after(1.0):  # 1 second timeout
                                message = await self._ws_connection.get_message()
                                if isinstance(message, str):
                                    message = message.encode("utf-8")
                                self._read_buffer = message
                        except trio.TooSlowError:
                            # No message available within timeout
                            return b""
                        except Exception:
                            # Return empty bytes if no data available
                            # (connection closed)
                            return b""

                    result = self._read_buffer
                    self._read_buffer = b""
                    self._bytes_read += len(result)
                    return result

                # For specific byte count requests, return UP TO n bytes (not exactly n)
                # This matches TCP semantics where read(1024) returns available data
                # up to 1024 bytes

                # If we don't have any data buffered, try to get at least one message
                if not self._read_buffer:
                    try:
                        # Use a short timeout to avoid blocking indefinitely
                        with trio.fail_after(1.0):  # 1 second timeout
                            message = await self._ws_connection.get_message()
                            if isinstance(message, str):
                                message = message.encode("utf-8")
                            self._read_buffer = message
                    except trio.TooSlowError:
                        return b""  # No data available
                    except Exception:
                        return b""

                # Now return up to n bytes from the buffer (TCP-like semantics)
                if len(self._read_buffer) == 0:
                    return b""

                # Return up to n bytes (like TCP read())
                result = self._read_buffer[:n]
                self._read_buffer = self._read_buffer[len(result) :]
                self._bytes_read += len(result)
                return result

            except Exception as e:
                logger.error(f"WebSocket read failed: {e}")
                raise IOException from e

    async def close(self) -> None:
        """Close the WebSocket connection. This method is idempotent."""
        async with self._close_lock:
            if self._closed:
                return  # Already closed

            logger.debug("WebSocket connection closing")
            self._closed = True
            try:
                # Always close the connection directly, avoid context manager issues
                # The context manager may be causing cancel scope corruption
                logger.debug("WebSocket closing connection directly")
                await self._ws_connection.aclose()
                # Exit the context manager if we have one
                if self._ws_context is not None:
                    await self._ws_context.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"WebSocket close error: {e}")
                # Don't raise here, as close() should be idempotent
            finally:
                logger.debug("WebSocket connection closed")

    def is_closed(self) -> bool:
        """Check if the connection is closed"""
        return self._closed

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
