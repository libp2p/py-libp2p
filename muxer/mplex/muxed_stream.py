from .muxed_stream_interface import IMuxedStream
from .constants import HEADER_TAGS


class MuxedStream(IMuxedStream):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
    """

    def __init__(self, stream_id, initiator, muxed_conn):
        """
        create new MuxedStream in muxer
        :param stream_id: stream stream id
        :param initiator: boolean if this is an initiator
        :param muxed_conn: muxed connection of this muxed_stream
        """
        self.stream_id = stream_id
        self.initiator = initiator
        self.muxed_conn = muxed_conn

        self.read_deadline = None
        self.write_deadline = None

        self.local_closed = False
        self.remote_closed = False

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
        return await self.muxed_conn.read_buffer(self.stream_id)

    async def write(self, data):
        """
        write to stream
        :return: number of bytes written
        """
        return await self.muxed_conn.send_message(self.get_flag("MESSAGE"), data, self.stream_id)

    def close(self):
        """
        close stream
        :return: true if successful
        """

        if self.local_closed and self.remote_closed:
            return True

        self.muxed_conn.send_message(self.get_flag("CLOSE"), None, self.stream_id)
        self.muxed_conn.streams.pop(self.stream_id)

        self.local_closed = True
        self.remote_closed = True

        return True

    def reset(self):
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: true if successful
        """
        # TODO behavior not fully understood
        pass
        # if self.local_closed and self.remote_closed:
        #     return True
        #
        # self.muxed_conn.send_message(self.get_flag("RESET"), None, self.id)
        # self.muxed_conn.streams.pop(self.id, None)
        #
        # self.local_closed = True
        # self.remote_closed = True
        #
        # return True

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
