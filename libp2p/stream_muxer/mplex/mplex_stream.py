import asyncio

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

    _buf: bytearray

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
        self._buf = bytearray()

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to n bytes. Read possibly returns fewer than `n` bytes,
        if there are not enough bytes in the Mplex buffer.
        If `n == -1`, read until EOF.
        :param n: number of bytes to read
        :return: bytes actually read
        """
        if n < 0 and n != -1:
            raise ValueError("`n` can only be -1 if it is negative")
        # If the buffer is empty at first, blocking wait for data.
        if len(self._buf) == 0:
            self._buf.extend(await self.mplex_conn.read_buffer(self.stream_id))
        # Sanity check: `self._buf` should never be empty here.
        if self._buf is None or len(self._buf) == 0:
            raise Exception("`self._buf` should never be empty here")

        # FIXME: If `n == -1`, we should blocking read until EOF, instead of returning when
        #   no message is available.
        # If `n >= 0`, read up to `n` bytes.
        # Else, read until no message is available.
        while len(self._buf) < n or n == -1:
            new_bytes = await self.mplex_conn.read_buffer_nonblocking(self.stream_id)
            if new_bytes is None:
                # Nothing to read in the `MplexConn` buffer
                break
            self._buf.extend(new_bytes)
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
