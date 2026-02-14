"""
Yamux stream multiplexer implementation for py-libp2p.
This is the preferred multiplexing protocol due to its performance and feature set.
Mplex is also available for legacy compatibility but may be deprecated in the future.
"""

from collections.abc import (
    Awaitable,
    Callable,
)
import inspect
import logging
import struct
from types import (
    TracebackType,
)
from typing import (
    Any,
)

import trio
from trio import (
    MemoryReceiveChannel,
    MemorySendChannel,
    Nursery,
)

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    ISecureConn,
)
from libp2p.io.exceptions import (
    ConnectionClosedError,
    IncompleteReadError,
    IOException,
)
from libp2p.io.utils import (
    read_exactly,
)
from libp2p.network.connection.exceptions import (
    RawConnError,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
    MuxedStreamEOF,
    MuxedStreamError,
    MuxedStreamReset,
)
from libp2p.stream_muxer.rw_lock import ReadWriteLock

# Configure logger for this module
logger = logging.getLogger(__name__)

PROTOCOL_ID = "/yamux/1.0.0"
TYPE_DATA = 0x0
TYPE_WINDOW_UPDATE = 0x1
TYPE_PING = 0x2
TYPE_GO_AWAY = 0x3
FLAG_SYN = 0x1
FLAG_ACK = 0x2
FLAG_FIN = 0x4
FLAG_RST = 0x8
HEADER_SIZE = 12
# Network byte order: version (B), type (B), flags (H), stream_id (I), length (I)
YAMUX_HEADER_FORMAT = "!BBHII"
DEFAULT_WINDOW_SIZE = 256 * 1024

GO_AWAY_NORMAL = 0x0
GO_AWAY_PROTOCOL_ERROR = 0x1
GO_AWAY_INTERNAL_ERROR = 0x2


