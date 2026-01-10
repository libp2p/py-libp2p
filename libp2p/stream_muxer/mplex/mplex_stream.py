from collections.abc import Awaitable, Callable
import logging
from types import (
    TracebackType,
)
from typing import (
    TYPE_CHECKING,
    Any,
)

import trio

from libp2p.abc import (
    IMuxedStream,
)
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)
from libp2p.stream_muxer.rw_lock import ReadWriteLock

from .constants import (
    HeaderTags,
)
from .datastructures import (
    StreamID,
)
from .exceptions import (
    MplexStreamClosed,
    MplexStreamEOF,
    MplexStreamReset,
)

logger = logging.getLogger("libp2p.stream_muxer.mplex.mplex_stream")
# Enable debug logging for mplex troubleshooting
logger.setLevel(logging.DEBUG)

if TYPE_CHECKING:
    from libp2p.stream_muxer.mplex.mplex import (
        Mplex,
    )


class MplexStream(IMuxedStream):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    name: str
    stream_id: StreamID
    # NOTE: All methods used here are part of `Mplex` which is a derived
    # class of IMuxedConn. Ignoring this type assignment should not pose
    # any risk.
    muxed_conn: "Mplex"  # type: ignore[assignment]
    read_deadline: int | None
    write_deadline: int | None

    rw_lock: ReadWriteLock
    close_lock: trio.Lock

    # NOTE: `dataIn` is size of 8 in Go implementation.
    incoming_data_channel: "trio.MemoryReceiveChannel[bytes]"

    event_local_closed: trio.Event
    event_remote_closed: trio.Event
    event_reset: trio.Event

    _buf: bytearray

    def __init__(
        self,
        name: str,
        stream_id: StreamID,
        muxed_conn: "Mplex",
        incoming_data_channel: "trio.MemoryReceiveChannel[bytes]",
    ) -> None:
        """
        Create new MuxedStream in muxer.

        :param stream_id: stream id of this stream
        :param muxed_conn: muxed connection of this muxed_stream
        """
        self.name = name
        self.stream_id = stream_id
        self.muxed_conn = muxed_conn
        self.read_deadline = None
        self.write_deadline = None
        self.event_local_closed = trio.Event()
        self.event_remote_closed = trio.Event()
        self.event_reset = trio.Event()
        self.close_lock = trio.Lock()
        self.rw_lock = ReadWriteLock()
        self.incoming_data_channel = incoming_data_channel
        self._buf = bytearray()

    @property
    def is_initiator(self) -> bool:
        return self.stream_id.is_initiator

    async def _read_until_eof(self) -> bytes:
        async for data in self.incoming_data_channel:
            self._buf.extend(data)
        payload = self._buf
        self._buf = self._buf[len(payload) :]
        return bytes(payload)

    def _read_return_when_blocked(self) -> bytearray:
        buf = bytearray()
        while True:
            try:
                data = self.incoming_data_channel.receive_nowait()
                buf.extend(data)
            except (trio.WouldBlock, trio.EndOfChannel):
                break
        return buf

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes. Read possibly returns fewer than `n` bytes, if
        there are not enough bytes in the Mplex buffer. If `n is None`, read
        until EOF.

        :param n: number of bytes to read
        :return: bytes actually read
        :raises TimeoutError: if read_deadline is set and operation times out
        :raises MplexStreamReset: if stream has been reset
        :raises MplexStreamEOF: if stream has reached end of file
        :raises ValueError: if n is negative
        """
        # Check if stream is already reset before attempting operation
        if self.event_reset.is_set():
            raise MplexStreamReset

        # Apply read deadline if set
        return await self._with_timeout(
            self.read_deadline, "Read", lambda: self._do_read(n)
        )

    async def _do_read(self, n: int | None = None) -> bytes:
        """
        Internal read implementation that performs the actual read operation.

        :param n: number of bytes to read
        :return: bytes actually read
        """
        peer_id = getattr(self.muxed_conn, "peer_id", "unknown")
        logger.debug(
            f"[MPLEX_STREAM] _do_read: starting read "
            f"stream_id={self.stream_id}, n={n}, peer_id={peer_id}"
        )
        async with self.rw_lock.read_lock():
            logger.debug(
                f"[MPLEX_STREAM] _do_read: acquired read lock "
                f"stream_id={self.stream_id}, peer_id={peer_id}"
            )
            if n is not None and n < 0:
                raise ValueError(
                    "the number of bytes to read `n` must be non-negative or "
                    f"`None` to indicate read until EOF, got n={n}"
                )
            if n is None:
                logger.debug(
                    f"[MPLEX_STREAM] _do_read: reading until EOF "
                    f"stream_id={self.stream_id}, peer_id={peer_id}"
                )
                return await self._read_until_eof()
            # Try to read buffered data first, even if reset is set
            # This allows reading data that arrived before the reset
            logger.debug(
                f"[MPLEX_STREAM] _do_read: checking buffer "
                f"stream_id={self.stream_id}, buf_len={len(self._buf)}, "
                f"peer_id={peer_id}"
            )
            if len(self._buf) == 0:
                data: bytes
                # Peek whether there is data available. If yes, we just read until
                # there is no data, then return.
                try:
                    data = self.incoming_data_channel.receive_nowait()
                    logger.debug(
                        f"[MPLEX_STREAM] _do_read: received data non-blocking "
                        f"stream_id={self.stream_id}, data_len={len(data)}, "
                        f"peer_id={peer_id}"
                    )
                    self._buf.extend(data)
                except trio.EndOfChannel:
                    logger.debug(
                        f"[MPLEX_STREAM] _do_read: EndOfChannel "
                        f"stream_id={self.stream_id}, "
                        f"reset={self.event_reset.is_set()}, "
                        f"buf_len={len(self._buf)}, peer_id={peer_id}"
                    )
                    # If reset is set, raise reset only if no data was buffered
                    # This allows reading data that arrived before the reset
                    if self.event_reset.is_set() and len(self._buf) == 0:
                        logger.debug(
                            f"[MPLEX_STREAM] _do_read: raising MplexStreamReset "
                            f"stream_id={self.stream_id}, peer_id={peer_id}"
                        )
                        raise MplexStreamReset
                    raise MplexStreamEOF
                except trio.WouldBlock:
                    logger.debug(
                        f"[MPLEX_STREAM] _do_read: WouldBlock, waiting for data "
                        f"stream_id={self.stream_id}, peer_id={peer_id}"
                    )
                    # We know `receive` will be blocked here. Wait for data here with
                    # `receive` and catch all kinds of errors here.
                    try:
                        data = await self.incoming_data_channel.receive()
                        logger.debug(
                            f"[MPLEX_STREAM] _do_read: received data blocking "
                            f"stream_id={self.stream_id}, data_len={len(data)}, "
                            f"peer_id={peer_id}"
                        )
                        self._buf.extend(data)
                    except trio.EndOfChannel:
                        logger.debug(
                            f"[MPLEX_STREAM] _do_read: EndOfChannel during "
                            f"blocking receive stream_id={self.stream_id}, "
                            f"reset={self.event_reset.is_set()}, "
                            f"buf_len={len(self._buf)}, peer_id={peer_id}"
                        )
                        # If reset is set, raise reset only if no data was buffered
                        # This allows reading data that arrived before the reset
                        if self.event_reset.is_set() and len(self._buf) == 0:
                            raise MplexStreamReset
                        if self.event_remote_closed.is_set():
                            raise MplexStreamEOF
                    except trio.ClosedResourceError as error:
                        # Probably `incoming_data_channel` is closed in `reset` when
                        # we are waiting for `receive`.
                        if self.event_reset.is_set():
                            raise MplexStreamReset
                        raise Exception(
                            "`incoming_data_channel` is closed but stream is not reset."
                            "This should never happen."
                        ) from error
            # Try to read any remaining data from channel (non-blocking)
            additional_data = self._read_return_when_blocked()
            if len(additional_data) > 0:
                logger.debug(
                    f"[MPLEX_STREAM] _do_read: read additional data "
                    f"stream_id={self.stream_id}, "
                    f"additional_len={len(additional_data)}, peer_id={peer_id}"
                )
            self._buf.extend(additional_data)
            # If we have data in buffer, return it even if reset is set
            # This allows reading data that arrived before the reset
            if len(self._buf) > 0:
                payload = self._buf[:n]
                self._buf = self._buf[len(payload) :]
                logger.debug(
                    f"[MPLEX_STREAM] _do_read: returning data "
                    f"stream_id={self.stream_id}, payload_len={len(payload)}, "
                    f"remaining_buf_len={len(self._buf)}, peer_id={peer_id}"
                )
                return bytes(payload)
            # Only raise reset if no data is available
            if self.event_reset.is_set():
                logger.debug(
                    f"[MPLEX_STREAM] _do_read: raising MplexStreamReset (no data) "
                    f"stream_id={self.stream_id}, peer_id={peer_id}"
                )
                raise MplexStreamReset
            # Should not reach here, but return empty bytes as fallback
            logger.warning(
                f"[MPLEX_STREAM] _do_read: returning empty bytes (unexpected) "
                f"stream_id={self.stream_id}, peer_id={peer_id}"
            )
            return b""

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :param data: bytes to write
        :raises TimeoutError: if write_deadline is set and operation times out
        :raises MplexStreamClosed: if stream is closed for writing
        """
        # Check if stream is already closed before attempting operation
        if self.event_local_closed.is_set():
            raise MplexStreamClosed(f"cannot write to closed stream: data={data!r}")

        # Apply write deadline if set
        await self._with_timeout(
            self.write_deadline, "Write", lambda: self._do_write(data)
        )

    async def _do_write(self, data: bytes) -> None:
        """
        Internal write implementation that performs the actual write operation.

        :param data: bytes to write
        """
        peer_id = getattr(self.muxed_conn, "peer_id", "unknown")
        logger.debug(
            f"[MPLEX_STREAM] _do_write: starting write "
            f"stream_id={self.stream_id}, data_len={len(data)}, peer_id={peer_id}"
        )
        async with self.rw_lock.write_lock():
            logger.debug(
                f"[MPLEX_STREAM] _do_write: acquired write lock "
                f"stream_id={self.stream_id}, peer_id={peer_id}"
            )
            if self.event_local_closed.is_set():
                logger.error(
                    f"[MPLEX_STREAM] _do_write: stream closed "
                    f"stream_id={self.stream_id}, peer_id={peer_id}"
                )
                raise MplexStreamClosed(f"cannot write to closed stream: data={data!r}")
            flag = self._get_header_flag("message")
            logger.debug(
                f"[MPLEX_STREAM] _do_write: sending message "
                f"stream_id={self.stream_id}, flag={flag.name}, peer_id={peer_id}"
            )
            await self.muxed_conn.send_message(flag, data, self.stream_id)
            logger.debug(
                f"[MPLEX_STREAM] _do_write: write completed "
                f"stream_id={self.stream_id}, peer_id={peer_id}"
            )

    async def close(self) -> None:
        """
        Closing a stream closes it for writing and closes the remote end for
        reading but allows writing in the other direction.
        """
        async with self.close_lock:
            if self.event_local_closed.is_set():
                return

        flag = self._get_header_flag("close")

        try:
            with trio.fail_after(5):  # timeout in seconds
                await self.muxed_conn.send_message(flag, None, self.stream_id)
        except trio.TooSlowError:
            raise TimeoutError("Timeout while trying to close the stream")
        except MuxedConnUnavailable:
            if not self.muxed_conn.event_shutting_down.is_set():
                raise RuntimeError(
                    "Failed to send close message and Mplex isn't shutting down"
                )

        _is_remote_closed: bool
        async with self.close_lock:
            self.event_local_closed.set()
            _is_remote_closed = self.event_remote_closed.is_set()

        if _is_remote_closed:
            # Both sides are closed, we can safely remove the buffer from the dict.
            async with self.muxed_conn.streams_lock:
                self.muxed_conn.streams.pop(self.stream_id, None)

    async def reset(self) -> None:
        """Close both ends of the stream tells this remote side to hang up."""
        async with self.close_lock:
            # Both sides have been closed. No need to event_reset.
            if self.event_remote_closed.is_set() and self.event_local_closed.is_set():
                return
            if self.event_reset.is_set():
                return
            self.event_reset.set()

            if not self.event_remote_closed.is_set():
                flag = self._get_header_flag("reset")
                # Try to send reset message to the other side.
                # Ignore if there is anything wrong.
                try:
                    await self.muxed_conn.send_message(flag, None, self.stream_id)
                except MuxedConnUnavailable:
                    pass

            self.event_local_closed.set()
            self.event_remote_closed.set()

            await self.incoming_data_channel.aclose()

        async with self.muxed_conn.streams_lock:
            if self.muxed_conn.streams is not None:
                self.muxed_conn.streams.pop(self.stream_id, None)

    def _validate_ttl(self, ttl: int) -> bool:
        """
        Validate TTL value for deadline operations.

        :param ttl: timeout value to validate
        :return: True if valid (non-negative), False otherwise
        """
        return ttl >= 0

    def _set_deadline_with_validation(self, ttl: int, deadline_attr: str) -> bool:
        """
        Set deadline with validation for a specific deadline attribute.

        :param ttl: timeout value
        :param deadline_attr: attribute name to set ('read_deadline' or
            'write_deadline')
        :return: True if successful, False if ttl is invalid
        """
        if not self._validate_ttl(ttl):
            return False
        setattr(self, deadline_attr, ttl)
        return True

    async def _with_timeout(
        self,
        timeout: int | None,
        operation_name: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """
        Execute an operation with optional timeout handling.

        :param timeout: timeout in seconds, None for no timeout
        :param operation_name: name of the operation for error messages
        :param operation: callable to execute
        :return: result of the operation
        :raises TimeoutError: if operation times out
        """
        if timeout is None:
            return await operation()

        try:
            with trio.fail_after(timeout):
                return await operation()
        except trio.TooSlowError:
            raise TimeoutError(
                f"{operation_name} operation timed out after {timeout} seconds"
            )

    def _get_header_flag(self, operation_type: str) -> HeaderTags:
        """
        Get appropriate header flag based on operation type and initiator status.

        :param operation_type: type of operation ('message', 'close', 'reset')
        :return: appropriate HeaderTags value
        """
        flag_map = {
            "message": (HeaderTags.MessageInitiator, HeaderTags.MessageReceiver),
            "close": (HeaderTags.CloseInitiator, HeaderTags.CloseReceiver),
            "reset": (HeaderTags.ResetInitiator, HeaderTags.ResetReceiver),
        }
        initiator_flag, receiver_flag = flag_map[operation_type]
        return initiator_flag if self.is_initiator else receiver_flag

    def set_deadline(self, ttl: int) -> bool:
        """
        Set deadline for both read and write operations on the muxed stream.

        The deadline is enforced for the entire operation including lock acquisition.
        If the operation takes longer than the specified timeout, a TimeoutError
        is raised.

        :param ttl: timeout in seconds for read and write operations
        :return: True if successful, False if ttl is invalid (negative)
        """
        if not self._validate_ttl(ttl):
            return False
        self.read_deadline = ttl
        self.write_deadline = ttl
        return True

    def set_read_deadline(self, ttl: int) -> bool:
        """
        Set read deadline for muxed stream.

        The deadline is enforced for the entire read operation including lock
        acquisition. If the read operation takes longer than the specified timeout,
        a TimeoutError is raised.

        :param ttl: timeout in seconds for read operations
        :return: True if successful, False if ttl is invalid (negative)
        """
        return self._set_deadline_with_validation(ttl, "read_deadline")

    def set_write_deadline(self, ttl: int) -> bool:
        """
        Set write deadline for muxed stream.

        The deadline is enforced for the entire write operation including lock
        acquisition. If the write operation takes longer than the specified timeout,
        a TimeoutError is raised.

        :param ttl: timeout in seconds for write operations
        :return: True if successful, False if ttl is invalid (negative)
        """
        return self._set_deadline_with_validation(ttl, "write_deadline")

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the parent Mplex connection."""
        return self.muxed_conn.get_remote_address()

    async def __aenter__(self) -> "MplexStream":
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
