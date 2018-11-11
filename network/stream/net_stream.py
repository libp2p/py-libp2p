import asyncio
from .net_stream_interface import INetStream

class NetStream(INetStream):

    def __init__(self, muxed_stream):
        self.muxed_stream = muxed_stream

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
        :return: bytes of input until EOF
        """
        return self.muxed_stream.read()

    def write(self, bytes):
        """
        write to stream
        :return: number of bytes written
        """
        return self.muxed_stream.write(bytes)

    def close(self):
        """
        close stream
        :return: true if successful
        """
        self.muxed_stream.close()
        return True
