from .net_stream_interface import INetStream


class NetStream(INetStream):

    def __init__(self, muxed_stream):
        """
        Create a new NetStream instance
        :param muxed_stream: An IMuxedConn instance
        """
        self.muxed_stream = muxed_stream
        self.mplex_conn = muxed_stream.mplex_conn
        self.protocol_id = None

    def get_protocol(self):
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id):
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        self.protocol_id = protocol_id

    async def read(self):
        """
        read from stream
        :return: bytes of input until EOF
        """
        return await self.muxed_stream.read()

    async def write(self, data):
        """
        write to stream
        :return: number of bytes written
        """
        return await self.muxed_stream.write(data)

    def close(self):
        """
        close stream
        :return: true if successful
        """
        if self.muxed_stream is None: return False
        if not self.muxed_stream.close(): return False
        self.muxed_stream = None
        return True

    def shutdown(self, options=None):
        """
        Launch the start of the stream and underlying connection,
        usefull for closing multiple conns at once.
        :param options: optional object potential with a timeout value
        in ms that fires and destroy all connections
        :return: return True if successful
        """
        if self.muxed_stream is None:
            return False
        self.muxed_stream.shutdown()
        return True

    async def wait_closed(self):
        """
        Wait until the connection is closed. Usefull for closing multiple
        connection at once. Must be used after shutdown.
        For an all in one close use close.
        :return: return True if successful
        """
        if self.muxed_stream is None: return False
        return await self.muxed_stream.wait_close()
