import asyncio
from io import BytesIO

from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream

from .constants import HeaderTags


class MplexStream(IMuxedStream):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    stream_id: int
    initiator: bool
    mplex_conn: IMuxedConn
    read_deadline: int
    write_deadline: int
    local_closed: bool
    remote_closed: bool
    stream_lock: asyncio.Lock

    _buf: bytes

    def __init__(self, stream_id: int, initiator: bool, mplex_conn: IMuxedConn) -> None:
        """
        create new MuxedStream in muxer
        :param stream_id: stream stream id
        :param initiator: boolean if this is an initiator
        :param mplex_conn: muxed connection of this muxed_stream
        """
        self.stream_id = stream_id
        self.initiator = initiator
        self.mplex_conn = mplex_conn
        self.read_deadline = None
        self.write_deadline = None
        self.local_closed = False
        self.remote_closed = False
        self.stream_lock = asyncio.Lock()
        self._buf = None

    async def read(self, n: int = -1) -> bytes:
        """
        read messages associated with stream from buffer til end of file
        :param n: number of bytes to read
        :return: bytes of input
        """
        if n == -1:
            return await self.mplex_conn.read_buffer(self.stream_id)
        return await self.read_bytes(n)

    async def read_bytes(self, n: int) -> bytes:
        if self._buf is None:
            self._buf = await self.mplex_conn.read_buffer(self.stream_id)
        n_read = 0
        bytes_buf = BytesIO()
        while self._buf is not None and n_read < n:
            n_to_read = min(n - n_read, len(self._buf))
            bytes_buf.write(self._buf[:n_to_read])
            if n_to_read == n - n_read:
                self._buf = self._buf[n_to_read:]
            else:
                self._buf = None
                self._buf = await self.mplex_conn.read_buffer(self.stream_id)
            n_read += n_to_read
        return bytes_buf.getvalue()

    async def write(self, data: bytes) -> int:
        """
        write to stream
        :return: number of bytes written
        """
        flag = (
            HeaderTags.MessageInitiator
            if self.initiator
            else HeaderTags.MessageReceiver
        )
        return await self.mplex_conn.send_message(flag, data, self.stream_id)

    async def close(self) -> bool:
        """
        Closing a stream closes it for writing and closes the remote end for reading
        but allows writing in the other direction.
        :return: true if successful
        """
        # TODO error handling with timeout
        # TODO understand better how mutexes are used from go repo
        flag = HeaderTags.CloseInitiator if self.initiator else HeaderTags.CloseReceiver
        await self.mplex_conn.send_message(flag, None, self.stream_id)

        remote_lock = False
        async with self.stream_lock:
            if self.local_closed:
                return True
            self.local_closed = True
            remote_lock = self.remote_closed

        if remote_lock:
            # FIXME: mplex_conn has no conn_lock!
            async with self.mplex_conn.conn_lock:  # type: ignore
                # FIXME: Don't access to buffers directly
                self.mplex_conn.buffers.pop(self.stream_id)  # type: ignore

        return True

    async def reset(self) -> bool:
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: true if successful
        """
        # TODO understand better how mutexes are used here
        # TODO understand the difference between close and reset
        async with self.stream_lock:
            if self.remote_closed and self.local_closed:
                return True

            if not self.remote_closed:
                flag = (
                    HeaderTags.ResetInitiator
                    if self.initiator
                    else HeaderTags.ResetInitiator
                )
                await self.mplex_conn.send_message(flag, None, self.stream_id)

            self.local_closed = True
            self.remote_closed = True

        # FIXME: mplex_conn has no conn_lock!
        async with self.mplex_conn.conn_lock:  # type: ignore
            # FIXME: Don't access to buffers directly
            self.mplex_conn.buffers.pop(self.stream_id, None)  # type: ignore

        return True

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
