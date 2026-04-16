"""
WebRTC data-channel stream.

Each libp2p stream maps to one WebRTC data channel.  Every write is wrapped
in a protobuf :class:`Message` with an optional :class:`Flag` for lifecycle
signaling.  The FIN/FIN_ACK/STOP_SENDING/RESET state machine follows the
libp2p WebRTC specification exactly.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import enum
import logging
from typing import TYPE_CHECKING

import trio

from libp2p.abc import IMuxedStream

from .constants import MAX_MESSAGE_SIZE
from .exceptions import WebRTCStreamError
from .pb.webrtc_pb2 import Message

if TYPE_CHECKING:
    from .connection import WebRTCConnection

logger = logging.getLogger(__name__)


class StreamState(enum.Enum):
    """Data-channel stream lifecycle states."""

    OPEN = "open"
    WRITE_CLOSED = "write_closed"  # Sent FIN, awaiting FIN_ACK
    READ_CLOSED = "read_closed"  # Sent STOP_SENDING
    CLOSED = "closed"  # Both sides done
    RESET = "reset"  # Abrupt termination


class WebRTCStream(IMuxedStream):
    """
    A single multiplexed stream over a WebRTC data channel.

    Implements :class:`IMuxedStream` with protobuf framing and the
    FIN/FIN_ACK lifecycle protocol from the spec.

    The stream does **not** interact with aiortc directly — it sends and
    receives raw bytes through callbacks registered by
    :class:`WebRTCConnection`.  This keeps the stream logic testable
    without an aiortc dependency.
    """

    def __init__(
        self,
        connection: WebRTCConnection,
        channel_id: int,
        is_initiator: bool,
        trio_token: trio.lowlevel.TrioToken | None = None,
    ) -> None:
        self.muxed_conn = connection
        self._channel_id = channel_id
        self._is_initiator = is_initiator
        self._state = StreamState.OPEN
        self._state_lock = trio.Lock()

        # Read side: incoming messages arrive via on_data() callback
        self._read_send: trio.MemorySendChannel[bytes]
        self._read_recv: trio.MemoryReceiveChannel[bytes]
        self._read_send, self._read_recv = trio.open_memory_channel[bytes](64)
        self._read_buf = bytearray()
        self._read_closed = False

        # Write side
        self._write_closed = False

        # FIN_ACK coordination
        self._fin_ack_received = trio.Event()

        # Deadline (seconds from epoch, or 0 for no deadline)
        self._deadline: float = 0.0

        # Callback for sending framed bytes over the data channel.
        # Set by WebRTCConnection after construction.
        self._send_callback: _SendCallback | None = None

        # Trio token used to safely route asyncio-side callbacks back to the
        # trio thread.  Prefer the explicitly-supplied token (the connection
        # passes its own trio_token when constructing inbound streams from
        # the asyncio thread).  Fall back to capturing one inline only when
        # we're already on a trio task (tests / outbound streams).
        if trio_token is not None:
            self._trio_token: trio.lowlevel.TrioToken | None = trio_token
        else:
            try:
                self._trio_token = trio.lowlevel.current_trio_token()
            except RuntimeError:
                self._trio_token = None

    @property
    def channel_id(self) -> int:
        """The WebRTC data channel ID for this stream."""
        return self._channel_id

    def get_remote_address(
        self,
    ) -> tuple[str, int] | None:  # pyrefly: ignore[bad-return]
        """Delegate to the connection (data channels share its address)."""
        # WebRTCConnection adds get_remote_address() on top of the bare
        # IMuxedConn ABC.  Fall back to None for any other muxed connection.
        get_addr = getattr(self.muxed_conn, "get_remote_address", None)
        if callable(get_addr):
            return get_addr()  # type: ignore[no-any-return]
        return None

    # ------------------------------------------------------------------
    # IMuxedStream: read
    # ------------------------------------------------------------------

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to *n* bytes from the stream.

        Blocks until data is available, the remote sends FIN, or the
        stream is reset.

        :param n: Maximum bytes to return.  ``None`` returns whatever is
            available in the next message.
        :returns: The bytes read (may be shorter than *n*).
        :raises WebRTCStreamError: If the stream was reset or closed.
        """
        if self._state == StreamState.RESET:
            raise WebRTCStreamError("Stream was reset")

        # Serve from internal buffer first
        if self._read_buf:
            return self._drain_buf(n)

        # Drain any remaining data from the channel (may have data even
        # after FIN if the message carried both payload and FIN flag).
        if self._read_closed:
            try:
                chunk = self._read_recv.receive_nowait()
                if chunk:  # Skip empty EOF sentinel
                    self._read_buf.extend(chunk)
                    return self._drain_buf(n)
            except (trio.WouldBlock, trio.EndOfChannel, trio.ClosedResourceError):
                pass
            raise WebRTCStreamError("Read side is closed")

        # Block for the next chunk
        try:
            if self._deadline > 0:
                timeout = max(0.0, self._deadline - trio.current_time())
                with trio.move_on_after(timeout) as scope:
                    chunk = await self._read_recv.receive()
                if scope.cancelled_caught:
                    raise WebRTCStreamError("Read deadline exceeded")
            else:
                chunk = await self._read_recv.receive()
        except trio.EndOfChannel:
            if self._read_buf:
                return self._drain_buf(n)
            raise WebRTCStreamError("Stream closed by remote") from None

        # Empty chunk is an EOF sentinel from on_data()
        if not chunk:
            self._read_closed = True
            raise WebRTCStreamError("Stream closed by remote")

        self._read_buf.extend(chunk)
        return self._drain_buf(n)

    def _drain_buf(self, n: int | None) -> bytes:
        """Return up to *n* bytes from the read buffer."""
        if n is None or n < 0 or n >= len(self._read_buf):
            data = bytes(self._read_buf)
            self._read_buf.clear()
            return data
        data = bytes(self._read_buf[:n])
        del self._read_buf[:n]
        return data

    # ------------------------------------------------------------------
    # IMuxedStream: write
    # ------------------------------------------------------------------

    async def write(self, data: bytes) -> None:
        """
        Write *data* to the stream, protobuf-framed.

        Large writes are split into chunks of at most
        :data:`MAX_MESSAGE_SIZE` bytes.

        :raises WebRTCStreamError: If the write side is closed or reset.
        """
        if self._state == StreamState.RESET:
            raise WebRTCStreamError("Stream was reset")
        if self._write_closed:
            raise WebRTCStreamError("Write side is closed")

        # Split into spec-compliant chunks
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + MAX_MESSAGE_SIZE]
            msg = Message(message=chunk)
            await self._send_message(msg)
            offset += len(chunk)

    # ------------------------------------------------------------------
    # IMuxedStream: close / reset
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """
        Gracefully close the stream (both read and write sides).

        Sends FIN, waits for FIN_ACK (with timeout), then closes.
        """
        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                return

        if not self._write_closed:
            await self._close_write()

        if not self._read_closed:
            self._close_read_side()

        async with self._state_lock:
            self._state = StreamState.CLOSED
        self._cleanup()

    async def reset(self) -> None:
        """
        Abruptly terminate the stream.

        Sends RESET and immediately tears down without waiting for
        acknowledgement.
        """
        async with self._state_lock:
            if self._state == StreamState.RESET:
                return
            self._state = StreamState.RESET

        try:
            await self._send_message(Message(flag=Message.RESET))
        except Exception:
            pass  # Best-effort
        self._cleanup()

    def set_deadline(self, ttl: int) -> None:
        """
        Set a deadline for future read operations.

        :param ttl: Seconds from now.  0 removes the deadline.
        """
        if ttl <= 0:
            self._deadline = 0.0
        else:
            self._deadline = trio.current_time() + ttl

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> WebRTCStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Data-channel callbacks (called by WebRTCConnection)
    # ------------------------------------------------------------------

    def on_data(self, raw: bytes) -> None:
        """
        Called by :class:`WebRTCConnection` when the data channel receives
        a protobuf-framed message.

        Parses the :class:`Message`, processes any flag, and enqueues
        payload bytes for :meth:`read`.

        May be invoked from the asyncio bridge thread (not a Trio task).
        To stay safe we route every Trio primitive call (memory channel,
        :class:`trio.Event`) through :func:`trio.from_thread.run_sync`
        with a captured :class:`trio.lowlevel.TrioToken`.  When called
        from within a Trio task (for example in unit tests) we execute
        the mutations inline.
        """
        msg = Message()
        msg.ParseFromString(raw)

        # Snapshot flags/payload first; all subsequent state mutations are
        # performed under the Trio thread.
        has_payload = msg.HasField("message") and bool(msg.message)
        payload = bytes(msg.message) if has_payload else b""
        has_flag = msg.HasField("flag")
        flag = msg.flag if has_flag else None

        def _apply_on_trio_thread() -> None:
            # Enqueue payload BEFORE processing flags — the spec allows a
            # message to carry both data and FIN, and the data must be
            # delivered to the reader before the read channel is closed.
            if has_payload:
                try:
                    self._read_send.send_nowait(payload)
                except trio.WouldBlock:
                    logger.warning(
                        "WebRTCStream channel=%d: read buffer full, dropping message",
                        self._channel_id,
                    )
                except trio.ClosedResourceError:
                    pass

            if has_flag:
                if flag == Message.FIN:
                    self._read_closed = True
                    self._enqueue_eof_sentinel_locked()
                    self._schedule_send(Message(flag=Message.FIN_ACK))
                elif flag == Message.FIN_ACK:
                    self._fin_ack_received.set()
                elif flag == Message.STOP_SENDING:
                    self._write_closed = True
                elif flag == Message.RESET:
                    self._state = StreamState.RESET
                    self._enqueue_eof_sentinel_locked()

        self._run_on_trio_thread(_apply_on_trio_thread)

    def _run_on_trio_thread(self, fn: Callable[[], None]) -> None:
        """
        Execute *fn* on the Trio thread.

        If we're already inside a Trio task, call directly.  Otherwise
        route through :func:`trio.from_thread.run_sync` using the token
        captured at construction time.  If no token was captured (e.g.
        tests that build a stream without a running Trio loop) fall back
        to a direct call — those tests never cross thread boundaries
        anyway.
        """
        token = self._trio_token
        try:
            trio.lowlevel.current_task()
            in_trio = True
        except RuntimeError:
            in_trio = False

        if in_trio or token is None:
            fn()
        else:
            try:
                trio.from_thread.run_sync(fn, trio_token=token)
            except trio.RunFinishedError:
                logger.debug(
                    "WebRTCStream channel=%d: trio run finished, dropping "
                    "asyncio-side callback",
                    self._channel_id,
                )

    def _enqueue_eof_sentinel_locked(self) -> None:
        """
        Send an empty sentinel to signal EOF to the trio-side reader.

        MUST be called from a Trio task — use via
        :meth:`_run_on_trio_thread` when routing from a foreign thread.
        """
        try:
            self._read_send.send_nowait(b"")
        except (trio.WouldBlock, trio.ClosedResourceError):
            pass

    # Preserved name for internal callers already on the Trio side.
    _enqueue_eof_sentinel = _enqueue_eof_sentinel_locked

    def on_channel_close(self) -> None:
        """Called when the underlying data channel is closed."""

        def _apply() -> None:
            self._read_closed = True
            self._write_closed = True
            self._enqueue_eof_sentinel_locked()

        self._run_on_trio_thread(_apply)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _close_write(self) -> None:
        """Send FIN and wait for FIN_ACK."""
        self._write_closed = True
        await self._send_message(Message(flag=Message.FIN))

        # Wait for FIN_ACK with a bounded timeout
        with trio.move_on_after(5.0):
            await self._fin_ack_received.wait()

        async with self._state_lock:
            self._state = StreamState.WRITE_CLOSED

    def _close_read_side(self) -> None:
        """Close the read side and send STOP_SENDING."""
        self._read_closed = True
        self._enqueue_eof_sentinel()
        self._schedule_send(Message(flag=Message.STOP_SENDING))

    async def _send_message(self, msg: Message) -> None:
        """Serialize and send a protobuf Message via the data channel."""
        if self._send_callback is None:
            raise WebRTCStreamError("Stream not connected to a data channel")
        data = msg.SerializeToString()
        await self._send_callback(data)

    def _schedule_send(self, msg: Message) -> None:
        """
        Best-effort send for flags from synchronous callbacks (on_data).

        Uses the connection's bridge to schedule the send as a fire-and-forget
        asyncio coroutine, since this method may be called from a non-trio
        thread.
        """
        if self._send_callback is None:
            return
        data = msg.SerializeToString()
        bridge = getattr(self.muxed_conn, "_bridge", None)
        # CRITICAL: do NOT use self._send_callback here.  That callback is
        # the trio-facing wrapper which itself awaits bridge.run_coro() —
        # invoking it via schedule_fire_and_forget would block the asyncio
        # thread on a future that can only be resolved from a trio task.
        # Bypass it and call the asyncio-native callback directly.
        send_cb = getattr(self.muxed_conn, "_send_on_channel_cb", None)
        if bridge is not None and bridge.is_running and send_cb is not None:
            bridge.schedule_fire_and_forget(send_cb(self._channel_id, data))

    def _cleanup(self) -> None:
        """Release resources."""
        try:
            self._read_send.close()
        except trio.ClosedResourceError:
            pass
        try:
            self._read_recv.close()
        except trio.ClosedResourceError:
            pass


# Type alias for the send callback
_SendCallback = Callable[[bytes], Awaitable[None]]
