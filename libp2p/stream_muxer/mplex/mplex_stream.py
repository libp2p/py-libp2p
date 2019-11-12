import asyncio
from typing import TYPE_CHECKING

from libp2p.stream_muxer.abc import IMuxedStream

from .constants import HeaderTags
from .datastructures import StreamID
from .exceptions import MplexStreamClosed, MplexStreamEOF, MplexStreamReset

if TYPE_CHECKING:
    from libp2p.stream_muxer.mplex.mplex import Mplex


class MplexStream(IMuxedStream):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    name: str
    stream_id: StreamID
    muxed_conn: "Mplex"
    read_deadline: int
    write_deadline: int

    close_lock: asyncio.Lock

    # NOTE: `dataIn` is size of 8 in Go implementation.
    incoming_data: "asyncio.Queue[bytes]"

    event_local_closed: asyncio.Event
    event_remote_closed: asyncio.Event
    event_reset: asyncio.Event

    _buf: bytearray

    def __init__(self, name: str, stream_id: StreamID, muxed_conn: "Mplex") -> None:
        """
        create new MuxedStream in muxer.

        :param stream_id: stream id of this stream
        :param muxed_conn: muxed connection of this muxed_stream
        """
        self.name = name
        self.stream_id = stream_id
        self.muxed_conn = muxed_conn
        self.read_deadline = None
        self.write_deadline = None
        self.event_local_closed = asyncio.Event()
        self.event_remote_closed = asyncio.Event()
        self.event_reset = asyncio.Event()
        self.close_lock = asyncio.Lock()
        self.incoming_data = asyncio.Queue()
        self._buf = bytearray()

    @property
    def is_initiator(self) -> bool:
        return self.stream_id.is_initiator

    async def _wait_for_data(self) -> None:
        task_event_reset = asyncio.ensure_future(self.event_reset.wait())
        task_incoming_data_get = asyncio.ensure_future(self.incoming_data.get())
        task_event_remote_closed = asyncio.ensure_future(
            self.event_remote_closed.wait()
        )
        done, pending = await asyncio.wait(  # type: ignore
            [  # type: ignore
                task_event_reset,
                task_incoming_data_get,
                task_event_remote_closed,
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for fut in pending:
            fut.cancel()

        if task_event_reset in done:
            if self.event_reset.is_set():
                raise MplexStreamReset
            else:
                # However, it is abnormal that `Event.wait` is unblocked without any of the flag
                #   is set. The task is probably cancelled.
                raise Exception(
                    "Should not enter here. "
                    f"It is probably because {task_event_remote_closed} is cancelled."
                )

        if task_incoming_data_get in done:
            data = task_incoming_data_get.result()
            self._buf.extend(data)
            return

        if task_event_remote_closed in done:
            if self.event_remote_closed.is_set():
                raise MplexStreamEOF
            else:
                # However, it is abnormal that `Event.wait` is unblocked without any of the flag
                #   is set. The task is probably cancelled.
                raise Exception(
                    "Should not enter here. "
                    f"It is probably because {task_event_remote_closed} is cancelled."
                )

        # TODO: Handle timeout when deadline is used.

    async def _read_until_eof(self) -> bytes:
        while True:
            try:
                await self._wait_for_data()
            except MplexStreamEOF:
                break
        payload = self._buf
        self._buf = self._buf[len(payload) :]
        return bytes(payload)

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to n bytes. Read possibly returns fewer than `n` bytes, if
        there are not enough bytes in the Mplex buffer. If `n == -1`, read
        until EOF.

        :param n: number of bytes to read
        :return: bytes actually read
        """
        if n < 0 and n != -1:
            raise ValueError(
                f"the number of bytes to read `n` must be positive or -1 to indicate read until EOF"
            )
        if self.event_reset.is_set():
            raise MplexStreamReset
        if n == -1:
            return await self._read_until_eof()
        if len(self._buf) == 0 and self.incoming_data.empty():
            await self._wait_for_data()
        # Now we are sure we have something to read.
        # Try to put enough incoming data into `self._buf`.
        while len(self._buf) < n:
            try:
                self._buf.extend(self.incoming_data.get_nowait())
            except asyncio.QueueEmpty:
                break
        payload = self._buf[:n]
        self._buf = self._buf[len(payload) :]
        return bytes(payload)

    async def write(self, data: bytes) -> int:
        """
        write to stream.

        :return: number of bytes written
        """
        if self.event_local_closed.is_set():
            raise MplexStreamClosed(f"cannot write to closed stream: data={data!r}")
        flag = (
            HeaderTags.MessageInitiator
            if self.is_initiator
            else HeaderTags.MessageReceiver
        )
        return await self.muxed_conn.send_message(flag, data, self.stream_id)

    async def close(self) -> None:
        """Closing a stream closes it for writing and closes the remote end for
        reading but allows writing in the other direction."""
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
                del self.muxed_conn.streams[self.stream_id]

    async def reset(self) -> None:
        """closes both ends of the stream tells this remote side to hang up."""
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
                asyncio.ensure_future(
                    self.muxed_conn.send_message(flag, None, self.stream_id)
                )
                await asyncio.sleep(0)

            self.event_local_closed.set()
            self.event_remote_closed.set()

        async with self.muxed_conn.streams_lock:
            if (
                self.muxed_conn.streams is not None
                and self.stream_id in self.muxed_conn.streams
            ):
                del self.muxed_conn.streams[self.stream_id]

    # TODO deadline not in use
    def set_deadline(self, ttl: int) -> bool:
        """
        set deadline for muxed stream.

        :return: True if successful
        """
        self.read_deadline = ttl
        self.write_deadline = ttl
        return True

    def set_read_deadline(self, ttl: int) -> bool:
        """
        set read deadline for muxed stream.

        :return: True if successful
        """
        self.read_deadline = ttl
        return True

    def set_write_deadline(self, ttl: int) -> bool:
        """
        set write deadline for muxed stream.

        :return: True if successful
        """
        self.write_deadline = ttl
        return True
