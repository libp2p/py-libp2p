import asyncio

from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):

    conn_ip: str
    conn_port: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    _next_id: int
    initiator: bool

    def __init__(
        self,
        ip: str,
        port: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        initiator: bool,
    ) -> None:
        self.conn_ip = ip
        self.conn_port = port
        self.reader = reader
        self.writer = writer
        self._next_id = 0 if initiator else 1
        self.initiator = initiator

    async def write(self, data: bytes) -> None:
        self.writer.write(data)
        self.writer.write("\n".encode())
        await self.writer.drain()

    async def read(self) -> bytes:
        line = await self.reader.readline()
        return line.rstrip(b"\n")

    def close(self) -> None:
        self.writer.close()

    def next_stream_id(self) -> int:
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self._next_id
        self._next_id += 2
        return next_id
