from .net_stream_interface import INetStream


class NetStream(INetStream):

    def __init__(self, muxed_stream):
        self.muxed_stream = muxed_stream
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

    async def close(self):
        """
        close stream
        :return: true if successful
        """
        await self.muxed_stream.close()
        return True
