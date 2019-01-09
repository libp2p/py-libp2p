import asyncio

from .constants import HEADER_TAGS
from ..muxed_stream_interface import IMuxedStream


class MplexStream(IMuxedStream):
    # pylint: disable=too-many-instance-attributes
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    def __init__(self, stream_id, initiator, mplex_conn):
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

    def get_flag(self, action):
        """
        get header flag based on action for mplex
        :param action: action type in str
        :return: int flag
        """
        if self.initiator:
            return HEADER_TAGS[action]

        return HEADER_TAGS[action] - 1

    async def read(self):
        """
        read messages associated with stream from buffer til end of file
        :return: bytes of input
        """
        return await self.mplex_conn.read_buffer(self.stream_id)

    async def write(self, data):
        """
        write to stream
        :return: number of bytes written
        """
        return await self.mplex_conn.send_message(self.get_flag("MESSAGE"), data, self.stream_id)

    async def close(self):
        """
        Closing a stream closes it for writing and closes the remote end for reading
        but allows writing in the other direction.
        :return: true if successful
        """
        # TODO error handling with timeout
        # TODO understand better how mutexes are used from go repo
        await self.mplex_conn.send_message(self.get_flag("CLOSE"), None, self.stream_id)

        remote_lock = ""
        async with self.stream_lock:
            if self.local_closed:
                return True
            self.local_closed = True
            remote_lock = self.remote_closed

        if remote_lock:
            async with self.mplex_conn.conn_lock:
                self.mplex_conn.buffers.pop(self.stream_id)

        return True

    async def reset(self):
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
                await self.mplex_conn.send_message(self.get_flag("RESET"), None, self.stream_id)

            self.local_closed = True
            self.remote_closed = True

        async with self.mplex_conn.conn_lock:
            self.mplex_conn.buffers.pop(self.stream_id, None)

        return True

    # TODO deadline not in use
    def set_deadline(self, ttl):
        """
        set deadline for muxed stream
        :return: True if successful
        """
        self.read_deadline = ttl
        self.write_deadline = ttl
        return True

    def set_read_deadline(self, ttl):
        """
        set read deadline for muxed stream
        :return: True if successful
        """
        self.read_deadline = ttl
        return True

    def set_write_deadline(self, ttl):
        """
        set write deadline for muxed stream
        :return: True if successful
        """
        self.write_deadline = ttl
        return True
