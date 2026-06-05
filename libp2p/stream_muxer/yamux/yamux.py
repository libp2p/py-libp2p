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
import os
import struct
from types import (
    TracebackType,
)
from typing import (
    Any,
)

import multiaddr
import trio
from trio import (
    MemoryReceiveChannel,
    MemorySendChannel,
    Nursery,
)

from libp2p.abc import (
    ConnectionType,
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

_PERF_YAMUX_DEBUG_LOG_INTERVAL = 500
_DEFAULT_ASSUME_RTT_MS = 1.0

# Python-only yamux tuning (PY_YAMUX_*).
#
# Set in the environment before the process starts. The unified-testing perf
# harness forwards these to python-v0.x listener/dialer containers only; the
# local runner (`scripts/perf/run_local_perf.py`) passes them through as well.
# Helpers below read os.environ at call time (no reload).
#
#   PY_YAMUX_RELEASE_ON_READ (default: on)
#       When hysteresis defers GrowTo, release recv-window credit on read via
#       WINDOW_UPDATE instead of waiting for the next GrowTo batch.
#   PY_YAMUX_ASSUME_RTT_MS (default: 1 ms when unset and ping RTT is 0)
#       Bootstrap RTT in milliseconds for send-window autotune before the first
#       measured ping RTT is available.
#   PY_YAMUX_BATCH_THRESHOLD_DIV (default: 2, minimum: 1)
#       GrowTo / pending-batch threshold = target_recv_window // divisor.
#   PY_YAMUX_DISABLE_HYSTERESIS (default: off)
#       Debug escape hatch: any positive window delta triggers a full GrowTo.
#   PY_YAMUX_DEBUG (default: off)
#       Emit targeted [YAMUX_PERF] logs. Not the same as LIBP2P_DEBUG, which
#       enables full py-libp2p module logging via libp2p.utils.logging.
#
# Example scenarios (local runner from py-libp2p root; Docker: use ./perf/run.sh
# with the same PY_YAMUX_* exports on the host — forwarded to python-v0.x only):
#
#   # Default autotune + hysteresis (baseline throughput)
#   ./scripts/perf/run_local_perf.py --quick -t tcp -s noise -m yamux
#
#   # A/B: disable hysteresis (every positive delta → full GrowTo)
#   PY_YAMUX_DISABLE_HYSTERESIS=1 ./scripts/perf/run_local_perf.py --quick
#
#   # Higher assumed RTT before first ping (slow-start / WAN-like bootstrap)
#   PY_YAMUX_ASSUME_RTT_MS=50 ./scripts/perf/run_local_perf.py --quick
#
#   # More aggressive GrowTo batches (threshold = target // 1 vs default // 2)
#   PY_YAMUX_BATCH_THRESHOLD_DIV=1 ./scripts/perf/run_local_perf.py --quick
#
#   # Hysteresis on but no WINDOW_UPDATE on read (credit release deferred)
#   PY_YAMUX_RELEASE_ON_READ=0 ./scripts/perf/run_local_perf.py --quick
#
#   # Targeted window/autotune traces ([YAMUX_PERF], low overhead)
#   PY_YAMUX_DEBUG=1 ./scripts/perf/run_local_perf.py --quick
#   ./scripts/perf/run_local_perf.py --debug   # same + broader perf_test loggers
#
#   # Full module trace (very verbose; not for 1 GiB benchmarks)
#   LIBP2P_DEBUG=stream_muxer.yamux:DEBUG ./scripts/perf/run_local_perf.py --quick


def _py_yamux_env(name: str, default: str = "") -> str:
    """Read PY_YAMUX_* tuning env (perf harness or local runner)."""
    return os.getenv(f"PY_YAMUX_{name}", default)


def _py_yamux_env_set(name: str) -> bool:
    return f"PY_YAMUX_{name}" in os.environ


def _perf_yamux_debug_enabled() -> bool:
    return _py_yamux_env("DEBUG", "").upper() in ("1", "TRUE", "YES")


def _yamux_disable_hysteresis() -> bool:
    """Debug escape hatch: treat any positive delta as a full GrowTo."""
    return _py_yamux_env("DISABLE_HYSTERESIS", "").upper() in (
        "1",
        "TRUE",
        "YES",
    )


def _yamux_release_on_read() -> bool:
    """When true, send WINDOW_UPDATE for bytes_read if hysteresis defers GrowTo."""
    return _py_yamux_env("RELEASE_ON_READ", "1").upper() not in (
        "0",
        "FALSE",
        "NO",
    )


def _yamux_batch_threshold_divisor() -> int:
    """GrowTo / pending batch threshold = target_recv_window // divisor (default 2)."""
    raw = _py_yamux_env("BATCH_THRESHOLD_DIV", "2")
    try:
        div = int(raw)
    except ValueError:
        div = 2
    return max(div, 1)


def _perf_yamux_log(msg: str) -> None:
    if _perf_yamux_debug_enabled():
        print(f"[YAMUX_PERF] {msg}", flush=True)


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
MAX_WINDOW_SIZE = 16 * 1024 * 1024  # 16 MB max receive window (matches go-yamux)
MAX_MESSAGE_SIZE = 64 * 1024  # 64KB max frame payload, matches go-yamux default
RTT_MEASURE_INTERVAL = 30  # seconds between RTT measurements

GO_AWAY_NORMAL = 0x0
GO_AWAY_PROTOCOL_ERROR = 0x1
GO_AWAY_INTERNAL_ERROR = 0x2


class YamuxStream(IMuxedStream):
    target_recv_window: int
    epoch_start: float

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
        self.target_recv_window = DEFAULT_WINDOW_SIZE  # grows up to MAX_WINDOW_SIZE
        self.epoch_start = 0.0  # trio.current_time() of last window update
        self.rw_lock = ReadWriteLock()
        self.close_lock = trio.Lock()
        self._zero_window_waits = 0
        self._window_update_hysteresis_skips = 0
        self._window_update_bytes_read_only = 0
        self._window_update_full_grow = 0
        self._window_update_pending_flush = 0
        self._window_update_partial_slack = 0
        self._pending_recv_release = 0

    def _effective_rtt(self) -> float:
        """Measured RTT, or PY_YAMUX_ASSUME_RTT_MS / default when ping RTT is 0."""
        rtt = self.conn.rtt()
        if rtt > 0:
            return rtt
        if _py_yamux_env_set("ASSUME_RTT_MS"):
            raw = _py_yamux_env("ASSUME_RTT_MS", "").strip()
            try:
                return max(float(raw), 0.0) / 1000.0
            except ValueError:
                return 0.0
        return _DEFAULT_ASSUME_RTT_MS / 1000.0

    def _grow_threshold(self) -> int:
        if _yamux_disable_hysteresis():
            return 0
        return self.target_recv_window // _yamux_batch_threshold_divisor()

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

        total_len = len(data)
        sent = 0
        logger.debug(f"Stream {self.stream_id}: Starts writing {total_len} bytes ")
        while sent < total_len:
            frame: bytes | None = None
            while frame is None:
                async with self.rw_lock.write_lock():
                    if self.send_closed:
                        raise MuxedStreamError("Stream is closed for sending")
                    async with self.window_lock:
                        if self.closed:
                            raise MuxedStreamError("Stream is closed")
                        if self.send_window > 0:
                            to_send = min(
                                self.send_window,
                                MAX_MESSAGE_SIZE - HEADER_SIZE,
                                total_len - sent,
                            )
                            chunk = data[sent : sent + to_send]
                            self.send_window -= to_send
                            header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_DATA,
                                0,
                                self.stream_id,
                                len(chunk),
                            )
                            frame = header + chunk

                if frame is not None:
                    break

                self._zero_window_waits += 1
                if (
                    _perf_yamux_debug_enabled()
                    and self._zero_window_waits % _PERF_YAMUX_DEBUG_LOG_INTERVAL == 1
                ):
                    _perf_yamux_log(
                        f"stream={self.stream_id} zero_window_waits="
                        f"{self._zero_window_waits} send_window={self.send_window} "
                        f"recv_window={self.recv_window} "
                        f"target={self.target_recv_window}"
                    )
                logger.debug(
                    f"Stream {self.stream_id}: Window is zero, waiting for update"
                )
                with trio.move_on_after(5.0) as cancel_scope:
                    while True:
                        async with self.window_lock:
                            if self.send_window > 0 or self.closed:
                                break
                        await trio.sleep(0.01)
                if cancel_scope.cancelled_caught:
                    raise MuxedStreamError(
                        "Timed out waiting for window update after 5 seconds."
                    )

            await self.conn._write_frame(frame)
            sent += len(frame) - HEADER_SIZE

    async def send_window_update(self, increment: int, skip_lock: bool = False) -> None:
        """
        Send a window update to peer.

        param:increment: The amount to increment the window size by.
        If None, uses the difference between DEFAULT_WINDOW_SIZE
        and current receive window.
        param:skip_lock (bool): Unused (retained for API compatibility).

        Never hold ``window_lock`` across this await — inbound WINDOW_UPDATE handling
        also needs ``window_lock`` to adjust ``send_window`` concurrently.

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
                await self.conn._write_frame(header)
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

        # Never hold window_lock across _write_frame: inbound WINDOW_UPDATE handlers
        # need window_lock concurrently to adjust send_window.
        _ = skip_lock
        await _do_window_update()

    def _grow_to_delta(self, buffered: int) -> int:
        """Apply GrowTo slack (caller checks hysteresis threshold)."""
        delta = self.target_recv_window - (self.recv_window + buffered)
        if delta <= 0:
            return 0
        self.recv_window += delta
        return delta

    def _apply_autotune_epoch(self, buffered: int) -> int:
        """Double target within 4×RTT when sending an update; return extra increment."""
        rtt = self._effective_rtt()
        now = trio.current_time()
        if rtt <= 0:
            self.epoch_start = now
            return 0

        if self.epoch_start > 0 and (now - self.epoch_start) >= rtt * 4:
            self.epoch_start = now
            return 0

        extra_delta = 0
        new_target = min(self.target_recv_window * 2, MAX_WINDOW_SIZE)
        if new_target > self.target_recv_window:
            self.target_recv_window = new_target
            new_current = self.recv_window + buffered
            grow = self.target_recv_window - new_current
            if grow > 0:
                self.recv_window += grow
                extra_delta = grow

        self.epoch_start = now
        logger.debug(
            f"Stream {self.stream_id}: Auto-tune extra_delta={extra_delta}, "
            f"target={self.target_recv_window}"
        )
        return extra_delta

    async def _auto_tune_and_send_window_update(
        self: "YamuxStream", *, bytes_read: int = 0
    ) -> None:
        """
        Auto-tune receive window size and send WINDOW_UPDATE (go-yamux semantics).

        Mirrors go-yamux ``sendWindowUpdate`` + ``GrowTo`` hysteresis (half window),
        with ``_pending_recv_release`` so several smaller reads batch into one
        large update like repeated ``Read()`` calls in Go.
        """
        total_delta = 0
        async with self.window_lock:
            if bytes_read > 0:
                self._pending_recv_release += bytes_read

            buffered = len(self.conn.stream_buffers.get(self.stream_id, b""))
            delta = self.target_recv_window - (self.recv_window + buffered)
            threshold = self._grow_threshold()
            pending = self._pending_recv_release

            if delta >= threshold and delta > 0:
                self._window_update_full_grow += 1
                total_delta = self._grow_to_delta(buffered)
                total_delta += self._apply_autotune_epoch(buffered)
                self._pending_recv_release = 0
            elif pending >= threshold:
                self.recv_window += pending
                total_delta = pending
                self._pending_recv_release = 0
                self._window_update_pending_flush += 1
                total_delta += self._apply_autotune_epoch(buffered)
            elif 0 < delta < threshold and bytes_read > 0:
                self._window_update_partial_slack += 1
                self.recv_window += delta + bytes_read
                total_delta = delta + bytes_read
                self._pending_recv_release -= bytes_read
                total_delta += self._apply_autotune_epoch(buffered)
            elif _yamux_release_on_read() and bytes_read > 0:
                self.recv_window += bytes_read
                total_delta = bytes_read
                self._pending_recv_release -= bytes_read
                self._window_update_bytes_read_only += 1
                total_delta += self._apply_autotune_epoch(buffered)
            elif delta < threshold and bytes_read == 0:
                if _perf_yamux_debug_enabled():
                    self._window_update_hysteresis_skips += 1

        if total_delta > 0:
            await self.send_window_update(total_delta, skip_lock=True)

    def _log_perf_yamux_summary(self) -> None:
        if not _perf_yamux_debug_enabled():
            return
        _perf_yamux_log(
            f"stream={self.stream_id} summary "
            f"zero_window_waits={self._zero_window_waits} "
            f"hysteresis_skips={self._window_update_hysteresis_skips} "
            f"bytes_read_updates={self._window_update_bytes_read_only} "
            f"partial_slack={self._window_update_partial_slack} "
            f"full_grow_updates={self._window_update_full_grow} "
            f"pending_flush={self._window_update_pending_flush} "
            f"target={self.target_recv_window}"
        )

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

                # If we have data in buffer, process in MAX_MESSAGE_SIZE slices
                # (like bounded Read in go-yamux) so hysteresis can batch credit.
                while len(buffer) > 0:
                    take = min(len(buffer), MAX_MESSAGE_SIZE)
                    chunk = bytes(buffer[:take])
                    del buffer[:take]
                    data += chunk
                    await self._auto_tune_and_send_window_update(bytes_read=len(chunk))

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
            await self._auto_tune_and_send_window_update(bytes_read=len(data))
            return data

    async def close(self) -> None:
        self._log_perf_yamux_summary()
        async with self.close_lock:
            if not self.send_closed:
                logger.debug(f"Half-closing stream {self.stream_id} (local end)")
                try:
                    header = struct.pack(
                        YAMUX_HEADER_FORMAT,
                        0,
                        TYPE_WINDOW_UPDATE,
                        FLAG_FIN,
                        self.stream_id,
                        0,
                    )
                    await self.conn._write_frame(header)
                except (RawConnError, ConnectionClosedError) as e:
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
                        YAMUX_HEADER_FORMAT,
                        0,
                        TYPE_WINDOW_UPDATE,
                        FLAG_RST,
                        self.stream_id,
                        0,
                    )
                    await self.conn._write_frame(header)
                except (RawConnError, ConnectionClosedError) as e:
                    logger.debug(f"Error sending RST, connection likely closed: {e}")
                finally:
                    self.closed = True
                    self.send_closed = True
                    self.recv_closed = True
                    self.reset_received = True  # Mark as reset

    def set_deadline(self, ttl: int) -> None:
        """
        Set a deadline for the stream. Yamux does not support deadlines natively.

        :param ttl: Time-to-live in seconds (ignored).
        :raises NotImplementedError: Yamux does not support setting deadlines.
        """
        raise NotImplementedError("Yamux does not support setting read deadlines")

    def get_remote_address(self) -> tuple[str, int] | None:
        """Return the transport remote endpoint via the muxed connection."""
        return self.conn.get_remote_address()


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
        self._write_lock = trio.Lock()
        self._nursery: Nursery | None = None
        self._established: bool = False
        self._rtt: float = 0.0  # smoothed RTT in seconds
        self._ping_id: int = 0  # incrementing ping nonce
        self._ping_sent_time: float = 0.0  # trio.current_time() when ping sent
        self._ping_event: trio.Event = trio.Event()

    def rtt(self) -> float:
        """Return the current smoothed RTT estimate in seconds."""
        return self._rtt

    async def _measure_rtt_loop(self) -> None:
        """Background task that periodically measures RTT via ping/pong."""
        # Initial delay to let the connection establish
        await trio.sleep(0.5)
        while not self.event_shutting_down.is_set():
            try:
                self._ping_id += 1
                self._ping_event = trio.Event()
                header = struct.pack(
                    YAMUX_HEADER_FORMAT, 0, TYPE_PING, FLAG_SYN, 0, self._ping_id
                )
                await self._write_frame(header)
                # Record time AFTER write completes, matching go-yamux which
                # times after dispatch to avoid including write-lock wait time.
                self._ping_sent_time = trio.current_time()
                # Wait for pong with timeout
                with trio.move_on_after(10.0):
                    await self._ping_event.wait()
            except Exception:
                # Connection likely closed, exit the loop
                break
            if self.event_shutting_down.is_set():
                break
            # Sleep between measurements, checking shutdown periodically
            with trio.move_on_after(RTT_MEASURE_INTERVAL):
                while not self.event_shutting_down.is_set():
                    await trio.sleep(1.0)

    @property
    def is_established(self) -> bool:
        """
        Check if the Yamux connection is fully established and ready for streams.

        Returns True when:
        - The event_started has been set
        - The handle_incoming task is actively running
        - The connection is not shutting down
        """
        return (
            self._established
            and self.event_started.is_set()
            and not self.event_shutting_down.is_set()
        )

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

            nursery.start_soon(self._measure_rtt_loop)
            # Use nursery.start() to ensure handle_incoming has started
            # before we set event_started. This prevents race conditions
            # where streams are opened before the muxer is ready.
            # When handle_incoming exits, the finally block cancels the nursery.
            await nursery.start(self._handle_incoming_with_ready_signal)

            logger.debug(f"Yamux.start() setting event_started for {self.peer_id}")
            self._established = True
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
                    await self._write_frame(header)
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

    def get_transport_addresses(self) -> list[multiaddr.Multiaddr]:
        """
        Get transport addresses by delegating to secured_conn.
        """
        return self.secured_conn.get_transport_addresses()

    def get_connection_type(self) -> ConnectionType:
        """
        Get connection type by delegating to secured_conn.
        """
        return self.secured_conn.get_connection_type()

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Return the transport-level remote endpoint, same as :class:`Mplex`.

        Delegates to ``secured_conn`` so callers (e.g. host subsystems) can
        resolve the peer address without opening a stream — matching
        :meth:`~libp2p.stream_muxer.mplex.mplex.Mplex.get_remote_address`.
        """
        return self.secured_conn.get_remote_address()

    async def _write_frame(self, data: bytes) -> None:
        """Write a frame to the connection, serializing all writes."""
        if len(data) >= HEADER_SIZE:
            _, typ, flags, sid, length = struct.unpack(
                YAMUX_HEADER_FORMAT, data[:HEADER_SIZE]
            )
            flag_names = []
            if flags & FLAG_SYN:
                flag_names.append("SYN")
            if flags & FLAG_ACK:
                flag_names.append("ACK")
            if flags & FLAG_FIN:
                flag_names.append("FIN")
            if flags & FLAG_RST:
                flag_names.append("RST")
            type_names = {0: "DATA", 1: "WINDOW_UPDATE", 2: "PING", 3: "GO_AWAY"}
            logger.debug(
                f"YAMUX TX: type={type_names.get(typ, typ)} "
                f"flags={'+'.join(flag_names) or '0'} "
                f"stream={sid} length={length} "
                f"is_initiator={self.is_initiator_value} "
                f"payload_bytes={len(data) - HEADER_SIZE}"
            )
        async with self._write_lock:
            await self.secured_conn.write(data)
        await trio.lowlevel.checkpoint()

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
                YAMUX_HEADER_FORMAT,
                0,
                TYPE_WINDOW_UPDATE,
                FLAG_SYN,
                stream_id,
                0,
            )
            logger.debug(f"Sending SYN header for stream {stream_id}")
            await self._write_frame(header)
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

    async def _handle_incoming_with_ready_signal(
        self, task_status: Any = trio.TASK_STATUS_IGNORED
    ) -> None:
        """
        Wrapper for handle_incoming that signals when the task is ready.

        This method uses trio's task_status to signal that the handle_incoming
        loop is ready to process frames. This prevents race conditions where
        streams are opened before the muxer is ready to handle them.
        When handle_incoming exits, this cancels the nursery scope.
        """
        logger.debug(
            f"Yamux _handle_incoming_with_ready_signal() starting for "
            f"peer {self.peer_id}"
        )
        task_status.started()
        try:
            await self.handle_incoming()
        finally:
            if self._nursery is not None:
                self._nursery.cancel_scope.cancel()

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
                type_names = {0: "DATA", 1: "WINDOW_UPDATE", 2: "PING", 3: "GO_AWAY"}
                flag_names = []
                if flags & FLAG_SYN:
                    flag_names.append("SYN")
                if flags & FLAG_ACK:
                    flag_names.append("ACK")
                if flags & FLAG_FIN:
                    flag_names.append("FIN")
                if flags & FLAG_RST:
                    flag_names.append("RST")
                logger.debug(
                    f"YAMUX RX: type={type_names.get(typ, typ)} "
                    f"flags={'+'.join(flag_names) or '0'} "
                    f"stream={stream_id} length={length} "
                    f"is_initiator={self.is_initiator_value}"
                )
                if (typ == TYPE_DATA or typ == TYPE_WINDOW_UPDATE) and flags & FLAG_SYN:
                    syn_payload: bytes = b""
                    syn_payload_err: IncompleteReadError | None = None
                    if typ == TYPE_DATA and length > 0:
                        try:
                            syn_payload = await read_exactly(self.secured_conn, length)
                        except IncompleteReadError as e:
                            syn_payload_err = e
                            logger.error(
                                "Incomplete read for SYN data on "
                                f"stream {stream_id}: {e}"
                            )

                    rst_header: bytes | None = None
                    ack_header: bytes | None = None
                    new_stream_notify: YamuxStream | None = None
                    async with self.streams_lock:
                        if stream_id not in self.streams:
                            stream = YamuxStream(stream_id, self, False)
                            self.streams[stream_id] = stream
                            self.stream_buffers[stream_id] = bytearray()
                            self.stream_events[stream_id] = trio.Event()

                            if syn_payload_err is not None:
                                stream.recv_closed = True
                                stream.closed = True
                                self.stream_events[stream_id].set()
                            elif typ == TYPE_WINDOW_UPDATE and length > 0:
                                # Window update SYN: length is a delta
                                async with stream.window_lock:
                                    stream.send_window += length
                                logger.debug(
                                    f"SYN window update for stream "
                                    f"{stream_id}: window={length}"
                                )
                            elif typ == TYPE_DATA and length > 0:
                                self.stream_buffers[stream_id].extend(syn_payload)
                                stream.recv_window -= len(syn_payload)
                                if stream.recv_window < 0:
                                    logger.warning(
                                        f"Stream {stream_id}: peer exceeded "
                                        f"receive window by "
                                        f"{-stream.recv_window} bytes"
                                    )
                                    stream.recv_window = 0
                                self.stream_events[stream_id].set()
                                logger.debug(
                                    f"Read {length} bytes with SYN "
                                    f"for stream {stream_id}"
                                )

                            # FIN and RST flags may be sent with SYN frames
                            if flags & FLAG_FIN:
                                logger.debug(
                                    f"Received FIN for stream {self.peer_id}:"
                                    f"{stream_id} with SYN, marking recv_closed"
                                )
                                stream.recv_closed = True
                                if stream.send_closed:
                                    stream.closed = True
                                self.stream_events[stream_id].set()

                            if flags & FLAG_RST:
                                logger.debug(
                                    f"Resetting stream {stream_id} for peer"
                                    f"{self.peer_id} with SYN"
                                )
                                stream.closed = True
                                stream.reset_received = True
                                self.stream_events[stream_id].set()

                            ack_header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_WINDOW_UPDATE,
                                FLAG_ACK,
                                stream_id,
                                0,
                            )
                            new_stream_notify = stream
                        else:
                            rst_header = struct.pack(
                                YAMUX_HEADER_FORMAT,
                                0,
                                TYPE_WINDOW_UPDATE,
                                FLAG_RST,
                                stream_id,
                                0,
                            )

                    if rst_header is not None:
                        await self._write_frame(rst_header)
                    elif ack_header is not None:
                        await self._write_frame(ack_header)
                        logger.debug(
                            f"Sending stream {stream_id}"
                            f"to channel for peer {self.peer_id}"
                        )
                        if new_stream_notify is not None:
                            await self.new_stream_send_channel.send(new_stream_notify)
                elif (
                    typ == TYPE_DATA or typ == TYPE_WINDOW_UPDATE
                ) and flags & FLAG_ACK:
                    ack_payload: bytes = b""
                    ack_payload_err: IncompleteReadError | None = None
                    if typ == TYPE_DATA and length > 0:
                        try:
                            ack_payload = await read_exactly(self.secured_conn, length)
                        except IncompleteReadError as e:
                            ack_payload_err = e
                            logger.error(
                                "Incomplete read for ACK data on "
                                f"stream {stream_id}: {e}"
                            )
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            stream = self.streams[stream_id]
                            if typ == TYPE_WINDOW_UPDATE:
                                # Window update ACK: length is a delta
                                # (matches go-yamux incrSendWindow).
                                if length > 0:
                                    async with stream.window_lock:
                                        stream.send_window += length
                                logger.debug(
                                    f"Received WINDOW_UPDATE ACK for stream "
                                    f"{stream_id}, send_window={length} "
                                    f"for peer {self.peer_id}"
                                )
                            elif typ == TYPE_DATA and length > 0:
                                if ack_payload_err is not None:
                                    stream.recv_closed = True
                                    stream.closed = True
                                    if stream_id in self.stream_events:
                                        self.stream_events[stream_id].set()
                                else:
                                    self.stream_buffers[stream_id].extend(ack_payload)
                                    self.streams[stream_id].recv_window -= len(
                                        ack_payload
                                    )
                                    if self.streams[stream_id].recv_window < 0:
                                        logger.warning(
                                            f"Stream {stream_id}: peer exceeded "
                                            f"receive window by "
                                            f"{-self.streams[stream_id].recv_window}"
                                            f" bytes"
                                        )
                                        self.streams[stream_id].recv_window = 0
                                    self.stream_events[stream_id].set()
                                    logger.debug(
                                        f"Received ACK with {length} bytes "
                                        f"for stream {stream_id} "
                                        f"for peer {self.peer_id}"
                                    )
                            else:
                                logger.debug(
                                    f"Received ACK (no data) for stream "
                                    f"{stream_id} for peer {self.peer_id}"
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
                        await self._write_frame(ping_header)
                    elif flags & FLAG_ACK:
                        # Compute RTT with exponential smoothing
                        now = trio.current_time()
                        new_rtt = now - self._ping_sent_time
                        if self._rtt == 0.0:
                            self._rtt = new_rtt
                        else:
                            self._rtt = (self._rtt + new_rtt) / 2
                        self._ping_event.set()
                        logger.debug(
                            f"Received ping response with value"
                            f"{length} for peer {self.peer_id}, rtt={self._rtt:.4f}s"
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
                                self.streams[stream_id].recv_window -= len(data)
                                if self.streams[stream_id].recv_window < 0:
                                    logger.warning(
                                        f"Stream {stream_id}: peer exceeded "
                                        f"receive window by "
                                        f"{-self.streams[stream_id].recv_window}"
                                        f" bytes"
                                    )
                                    self.streams[stream_id].recv_window = 0
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
