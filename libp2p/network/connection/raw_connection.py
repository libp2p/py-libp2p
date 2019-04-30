import asyncio
from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):

    def __init__(self, ip, port, reader, writer, initiator):
        # pylint: disable=too-many-arguments
        self.conn_ip = ip
        self.conn_port = port
        self.reader = reader
        self.writer = writer
        self._next_id = 0 if initiator else 1
        self.initiator = initiator

    async def write(self, data):
        self.writer.write(data)
        self.writer.write("\n".encode())
        await self.writer.drain()

    async def read(self):
        line = await self.reader.readline()
        adjusted_line = line.decode().rstrip('\n')

        # TODO: figure out a way to remove \n without going back and forth with
        # encoding and decoding
        return adjusted_line.encode()

    def close(self):
        self.writer.close()

    def next_stream_id(self):
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self._next_id
        self._next_id += 2
        return next_id
