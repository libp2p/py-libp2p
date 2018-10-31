import asyncio
from .stream_interface import IStream

class Stream(IStream):

    def __init__(self, peer_id, multi_addr, connection):
        IStream.__init__(self, peer_id, multi_addr)
        self.peer_id = peer_id

        stream_ip = multi_addr.get_protocol_value("ip4")
        stream_port = multi_addr.get_protocol_value("tcp")
        self.reader = connection.reader
        self.writer = connection.writer
        # TODO should construct protocol id from constructor
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

    def read(self):
        """
        read from stream
        :return: bytes of input
        """
        return self.reader.read(-1)

    def write(self, _bytes):
        """
        write to stream
        :return: number of bytes written
        """
        return self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes):
        to_return = self.writer.write(_bytes)
        await self.writer.drain()
        return to_return

    def close(self):
        """
        close stream
        :return: true if successful
        """
        self.writer.close()