class YamuxStream(IMuxedStream):
    def __init__(self, stream_id: int, conn: "Yamux", is_initiator: bool) -> None:
        self.stream_id = stream_id
        self.conn = conn
        self.muxed_conn = conn
        self.is_initiator = is_initiator
        self.closed = False
        self.send_closed = False
        self.recv_closed = False
        self.reset_received = False  # Track if RST was received
        self.send_window = DEFAULT_WINDOW_SIZE
        self.recv_window = DEFAULT_WINDOW_SIZE
        self.window_lock = trio.Lock()
        self.rw_lock = ReadWriteLock()
        self.close_lock = trio.Lock()

    async def __aenter__(self) -> "YamuxStream":
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

    async def write(self, data: bytes) -> None:
        async with self.rw_lock.write_lock():
            if self.send_closed:
                raise MuxedStreamError("Stream is closed for sending")

            # Flow control: Check if we have enough send window
            total_len = len(data)
            sent = 0
            logger.debug(f"Stream {self.stream_id}: Starts writing {total_len} bytes ")
            while sent < total_len:
                # Wait for available window with timeout
                timeout = False
                async with self.window_lock:
                    if self.send_window == 0:
                        logger.debug(
                            f"Stream {self.stream_id}: "
                            "Window is zero, waiting for update"
                        )
                        # Release lock and wait with timeout
                        self.window_lock.release()
                        # To avoid re-acquiring the lock immediately,
                        with trio.move_on_after(5.0) as cancel_scope:
                            while self.send_window == 0 and not self.closed:
                                await trio.sleep(0.01)
                            # If we timed out, cancel the scope
                            timeout = cancel_scope.cancelled_caught
                        # Re-acquire lock
                        await self.window_lock.acquire()

                    # If we timed out waiting for window update, raise an error
                    if timeout:
                        raise MuxedStreamError(
                            "Timed out waiting for window update after 5 seconds."
                        )

                    if self.closed:
                        raise MuxedStreamError("Stream is closed")

                    # Calculate how much we can send now
                    to_send = min(self.send_window, total_len - sent)
                    chunk = data[sent : sent + to_send]
                    self.send_window -= to_send

                    # Send the data
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT, 0, TYPE_DATA, 0, self.stream_id, len(chunk)
                    )
                    await self.conn.secured_conn.write(header + chunk)
                    sent += to_send

    async def send_window_update(self, increment: int, skip_lock: bool = False) -> None:
        """
        Send a window update to peer.

        param:increment: The amount to increment the window size by.
        If None, uses the difference between DEFAULT_WINDOW_SIZE
        and current receive window.
        param:skip_lock (bool): If True, skips acquiring window_lock.
        This should only be used when calling from a context
        that already holds the lock.

        Note: This method gracefully handles connection closure errors.
        If the connection is closed (e.g., peer closed WebSocket immediately
        after sending data), the window update will fail silently, allowing
        the read operation to complete successfully.
        """
        if increment <= 0:
            # If increment is zero or negative, skip sending update
            logger.debug(
                f"Stream {self.stream_id}: Skipping window update"
                f"(increment={increment})"
            )
            return
        logger.debug(
            f"Stream {self.stream_id}: Sending window update with increment={increment}"
        )

        async def _do_window_update() -> None:
            header = struct.pack(
                YAMUX_HEADER_FORMAT,
                0,
                TYPE_WINDOW_UPDATE,
                0,
                self.stream_id,
                increment,
            )
            try:
                await self.conn.secured_conn.write(header)
            except ConnectionClosedError as e:
                # Typed exception from transports (e.g., WebSocket) that
                # properly signal connection closure — handle gracefully.
                # Connection may be closed by peer (e.g., WebSocket closed
                # immediately after sending data, as seen with Nim).
                # This is acceptable — the data was already read successfully.
                logger.debug(
                    f"Stream {self.stream_id}: Window update failed due to "
                    f"connection closure (data was already read): {e}"
                )
                return
            except (RawConnError, IOException) as e:
                # Fallback for transports that don't yet raise
                # ConnectionClosedError (e.g., TCP RawConnError).
                error_str = str(e).lower()
                if any(
                    keyword in error_str
                    for keyword in [
                        "connection closed",
                        "closed by peer",
                        "connection is closed",
                    ]
                ):
                    logger.debug(
                        f"Stream {self.stream_id}: Window update failed due to "
                        f"connection closure (data was already read): {e}"
                    )
                    return
                # Re-raise if it's a different error we don't expect
                logger.warning(
                    f"Stream {self.stream_id}: Unexpected error during "
                    f"window update: {e}"
                )
                raise

        if skip_lock:
            await _do_window_update()
        else:
            async with self.window_lock:
                await _do_window_update()

    async def read(self, n: int | None = -1) -> bytes:
        """
        Read data from the stream.

        Args:
            n: Number of bytes to read. If -1 or None, read all available data
               until the stream is closed.

        Returns:
            bytes: The data read from the stream. May return partial data
                   if the stream is reset or closed before reading all requested bytes.

        Raises:
            MuxedStreamReset: If the stream was reset by the remote peer.
            MuxedStreamEOF: If the stream is closed for receiving and no more
                           data is available.

        """
        # Handle None value for n by converting it to -1
        if n is None:
            n = -1

        # If the stream is closed for receiving and the buffer is empty, check status
        if self.recv_closed and not self.conn.stream_buffers.get(self.stream_id):
            logger.debug(
                f"Stream {self.stream_id}: Stream closed for receiving and buffer empty"
            )
            if self.reset_received:
                raise MuxedStreamReset("Stream was reset")
            raise MuxedStreamEOF("Stream is closed for receiving")

        if n == -1:
            data = b""
            while not self.conn.event_shutting_down.is_set():
                # Check if there's data in the buffer
                buffer = self.conn.stream_buffers.get(self.stream_id)

                # If buffer is not available, check if stream is closed
                if buffer is None:
                    logger.debug(f"Stream {self.stream_id}: No buffer available")
                    # If reset was received, raise reset. Otherwise, EOF.
                    if self.reset_received:
                        raise MuxedStreamReset("Stream was reset")
                    # If we got data before the buffer disappeared, return it
                    if data:
                        return data
                    raise MuxedStreamEOF("Stream buffer closed")

                # If we have data in buffer, process it
                if len(buffer) > 0:
                    chunk = bytes(buffer)
                    buffer.clear()
                    data += chunk

                    # Send window update for the chunk we just read
                    async with self.window_lock:
                        self.recv_window += len(chunk)
                        logger.debug(f"Stream {self.stream_id}: Update {len(chunk)}")
                        await self.send_window_update(len(chunk), skip_lock=True)

                # Check for reset
                if self.reset_received:
                    logger.debug(f"Stream {self.stream_id}: Stream was reset")
                    # Return any data we managed to read before the reset
                    if data:
                        return data
                    raise MuxedStreamReset("Stream was reset")

                # If stream is closed and buffer is empty
                if self.recv_closed and len(buffer) == 0:
                    logger.debug(f"Stream {self.stream_id}: Closed with empty buffer")
                    if data:
                        return data
                    else:
                        raise MuxedStreamEOF("Stream is closed for receiving")

                # Wait for more data or stream closure
                logger.debug(f"Stream {self.stream_id}: Waiting for data or FIN")
                try:
                    await self.conn.stream_events[self.stream_id].wait()
                    self.conn.stream_events[self.stream_id] = trio.Event()
                except KeyError:
                    # Event was removed, means connection is closing
                    logger.debug(f"Stream {self.stream_id}: Event removed, closing")
                    raise MuxedStreamEOF("Stream was removed during read")

            # After loop exit, first check if we have data to return
            if data:
                logger.debug(
                    f"Stream {self.stream_id}: Returning {len(data)} bytes after loop"
                )
                return data

            # No data accumulated, now check why we exited the loop
            if self.conn.event_shutting_down.is_set():
                logger.debug(f"Stream {self.stream_id}: Connection shutting down")
                raise MuxedStreamEOF("Connection shut down")

            # Return empty data (e.g., clean FIN received)
            # This path should no longer be hit for FIN, as it's raised in the loop
            return b""
        else:
            data = await self.conn.read_stream(self.stream_id, n)
            async with self.window_lock:
                self.recv_window += len(data)
                logger.debug(
                    f"Stream {self.stream_id}: Sending window update after read, "
                    f"increment={len(data)}"
                )
                await self.send_window_update(len(data), skip_lock=True)
            return data

    async def close(self) -> None:
        async with self.close_lock:
            if not self.send_closed:
                logger.debug(f"Half-closing stream {self.stream_id} (local end)")
                try:
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_FIN, self.stream_id, 0
                    )
                    await self.conn.secured_conn.write(header)
                except RawConnError as e:
                    logger.debug(f"Error sending FIN, connection likely closed: {e}")
                finally:
                    self.send_closed = True

            # Only set fully closed if both directions are closed
            if self.send_closed and self.recv_closed:
                self.closed = True
            else:
                # Stream is half-closed but not fully closed
                self.closed = False

    async def reset(self) -> None:
        if not self.closed:
            async with self.close_lock:
                logger.debug(f"Resetting stream {self.stream_id}")
                try:
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_RST, self.stream_id, 0
                    )
                    await self.conn.secured_conn.write(header)
                except RawConnError as e:
                    logger.debug(f"Error sending RST, connection likely closed: {e}")
                finally:
                    self.closed = True
                    self.send_closed = True
                    self.recv_closed = True
                    self.reset_received = True  # Mark as reset

    def set_deadline(self, ttl: int) -> bool:
        """
        Set a deadline for the stream. Yamux does not support deadlines natively,
        so this method always returns False to indicate the operation is unsupported.

        :param ttl: Time-to-live in seconds (ignored).
        :return: False, as deadlines are not supported.
        """
        raise NotImplementedError("Yamux does not support setting read deadlines")

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Returns the remote address of the underlying connection.
        """
        # Delegate to the secured_conn's get_remote_address method
        if hasattr(self.conn.secured_conn, "get_remote_address"):
            remote_addr = self.conn.secured_conn.get_remote_address()
            # Ensure the return value matches tuple[str, int] | None
            if (
                remote_addr is None
                or isinstance(remote_addr, tuple)
                and len(remote_addr) == 2
            ):
                return remote_addr
            else:
                raise ValueError(
                    "Underlying connection returned an unexpected address format"
                )
        else:
            # Return None if the underlying connection doesn't provide this info
            return None


class Yamux(IMuxedConn):
    def __init__(
        self,
        secured_conn: ISecureConn,
        peer_id: ID,
        is_initiator: bool | None = None,
        on_close: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.secured_conn = secured_conn
        self.peer_id = peer_id
        self.stream_backlog_limit = 256
        self.stream_backlog_semaphore = trio.Semaphore(256)
        self.on_close = on_close
        # Per Yamux spec
        # (https://github.com/hashicorp/yamux/blob/master/spec.md#streamid-field):
        # Initiators assign odd stream IDs (starting at 1),
        # responders use even IDs (starting at 2).
        self.is_initiator_value = (
            is_initiator if is_initiator is not None else secured_conn.is_initiator
        )
        self.next_stream_id: int = 1 if self.is_initiator_value else 2
        self.streams: dict[int, YamuxStream] = {}
        self.streams_lock = trio.Lock()
        self.new_stream_send_channel: MemorySendChannel[YamuxStream]
        self.new_stream_receive_channel: MemoryReceiveChannel[YamuxStream]
        (
            self.new_stream_send_channel,
            self.new_stream_receive_channel,
        ) = trio.open_memory_channel(10)
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()
        self.stream_buffers: dict[int, bytearray] = {}
        self.stream_events: dict[int, trio.Event] = {}
        self._nursery: Nursery | None = None

    async def start(self) -> None:
        logger.debug(f"Starting Yamux for {self.peer_id}")
        if self.event_started.is_set():
            logger.debug(f"Yamux for {self.peer_id} already started")
            return
        logger.debug(f"Yamux.start() creating nursery for {self.peer_id}")
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            logger.debug(
                f"Yamux.start() starting handle_incoming task for {self.peer_id}"
            )
            nursery.start_soon(self.handle_incoming)
            logger.debug(f"Yamux.start() setting event_started for {self.peer_id}")
            self.event_started.set()
        logger.debug(
            f"Yamux.start() exiting for {self.peer_id}, closing new stream channel"
        )
        try:
            self.new_stream_send_channel.close()
        except trio.ClosedResourceError:
            # Channel already closed. This occurs when close() was called or when
            # handle_incoming() detected a connection error and called
            # _cleanup_on_error(). In both cases, handle_incoming() exits, causing
            # the nursery to exit. This is fine - we just wanted to make sure
            # it's closed.
            pass

    @property
    def is_initiator(self) -> bool:
        return self.is_initiator_value

    async def close(self, error_code: int = GO_AWAY_NORMAL) -> None:
        logger.debug(f"Closing Yamux connection with code {error_code}")
        async with self.streams_lock:
            if not self.event_shutting_down.is_set():
                try:
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT, 0, TYPE_GO_AWAY, 0, 0, error_code
                    )
                    await self.secured_conn.write(header)
                except Exception as e:
                    logger.debug(f"Failed to send GO_AWAY: {e}")
                self.event_shutting_down.set()
                # Close channel to unblock accept_stream
                self.new_stream_send_channel.close()
                for stream in self.streams.values():
                    stream.closed = True
                    stream.send_closed = True
                    stream.recv_closed = True
                    if stream.stream_id in self.stream_events:
                        self.stream_events[stream.stream_id].set()
                self.streams.clear()
                self.stream_buffers.clear()
                self.stream_events.clear()
        try:
            await self.secured_conn.close()
            logger.debug(f"Successfully closed secured_conn for peer {self.peer_id}")
        except Exception as e:
            logger.debug(f"Error closing secured_conn for peer {self.peer_id}: {e}")
        self.event_closed.set()
        if self.on_close:
            logger.debug(f"Calling on_close in Yamux.close for peer {self.peer_id}")
            if inspect.iscoroutinefunction(self.on_close):
                if self.on_close is not None:
                    await self.on_close()
            else:
                if self.on_close is not None:
                    await self.on_close()
        await trio.sleep(0.1)

    @property
    def is_closed(self) -> bool:
        return self.event_closed.is_set()

    async def open_stream(self) -> YamuxStream:
        # Wait for backlog slot
        await self.stream_backlog_semaphore.acquire()
        async with self.streams_lock:
            if self.event_shutting_down.is_set():
                self.stream_backlog_semaphore.release()
                raise MuxedStreamError("Connection is shutting down")
            stream_id = self.next_stream_id
            self.next_stream_id += 2
            stream = YamuxStream(stream_id, self, True)
            self.streams[stream_id] = stream
            self.stream_buffers[stream_id] = bytearray()
            self.stream_events[stream_id] = trio.Event()

        # If stream is rejected or errors, release the semaphore
        try:
            header = struct.pack(
                YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_SYN, stream_id, 0
            )
            logger.debug(f"Sending SYN header for stream {stream_id}")
            await self.secured_conn.write(header)
            return stream
        except Exception as e:
            self.stream_backlog_semaphore.release()
            # Clean up stream if SYN fails
            async with self.streams_lock:
                if stream_id in self.streams:
                    del self.streams[stream_id]
                if stream_id in self.stream_buffers:
                    del self.stream_buffers[stream_id]
                if stream_id in self.stream_events:
                    del self.stream_events[stream_id]
            raise MuxedStreamError(f"Failed to send SYN: {e}") from e

    async def accept_stream(self) -> IMuxedStream:
        """
        Accept a new stream from the remote peer.

        Returns:
            IMuxedStream: A new stream from the remote peer.

        Raises:
            MuxedConnUnavailable: If the connection is closed while waiting for a new
                stream. This ensures that accept_stream() does not hang indefinitely
                when the underlying connection terminates (either cleanly or due to
                error). The caller (e.g., SwarmConn) catches this exception to properly
                clean up the connection.

        """
        logger.debug("Waiting for new stream")
        try:
            stream = await self.new_stream_receive_channel.receive()
            logger.debug(f"Received stream {stream.stream_id}")
            return stream
        except trio.EndOfChannel:
            logger.debug("New stream channel closed, connection is shutting down")
            raise MuxedConnUnavailable("Connection closed")

    async def read_stream(self, stream_id: int, n: int = -1) -> bytes:
        logger.debug(f"Reading from stream {self.peer_id}:{stream_id}, n={n}")
        if n is None:
            n = -1

        while True:
            async with self.streams_lock:
                if stream_id not in self.streams:
                    logger.debug(f"Stream {self.peer_id}:{stream_id} unknown")
                    raise MuxedStreamEOF("Stream closed")
                if self.event_shutting_down.is_set():
                    logger.debug(
                        f"Stream {self.peer_id}:{stream_id}: connection shutting down"
                    )
                    raise MuxedStreamEOF("Connection shut down")
                stream = self.streams[stream_id]
                buffer = self.stream_buffers.get(stream_id)
                logger.debug(
                    f"Stream {self.peer_id}:{stream_id}: "
                    f"closed={stream.closed}, "
                    f"recv_closed={stream.recv_closed}, "
                    f"reset_received={stream.reset_received}, "
                    f"buffer_len={len(buffer) if buffer else 0}"
                )
                if buffer is None:
                    logger.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"Buffer gone, assuming closed"
                    )
                    if stream.reset_received:
                        raise MuxedStreamReset("Stream was reset")
                    raise MuxedStreamEOF("Stream buffer closed")

                if stream.recv_closed and buffer and len(buffer) > 0:
                    if n == -1 or n >= len(buffer):
                        data = bytes(buffer)
                        buffer.clear()
                    else:
                        data = bytes(buffer[:n])
                        del buffer[:n]
                    logger.debug(
                        f"Returning {len(data)} bytes"
                        f"from stream {self.peer_id}:{stream_id}, "
                        f"buffer_len={len(buffer)} (recv_closed)"
                    )
                    return data

                if stream.reset_received:
                    logger.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"reset_received=True, raising MuxedStreamReset"
                    )
                    raise MuxedStreamReset("Stream was reset")

                if buffer and len(buffer) > 0:
                    if n == -1 or n >= len(buffer):
                        data = bytes(buffer)
                        buffer.clear()
                    else:
                        data = bytes(buffer[:n])
                        del buffer[:n]
                    logger.debug(
                        f"Returning {len(data)} bytes"
                        f"from stream {self.peer_id}:{stream_id}, "
                        f"buffer_len={len(buffer)}"
                    )
                    return data

                # Check if recv_closed and buffer empty
                if stream.recv_closed:
                    logger.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"recv_closed=True, buffer empty, raising EOF"
                    )
                    raise MuxedStreamEOF("Stream is closed for receiving")

                # Check if stream is fully closed
                if stream.closed:
                    logger.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"closed=True, raising MuxedStreamReset"
                    )
                    raise MuxedStreamReset("Stream is reset or closed")

            # Wait for data if stream is still open
            logger.debug(f"Waiting for data on stream {self.peer_id}:{stream_id}")
            try:
                await self.stream_events[stream_id].wait()
                self.stream_events[stream_id] = trio.Event()
            except KeyError:
                raise MuxedStreamEOF("Stream was removed")

        # This line should never be reached, but satisfies the type checker
        raise MuxedStreamEOF("Unexpected end of read_stream")

    async def handle_incoming(self) -> None:
        logger.debug(f"Yamux handle_incoming() started for peer {self.peer_id}")
        while not self.event_shutting_down.is_set():
            try:
                logger.debug(
                    f"Yamux handle_incoming() calling read_exactly({HEADER_SIZE}) "
                    f"for peer {self.peer_id}"
                )
                try:
                    header = await read_exactly(self.secured_conn, HEADER_SIZE)
                except IncompleteReadError as e:
                    # Check if this is a clean connection closure (0 bytes received)
                    # This happens when the peer closes the connection gracefully
                    # after completing their operations (e.g., after ping/pong)
                    if e.is_clean_close:
                        # Clean connection closure - this is normal when peer
                        # disconnects after completing protocol exchange
                        logger.info(
                            f"Yamux connection closed cleanly by peer {self.peer_id}"
                        )
                    else:
                        # Unexpected partial read - log as warning
                        transport_type = "unknown"
                        try:
                            if hasattr(self.secured_conn, "conn_state"):
                                conn_state_method = getattr(
                                    self.secured_conn, "conn_state"
                                )
                                if callable(conn_state_method):
                                    state = conn_state_method()
                                    if isinstance(state, dict):
                                        transport_type = state.get(
                                            "transport", "unknown"
                                        )
                        except Exception:
                            pass
                        logger.warning(
                            f"Yamux connection closed unexpectedly for peer "
                            f"{self.peer_id}: {e}. Transport: {transport_type}."
                        )

                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break
                except Exception as e:
                    logger.debug(f"Error reading header for peer {self.peer_id}: {e}")
                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break

                header_len = len(header)
                logger.debug(
                    f"Yamux handle_incoming() received {header_len} bytes "
                    f"header for peer {self.peer_id}"
                )
                if len(header) != HEADER_SIZE:
                    logger.debug(
                        f"Unexpected header size {header_len} != {HEADER_SIZE} "
                        f"for peer {self.peer_id}"
                    )
                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break
                version, typ, flags, stream_id, length = struct.unpack(
                    YAMUX_HEADER_FORMAT, header
                )
                logger.debug(
                    f"Received header for peer {self.peer_id}:"
                    f"type={typ}, flags={flags}, stream_id={stream_id},"
                    f"length={length}"
                )
                if (typ == TYPE_DATA or typ == TYPE_WINDOW_UPDATE) and flags & FLAG_SYN:
                    async with self.streams_lock:
                        if stream_id not in self.streams:
                            stream = YamuxStream(stream_id, self, False)
                            self.streams[stream_id] = stream
                            self.stream_buffers[stream_id] = bytearray()
                            self.stream_events[stream_id] = trio.Event()

                            # Read any data that came with the SYN frame
                            if length > 0:
                                try:
                                    data = await read_exactly(self.secured_conn, length)
                                    self.stream_buffers[stream_id].extend(data)
                                    self.stream_events[stream_id].set()
                                    logger.debug(
                                        f"Read {length} bytes with SYN "
                                        f"for stream {stream_id}"
                                    )
                                except IncompleteReadError as e:
                                    logger.error(
                                        "Incomplete read for SYN data on stream "
                                        f"{stream_id}: {e}"
                                    )
                                    # Mark stream as closed
                                    stream.recv_closed = True
                                    stream.closed = True
                                    if stream_id in self.stream_events:
                                        self.stream_events[stream_id].set()

                            ack_header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_DATA,
                                FLAG_ACK,
                                stream_id,
                                0,
                            )
                            await self.secured_conn.write(ack_header)
                            logger.debug(
                                f"Sending stream {stream_id}"
                                f"to channel for peer {self.peer_id}"
                            )
                            await self.new_stream_send_channel.send(stream)
                        else:
                            rst_header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_DATA,
                                FLAG_RST,
                                stream_id,
                                0,
                            )
                            await self.secured_conn.write(rst_header)
                elif typ == TYPE_DATA and flags & FLAG_ACK:
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            # Read any data that came with the ACK
                            if length > 0:
                                try:
                                    data = await read_exactly(self.secured_conn, length)
                                    self.stream_buffers[stream_id].extend(data)
                                    self.stream_events[stream_id].set()
                                    logger.debug(
                                        f"Received ACK with {length} bytes for stream "
                                        f"{stream_id} for peer {self.peer_id}"
                                    )
                                except IncompleteReadError as e:
                                    logger.error(
                                        "Incomplete read for ACK data on stream "
                                        f"{stream_id}: {e}"
                                    )
                                    # Mark stream as closed
                                    stream = self.streams[stream_id]
                                    stream.recv_closed = True
                                    stream.closed = True
                                    if stream_id in self.stream_events:
                                        self.stream_events[stream_id].set()
                            else:
                                logger.debug(
                                    f"Received ACK (no data) for stream {stream_id} "
                                    f"for peer {self.peer_id}"
                                )
                elif typ == TYPE_GO_AWAY:
                    error_code = length
                    if error_code == GO_AWAY_NORMAL:
                        logger.debug(
                            f"Received GO_AWAY for peer"
                            f"{self.peer_id}: Normal termination"
                        )
                    elif error_code == GO_AWAY_PROTOCOL_ERROR:
                        logger.error(
                            f"Received GO_AWAY for peer{self.peer_id}: Protocol error"
                        )
                    elif error_code == GO_AWAY_INTERNAL_ERROR:
                        logger.error(
                            f"Received GO_AWAY for peer {self.peer_id}: Internal error"
                        )
                    else:
                        logger.error(
                            f"Received GO_AWAY for peer {self.peer_id}"
                            f"with unknown error code: {error_code}"
                        )
                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break
                elif typ == TYPE_PING:
                    if flags & FLAG_SYN:
                        logger.debug(
                            f"Received ping request with value"
                            f"{length} for peer {self.peer_id}"
                        )
                        ping_header = struct.pack(
                            YAMUX_HEADER_FORMAT, 0, TYPE_PING, FLAG_ACK, 0, length
                        )
                        await self.secured_conn.write(ping_header)
                    elif flags & FLAG_ACK:
                        logger.debug(
                            f"Received ping response with value"
                            f"{length} for peer {self.peer_id}"
                        )
                elif typ == TYPE_DATA:
                    try:
                        logger.debug(
                            f"Yamux handle_incoming() reading {length} bytes "
                            f"data for stream {stream_id}, peer {self.peer_id}"
                        )
                        try:
                            data = (
                                await read_exactly(self.secured_conn, length)
                                if length > 0
                                else b""
                            )
                        except IncompleteReadError as e:
                            logger.error(
                                f"Incomplete read for data on stream {stream_id}: {e}"
                            )
                            # Mark stream as closed
                            async with self.streams_lock:
                                if stream_id in self.streams:
                                    stream = self.streams[stream_id]
                                    stream.recv_closed = True
                                    stream.closed = True
                                    if stream_id in self.stream_events:
                                        self.stream_events[stream_id].set()
                            continue

                        if data is None:
                            logger.debug(
                                f"Connection closed (None returned) while reading data "
                                f"for peer {self.peer_id}"
                            )
                            self.event_shutting_down.set()
                            await self._cleanup_on_error()
                            break
                        data_len = len(data)
                        logger.debug(
                            f"Yamux handle_incoming() received {data_len} bytes "
                            f"data for stream {stream_id}, peer {self.peer_id}"
                        )
                        async with self.streams_lock:
                            if stream_id in self.streams:
                                self.stream_buffers[stream_id].extend(data)
                                # Always set event, even if no data
                                # in case FIN/RST is set
                                self.stream_events[stream_id].set()

                                if flags & FLAG_FIN:
                                    logger.debug(
                                        f"Received FIN for stream {self.peer_id}:"
                                        f"{stream_id}, marking recv_closed"
                                    )
                                    self.streams[stream_id].recv_closed = True
                                    if self.streams[stream_id].send_closed:
                                        self.streams[stream_id].closed = True

                                if flags & FLAG_RST:
                                    logger.debug(
                                        f"Resetting stream {stream_id} for peer"
                                        f"{self.peer_id} (RST on DATA)"
                                    )
                                    self.streams[stream_id].closed = True
                                    self.streams[stream_id].reset_received = True
                                    # Wake up reader
                                    self.stream_events[stream_id].set()

                    except Exception as e:
                        logger.error(f"Error reading data for stream {stream_id}: {e}")
                        # Mark stream as closed on read error
                        async with self.streams_lock:
                            if stream_id in self.streams:
                                self.streams[stream_id].recv_closed = True
                                if self.streams[stream_id].send_closed:
                                    self.streams[stream_id].closed = True
                                self.stream_events[stream_id].set()
                # Handle WINDOW_UPDATE frames
                # Per Yamux spec (https://github.com/hashicorp/yamux/blob/master/spec.md#flag-field),
                # FIN and RST flags may be sent with WINDOW_UPDATE frames, not just
                # DATA frames.
                elif typ == TYPE_WINDOW_UPDATE:
                    increment = length
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            stream = self.streams[stream_id]
                            async with stream.window_lock:
                                logger.debug(
                                    f"Received window update for stream"
                                    f"{self.peer_id}:{stream_id},"
                                    f" increment: {increment}"
                                )
                                stream.send_window += increment

                            # Check for FIN/RST flags on WINDOW_UPDATE
                            if flags & FLAG_FIN:
                                logger.debug(
                                    f"Received FIN for stream {self.peer_id}:"
                                    f"{stream_id} on WINDOW_UPDATE, marking recv_closed"
                                )
                                stream.recv_closed = True
                                if stream.send_closed:
                                    stream.closed = True
                                # Wake up reader
                                self.stream_events[stream_id].set()

                            if flags & FLAG_RST:
                                logger.debug(
                                    f"Resetting stream {stream_id} for peer"
                                    f"{self.peer_id} (RST on WINDOW_UPDATE)"
                                )
                                stream.closed = True
                                stream.reset_received = True
                                # Wake up reader
                                self.stream_events[stream_id].set()
            except Exception as e:
                # Special handling for expected IncompleteReadError on stream close
                # This occurs when the connection closes while reading
                if isinstance(e, IncompleteReadError):
                    if e.is_clean_close:
                        logger.info(
                            f"Yamux connection closed cleanly for peer {self.peer_id}"
                        )
                        self.event_shutting_down.set()
                        await self._cleanup_on_error()
                        break
                    else:
                        # Partial read - log as warning, not error
                        logger.warning(
                            f"Incomplete read in handle_incoming for peer "
                            f"{self.peer_id}: {e}"
                        )
                else:
                    # Handle RawConnError with more nuance
                    if isinstance(e, RawConnError):
                        error_msg = str(e)
                        # If RawConnError is empty, it's likely normal cleanup
                        if not error_msg.strip():
                            logger.info(
                                f"RawConnError (empty) during cleanup for peer "
                                f"{self.peer_id} (normal connection shutdown)"
                            )
                        else:
                            # Log non-empty RawConnError as warning
                            logger.warning(
                                f"RawConnError during connection handling for peer "
                                f"{self.peer_id}: {error_msg}"
                            )
                    else:
                        # Log all other errors normally
                        logger.error(
                            f"Error in handle_incoming for peer {self.peer_id}: "
                            + f"{type(e).__name__}: {str(e)}"
                        )
                # Don't crash the whole connection for temporary errors
                if self.event_shutting_down.is_set() or isinstance(
                    e,
                    (
                        RawConnError,
                        OSError,
                        IncompleteReadError,
                        trio.ClosedResourceError,
                        trio.BrokenResourceError,
                    ),
                ):
                    await self._cleanup_on_error()
                    break
                # For other errors, log and continue
                await trio.sleep(0.01)

    async def _cleanup_on_error(self) -> None:
        # Set shutdown flag first to prevent other operations
        self.event_shutting_down.set()

        # Close the new stream channel to unblock any pending accept_stream()
        try:
            self.new_stream_send_channel.close()
        except trio.ClosedResourceError:
            pass  # Already closed

        # Clean up streams
        async with self.streams_lock:
            for stream in self.streams.values():
                stream.closed = True
                stream.send_closed = True
                stream.recv_closed = True
                stream.reset_received = True
                # Set the event so any waiters are woken up
                if stream.stream_id in self.stream_events:
                    self.stream_events[stream.stream_id].set()
            # Clear buffers and events
            self.stream_buffers.clear()
            self.stream_events.clear()
            self.streams.clear()

        # Close the secured connection
        try:
            await self.secured_conn.close()
            logger.debug(f"Successfully closed secured_conn for peer {self.peer_id}")
        except Exception as close_error:
            logger.error(
                f"Error closing secured_conn for peer {self.peer_id}: {close_error}"
            )

        # Set closed flag
        self.event_closed.set()

        # Call on_close callback if provided
        if self.on_close:
            logger.debug(f"Calling on_close for peer {self.peer_id}")
            try:
                if inspect.iscoroutinefunction(self.on_close):
                    await self.on_close()
                else:
                    self.on_close()
            except Exception as callback_error:
                logger.error(f"Error in on_close callback: {callback_error}")
