from types import (
    TracebackType,
)
from typing import (
    TYPE_CHECKING,
)

import trio

from libp2p.abc import (
    IMuxedStream,
)
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)

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

    # TODO: Add lock for read/write to avoid interleaving receiving messages?
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
        """
        if n is not None and n < 0:
            raise ValueError(
                "the number of bytes to read `n` must be non-negative or "
                f"`None` to indicate read until EOF, got n={n}"
            )
        if self.event_reset.is_set():
            raise MplexStreamReset
        if n is None:
            return await self._read_until_eof()
        if len(self._buf) == 0:
            data: bytes
            # Peek whether there is data available. If yes, we just read until there is
            # no data, then return.
            try:
                data = self.incoming_data_channel.receive_nowait()
                self._buf.extend(data)
            except trio.EndOfChannel:
                raise MplexStreamEOF
            except trio.WouldBlock:
                # We know `receive` will be blocked here. Wait for data here with
                # `receive` and catch all kinds of errors here.
                try:
                    data = await self.incoming_data_channel.receive()
                    self._buf.extend(data)
                except trio.EndOfChannel:
                    if self.event_reset.is_set():
                        raise MplexStreamReset
                    if self.event_remote_closed.is_set():
                        raise MplexStreamEOF
                except trio.ClosedResourceError as error:
                    # Probably `incoming_data_channel` is closed in `reset` when we are
                    # waiting for `receive`.
                    if self.event_reset.is_set():
                        raise MplexStreamReset
                    raise Exception(
                        "`incoming_data_channel` is closed but stream is not reset. "
                        "This should never happen."
                    ) from error
        self._buf.extend(self._read_return_when_blocked())
        payload = self._buf[:n]
        self._buf = self._buf[len(payload) :]
        return bytes(payload)

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :return: number of bytes written
        """
        if self.event_local_closed.is_set():
            raise MplexStreamClosed(f"cannot write to closed stream: data={data!r}")
        flag = (
            HeaderTags.MessageInitiator
            if self.is_initiator
            else HeaderTags.MessageReceiver
        )
        await self.muxed_conn.send_message(flag, data, self.stream_id)

    async def close(self) -> None:
        """
        Closing a stream closes it for writing and closes the remote end for
        reading but allows writing in the other direction.
        """
        # TODO error handling with timeout

        async with self.close_lock:
            if self.event_local_closed.is_set():
                return

        flag = (
            HeaderTags.CloseInitiator if self.is_initiator else HeaderTags.CloseReceiver
        )
        # TODO: Raise when `muxed_conn.send_message` fails and `Mplex` isn't shutdown.
        await self.muxed_conn.send_message(flag, None, self.stream_id)

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
                flag = (
                    HeaderTags.ResetInitiator
                    if self.is_initiator
                    else HeaderTags.ResetReceiver
                )
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

    # TODO deadline not in use
    def set_deadline(self, ttl: int) -> bool:
        """
        Set deadline for muxed stream.

        :return: True if successful
        """
        self.read_deadline = ttl
        self.write_deadline = ttl
        return True

    def set_read_deadline(self, ttl: int) -> bool:
        """
        Set read deadline for muxed stream.

        :return: True if successful
        """
        self.read_deadline = ttl
        return True

    def set_write_deadline(self, ttl: int) -> bool:
        """
        Set write deadline for muxed stream.

        :return: True if successful
        """
        self.write_deadline = ttl
        return True

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
