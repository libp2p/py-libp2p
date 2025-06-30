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
    IncompleteReadError,
)
from libp2p.network.connection.exceptions import (
    RawConnError,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.stream_muxer.exceptions import (
    MuxedStreamEOF,
    MuxedStreamError,
    MuxedStreamReset,
)

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
        if self.send_closed:
            raise MuxedStreamError("Stream is closed for sending")

        # Flow control: Check if we have enough send window
        total_len = len(data)
        sent = 0
        logging.debug(f"Stream {self.stream_id}: Starts writing {total_len} bytes ")
        while sent < total_len:
            # Wait for available window with timeout
            timeout = False
            async with self.window_lock:
                if self.send_window == 0:
                    logging.debug(
                        f"Stream {self.stream_id}: Window is zero, waiting for update"
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
        """
        if increment <= 0:
            # If increment is zero or negative, skip sending update
            logging.debug(
                f"Stream {self.stream_id}: Skipping window update"
                f"(increment={increment})"
            )
            return
        logging.debug(
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
            await self.conn.secured_conn.write(header)

        if skip_lock:
            await _do_window_update()
        else:
            async with self.window_lock:
                await _do_window_update()

    async def read(self, n: int | None = -1) -> bytes:
        # Handle None value for n by converting it to -1
        if n is None:
            n = -1

        # If the stream is closed for receiving and the buffer is empty, raise EOF
        if self.recv_closed and not self.conn.stream_buffers.get(self.stream_id):
            logging.debug(
                f"Stream {self.stream_id}: Stream closed for receiving and buffer empty"
            )
            raise MuxedStreamEOF("Stream is closed for receiving")

        if n == -1:
            data = b""
            while not self.conn.event_shutting_down.is_set():
                # Check if there's data in the buffer
                buffer = self.conn.stream_buffers.get(self.stream_id)

                # If buffer is not available, check if stream is closed
                if buffer is None:
                    logging.debug(f"Stream {self.stream_id}: No buffer available")
                    raise MuxedStreamEOF("Stream buffer closed")

                # If we have data in buffer, process it
                if len(buffer) > 0:
                    chunk = bytes(buffer)
                    buffer.clear()
                    data += chunk

                    # Send window update for the chunk we just read
                    async with self.window_lock:
                        self.recv_window += len(chunk)
                        logging.debug(f"Stream {self.stream_id}: Update {len(chunk)}")
                        await self.send_window_update(len(chunk), skip_lock=True)

                # If stream is closed (FIN received) and buffer is empty, break
                if self.recv_closed and len(buffer) == 0:
                    logging.debug(f"Stream {self.stream_id}: Closed with empty buffer")
                    break

                # If stream was reset, raise reset error
                if self.reset_received:
                    logging.debug(f"Stream {self.stream_id}: Stream was reset")
                    raise MuxedStreamReset("Stream was reset")

                # Wait for more data or stream closure
                logging.debug(f"Stream {self.stream_id}: Waiting for data or FIN")
                await self.conn.stream_events[self.stream_id].wait()
                self.conn.stream_events[self.stream_id] = trio.Event()

            # After loop exit, first check if we have data to return
            if data:
                logging.debug(
                    f"Stream {self.stream_id}: Returning {len(data)} bytes after loop"
                )
                return data

            # No data accumulated, now check why we exited the loop
            if self.conn.event_shutting_down.is_set():
                logging.debug(f"Stream {self.stream_id}: Connection shutting down")
                raise MuxedStreamEOF("Connection shut down")

            # Return empty data
            return b""
        else:
            data = await self.conn.read_stream(self.stream_id, n)
            async with self.window_lock:
                self.recv_window += len(data)
                logging.debug(
                    f"Stream {self.stream_id}: Sending window update after read, "
                    f"increment={len(data)}"
                )
                await self.send_window_update(len(data), skip_lock=True)
            return data

    async def close(self) -> None:
        if not self.send_closed:
            logging.debug(f"Half-closing stream {self.stream_id} (local end)")
            header = struct.pack(
                YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_FIN, self.stream_id, 0
            )
            await self.conn.secured_conn.write(header)
            self.send_closed = True

        # Only set fully closed if both directions are closed
        if self.send_closed and self.recv_closed:
            self.closed = True
        else:
            # Stream is half-closed but not fully closed
            self.closed = False

    async def reset(self) -> None:
        if not self.closed:
            logging.debug(f"Resetting stream {self.stream_id}")
            header = struct.pack(
                YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_RST, self.stream_id, 0
            )
            await self.conn.secured_conn.write(header)
            self.closed = True
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
        logging.debug(f"Starting Yamux for {self.peer_id}")
        if self.event_started.is_set():
            return
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            nursery.start_soon(self.handle_incoming)
            self.event_started.set()

    @property
    def is_initiator(self) -> bool:
        return self.is_initiator_value

    async def close(self, error_code: int = GO_AWAY_NORMAL) -> None:
        logging.debug(f"Closing Yamux connection with code {error_code}")
        async with self.streams_lock:
            if not self.event_shutting_down.is_set():
                try:
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT, 0, TYPE_GO_AWAY, 0, 0, error_code
                    )
                    await self.secured_conn.write(header)
                except Exception as e:
                    logging.debug(f"Failed to send GO_AWAY: {e}")
                self.event_shutting_down.set()
                for stream in self.streams.values():
                    stream.closed = True
                    stream.send_closed = True
                    stream.recv_closed = True
                self.streams.clear()
                self.stream_buffers.clear()
                self.stream_events.clear()
        try:
            await self.secured_conn.close()
            logging.debug(f"Successfully closed secured_conn for peer {self.peer_id}")
        except Exception as e:
            logging.debug(f"Error closing secured_conn for peer {self.peer_id}: {e}")
        self.event_closed.set()
        if self.on_close:
            logging.debug(f"Calling on_close in Yamux.close for peer {self.peer_id}")
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
            logging.debug(f"Sending SYN header for stream {stream_id}")
            await self.secured_conn.write(header)
            return stream
        except Exception as e:
            self.stream_backlog_semaphore.release()
            raise e

    async def accept_stream(self) -> IMuxedStream:
        logging.debug("Waiting for new stream")
        try:
            stream = await self.new_stream_receive_channel.receive()
            logging.debug(f"Received stream {stream.stream_id}")
            return stream
        except trio.EndOfChannel:
            raise MuxedStreamError("No new streams available")

    async def read_stream(self, stream_id: int, n: int = -1) -> bytes:
        logging.debug(f"Reading from stream {self.peer_id}:{stream_id}, n={n}")
        if n is None:
            n = -1

        while True:
            async with self.streams_lock:
                if stream_id not in self.streams:
                    logging.debug(f"Stream {self.peer_id}:{stream_id} unknown")
                    raise MuxedStreamEOF("Stream closed")
                if self.event_shutting_down.is_set():
                    logging.debug(
                        f"Stream {self.peer_id}:{stream_id}: connection shutting down"
                    )
                    raise MuxedStreamEOF("Connection shut down")
                stream = self.streams[stream_id]
                buffer = self.stream_buffers.get(stream_id)
                logging.debug(
                    f"Stream {self.peer_id}:{stream_id}: "
                    f"closed={stream.closed}, "
                    f"recv_closed={stream.recv_closed}, "
                    f"reset_received={stream.reset_received}, "
                    f"buffer_len={len(buffer) if buffer else 0}"
                )
                if buffer is None:
                    logging.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"Buffer gone, assuming closed"
                    )
                    raise MuxedStreamEOF("Stream buffer closed")
                # If FIN received and buffer has data, return it
                if stream.recv_closed and buffer and len(buffer) > 0:
                    if n == -1 or n >= len(buffer):
                        data = bytes(buffer)
                        buffer.clear()
                    else:
                        data = bytes(buffer[:n])
                        del buffer[:n]
                    logging.debug(
                        f"Returning {len(data)} bytes"
                        f"from stream {self.peer_id}:{stream_id}, "
                        f"buffer_len={len(buffer)}"
                    )
                    return data
                # If reset received and buffer is empty, raise reset
                if stream.reset_received:
                    logging.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"reset_received=True, raising MuxedStreamReset"
                    )
                    raise MuxedStreamReset("Stream was reset")
                # Check if we can return data (no FIN or reset)
                if buffer and len(buffer) > 0:
                    if n == -1 or n >= len(buffer):
                        data = bytes(buffer)
                        buffer.clear()
                    else:
                        data = bytes(buffer[:n])
                        del buffer[:n]
                    logging.debug(
                        f"Returning {len(data)} bytes"
                        f"from stream {self.peer_id}:{stream_id}, "
                        f"buffer_len={len(buffer)}"
                    )
                    return data
                # Check if stream is closed
                if stream.closed:
                    logging.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"closed=True, raising MuxedStreamReset"
                    )
                    raise MuxedStreamReset("Stream is reset or closed")
                # Check if recv_closed and buffer empty
                if stream.recv_closed:
                    logging.debug(
                        f"Stream {self.peer_id}:{stream_id}:"
                        f"recv_closed=True, buffer empty, raising EOF"
                    )
                    raise MuxedStreamEOF("Stream is closed for receiving")

            # Wait for data if stream is still open
            logging.debug(f"Waiting for data on stream {self.peer_id}:{stream_id}")
            try:
                await self.stream_events[stream_id].wait()
                self.stream_events[stream_id] = trio.Event()
            except KeyError:
                raise MuxedStreamEOF("Stream was removed")

        # This line should never be reached, but satisfies the type checker
        raise MuxedStreamEOF("Unexpected end of read_stream")

    async def handle_incoming(self) -> None:
        while not self.event_shutting_down.is_set():
            try:
                header = await self.secured_conn.read(HEADER_SIZE)
                if not header or len(header) < HEADER_SIZE:
                    logging.debug(
                        f"Connection closed orincomplete header for peer {self.peer_id}"
                    )
                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break
                version, typ, flags, stream_id, length = struct.unpack(
                    YAMUX_HEADER_FORMAT, header
                )
                logging.debug(
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
                            ack_header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_DATA,
                                FLAG_ACK,
                                stream_id,
                                0,
                            )
                            await self.secured_conn.write(ack_header)
                            logging.debug(
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
                elif typ == TYPE_DATA and flags & FLAG_RST:
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            logging.debug(
                                f"Resetting stream {stream_id} for peer {self.peer_id}"
                            )
                            self.streams[stream_id].closed = True
                            self.streams[stream_id].reset_received = True
                            self.stream_events[stream_id].set()
                elif typ == TYPE_DATA and flags & FLAG_ACK:
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            logging.debug(
                                f"Received ACK for stream"
                                f"{stream_id} for peer {self.peer_id}"
                            )
                elif typ == TYPE_GO_AWAY:
                    error_code = length
                    if error_code == GO_AWAY_NORMAL:
                        logging.debug(
                            f"Received GO_AWAY for peer"
                            f"{self.peer_id}: Normal termination"
                        )
                    elif error_code == GO_AWAY_PROTOCOL_ERROR:
                        logging.error(
                            f"Received GO_AWAY for peer{self.peer_id}: Protocol error"
                        )
                    elif error_code == GO_AWAY_INTERNAL_ERROR:
                        logging.error(
                            f"Received GO_AWAY for peer {self.peer_id}: Internal error"
                        )
                    else:
                        logging.error(
                            f"Received GO_AWAY for peer {self.peer_id}"
                            f"with unknown error code: {error_code}"
                        )
                    self.event_shutting_down.set()
                    await self._cleanup_on_error()
                    break
                elif typ == TYPE_PING:
                    if flags & FLAG_SYN:
                        logging.debug(
                            f"Received ping request with value"
                            f"{length} for peer {self.peer_id}"
                        )
                        ping_header = struct.pack(
                            YAMUX_HEADER_FORMAT, 0, TYPE_PING, FLAG_ACK, 0, length
                        )
                        await self.secured_conn.write(ping_header)
                    elif flags & FLAG_ACK:
                        logging.debug(
                            f"Received ping response with value"
                            f"{length} for peer {self.peer_id}"
                        )
                elif typ == TYPE_DATA:
                    try:
                        data = (
                            await self.secured_conn.read(length) if length > 0 else b""
                        )
                        async with self.streams_lock:
                            if stream_id in self.streams:
                                self.stream_buffers[stream_id].extend(data)
                                self.stream_events[stream_id].set()
                                if flags & FLAG_FIN:
                                    logging.debug(
                                        f"Received FIN for stream {self.peer_id}:"
                                        f"{stream_id}, marking recv_closed"
                                    )
                                    self.streams[stream_id].recv_closed = True
                                    if self.streams[stream_id].send_closed:
                                        self.streams[stream_id].closed = True
                    except Exception as e:
                        logging.error(f"Error reading data for stream {stream_id}: {e}")
                        # Mark stream as closed on read error
                        async with self.streams_lock:
                            if stream_id in self.streams:
                                self.streams[stream_id].recv_closed = True
                                if self.streams[stream_id].send_closed:
                                    self.streams[stream_id].closed = True
                                self.stream_events[stream_id].set()
                elif typ == TYPE_WINDOW_UPDATE:
                    increment = length
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            stream = self.streams[stream_id]
                            async with stream.window_lock:
                                logging.debug(
                                    f"Received window update for stream"
                                    f"{self.peer_id}:{stream_id},"
                                    f" increment: {increment}"
                                )
                                stream.send_window += increment
            except Exception as e:
                # Special handling for expected IncompleteReadError on stream close
                if isinstance(e, IncompleteReadError):
                    details = getattr(e, "args", [{}])[0]
                    if (
                        isinstance(details, dict)
                        and details.get("requested_count") == 2
                        and details.get("received_count") == 0
                    ):
                        logging.info(
                            f"Stream closed cleanly for peer {self.peer_id}"
                            + f" (IncompleteReadError: {details})"
                        )
                        self.event_shutting_down.set()
                        await self._cleanup_on_error()
                        break
                    else:
                        logging.error(
                            f"Error in handle_incoming for peer {self.peer_id}: "
                            + f"{type(e).__name__}: {str(e)}"
                        )
                else:
                    logging.error(
                        f"Error in handle_incoming for peer {self.peer_id}: "
                        + f"{type(e).__name__}: {str(e)}"
                    )
                # Don't crash the whole connection for temporary errors
                if self.event_shutting_down.is_set() or isinstance(
                    e, (RawConnError, OSError)
                ):
                    await self._cleanup_on_error()
                    break
                # For other errors, log and continue
                await trio.sleep(0.01)

    async def _cleanup_on_error(self) -> None:
        # Set shutdown flag first to prevent other operations
        self.event_shutting_down.set()

        # Clean up streams
        async with self.streams_lock:
            for stream in self.streams.values():
                stream.closed = True
                stream.send_closed = True
                stream.recv_closed = True
                # Set the event so any waiters are woken up
                if stream.stream_id in self.stream_events:
                    self.stream_events[stream.stream_id].set()
            # Clear buffers and events
            self.stream_buffers.clear()
            self.stream_events.clear()

        # Close the secured connection
        try:
            await self.secured_conn.close()
            logging.debug(f"Successfully closed secured_conn for peer {self.peer_id}")
        except Exception as close_error:
            logging.error(
                f"Error closing secured_conn for peer {self.peer_id}: {close_error}"
            )

        # Set closed flag
        self.event_closed.set()

        # Call on_close callback if provided
        if self.on_close:
            logging.debug(f"Calling on_close for peer {self.peer_id}")
            try:
                if inspect.iscoroutinefunction(self.on_close):
                    await self.on_close()
                else:
                    self.on_close()
            except Exception as callback_error:
                logging.error(f"Error in on_close callback: {callback_error}")

        # Cancel nursery tasks
        if self._nursery:
            self._nursery.cancel_scope.cancel()
