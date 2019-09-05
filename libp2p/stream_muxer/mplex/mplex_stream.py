import asyncio
from typing import TYPE_CHECKING

from libp2p.stream_muxer.abc import IMuxedStream

from .constants import HeaderTags
from .exceptions import MplexStreamReset, MplexStreamEOF
from .datastructures import StreamID

if TYPE_CHECKING:
    from libp2p.stream_muxer.mplex.mplex import Mplex


class MplexStream(IMuxedStream):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    name: str
    stream_id: StreamID
    mplex_conn: "Mplex"
    read_deadline: int
    write_deadline: int

    close_lock: asyncio.Lock

    incoming_data: "asyncio.Queue[bytes]"

    event_local_closed: asyncio.Event
    event_remote_closed: asyncio.Event
    event_reset: asyncio.Event

    _buf: bytearray

    def __init__(self, name: str, stream_id: StreamID, mplex_conn: "Mplex") -> None:
        """
        create new MuxedStream in muxer
        :param stream_id: stream id of this stream
        :param mplex_conn: muxed connection of this muxed_stream
        """
        self.name = name
        self.stream_id = stream_id
        self.mplex_conn = mplex_conn
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
        print("!@# _wait_for_data: 0")
        done, pending = await asyncio.wait(
            [
                self.event_reset.wait(),
                self.event_remote_closed.wait(),
                self.incoming_data.get(),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        print("!@# _wait_for_data: 1")
        if self.event_reset.is_set():
            raise MplexStreamReset
        if self.event_remote_closed.is_set():
            while not self.incoming_data.empty():
                self._buf.extend(await self.incoming_data.get())
            raise MplexStreamEOF
        data = tuple(done)[0].result()
        self._buf.extend(data)

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to n bytes. Read possibly returns fewer than `n` bytes,
        if there are not enough bytes in the Mplex buffer.
        If `n == -1`, read until EOF.
        :param n: number of bytes to read
        :return: bytes actually read
        """
        # TODO: Add exceptions and handle/raise them in this class.
        if n < 0 and n != -1:
            raise ValueError(
                f"the number of bytes to read `n` must be positive or -1 to indicate read until EOF"
            )

        # FIXME: If `n == -1`, we should blocking read until EOF, instead of returning when
        #   no message is available.
        # If `n >= 0`, read up to `n` bytes.
        # Else, read until no message is available.
        while len(self._buf) < n or n == -1:
            # new_bytes = await self.incoming_data.get()
            try:
                await self._wait_for_data()
            except MplexStreamEOF:
                break
        payload: bytearray
        if n == -1:
            payload = self._buf
        else:
            payload = self._buf[:n]
        self._buf = self._buf[len(payload) :]
        return bytes(payload)

    async def write(self, data: bytes) -> int:
        """
        write to stream
        :return: number of bytes written
        """
        flag = (
            HeaderTags.MessageInitiator
            if self.is_initiator
            else HeaderTags.MessageReceiver
        )
        return await self.mplex_conn.send_message(flag, data, self.stream_id)

    async def close(self) -> None:
        """
        Closing a stream closes it for writing and closes the remote end for reading
        but allows writing in the other direction.
        """
        # TODO error handling with timeout

        async with self.close_lock:
            if self.event_local_closed.is_set():
                return

        flag = (
            HeaderTags.CloseInitiator if self.is_initiator else HeaderTags.CloseReceiver
        )
        # TODO: Raise when `mplex_conn.send_message` fails and `Mplex` isn't shutdown.
        await self.mplex_conn.send_message(flag, None, self.stream_id)

        _is_remote_closed: bool
        async with self.close_lock:
            self.event_local_closed.set()
            _is_remote_closed = self.event_remote_closed.is_set()

        if _is_remote_closed:
            # Both sides are closed, we can safely remove the buffer from the dict.
            async with self.mplex_conn.streams_lock:
                del self.mplex_conn.streams[self.stream_id]

    async def reset(self) -> None:
        """
        closes both ends of the stream
        tells this remote side to hang up
        """
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
                    self.mplex_conn.send_message(flag, None, self.stream_id)
                )
                await asyncio.sleep(0)

            self.event_local_closed.set()
            self.event_remote_closed.set()

        async with self.mplex_conn.streams_lock:
            del self.mplex_conn.streams[self.stream_id]

    # TODO deadline not in use
    def set_deadline(self, ttl: int) -> bool:
        """
        set deadline for muxed stream
        :return: True if successful
        """
        self.read_deadline = ttl
        self.write_deadline = ttl
        return True

    def set_read_deadline(self, ttl: int) -> bool:
        """
        set read deadline for muxed stream
        :return: True if successful
        """
        self.read_deadline = ttl
        return True

    def set_write_deadline(self, ttl: int) -> bool:
        """
        set write deadline for muxed stream
        :return: True if successful
        """
        self.write_deadline = ttl
        return True
