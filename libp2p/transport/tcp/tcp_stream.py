from asyncio import StreamReader, StreamWriter
from typing import Any, Tuple

from libp2p.transport.stream_interface import IStream, IStreamReader, IStreamWriter


class TCPStream(IStream):
    _write_stream: StreamWriter

    def __init__(self, write_stream: StreamWriter):
        self._write_stream = write_stream

    def get_extra_info(self, field: str) -> Any:
        return self._write_stream.get_extra_info(field)

    async def close(self) -> None:
        if not self._write_stream.is_closing():
            self._write_stream.close()
            await self._write_stream.wait_closed()

    @classmethod
    def from_asyncio_streams(
        cls, read_stream: StreamReader, write_stream: StreamWriter
    ) -> Tuple["TCPStreamReader", "TCPStreamWriter"]:
        return TCPStreamReader(read_stream, write_stream), TCPStreamWriter(write_stream)


class TCPStreamReader(TCPStream, IStreamReader):
    _read_stream: StreamReader

    def __init__(self, read_stream: StreamReader, write_stream: StreamWriter):
        TCPStream.__init__(self, write_stream)
        self._read_stream = read_stream

    async def read(self, n: int = -1) -> bytes:
        return await self._read_stream.read(n)


class TCPStreamWriter(TCPStream, IStreamWriter):
    async def write(self, data: bytes) -> None:
        self._write_stream.write(data)
        await self._write_stream.drain()
