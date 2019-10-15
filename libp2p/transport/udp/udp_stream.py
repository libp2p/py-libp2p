import asyncio
from io import BytesIO
from typing import Any

from asyncio_dgram.aio import DatagramStream
from libp2p.transport.stream_interface import IStream, IStreamReader, IStreamWriter
from libp2p.transport.udp.udp import UDPServer


class UDPStream(IStream):
    _stream: DatagramStream

    def __init__(self, stream: DatagramStream):
        self._stream = stream

    def get_extra_info(self, field: str) -> Any:
        return self._stream.__getattribute__(
            field
        )  # it is compatible with some TCP fields

    async def close(self) -> None:
        self._stream.close()  # it is safe to call close even though it is closed
        await asyncio.sleep(-1)


class UDPStreamReader(UDPStream, IStreamReader):
    _read_stream: BytesIO

    def __init__(self, stream: DatagramStream):
        UDPStream.__init__(self, stream)
        self._read_stream = BytesIO()

    async def read(self, n: int = -1) -> bytes:
        data = self._read_stream.read(n)
        while len(data) < n:
            await self._fill_read_stream()
            data_left = n - len(data)
            data += await self.read(data_left)
        self._read_stream.seek(0)
        return data

    async def _fill_read_stream(self) -> None:
        data, addr = await self._stream.recv()
        self._read_stream.write(data)
        self._read_stream.seek(0)


class UDPStreamWriter(UDPStream, IStreamWriter):
    _addr: Any

    def __init__(self, stream: DatagramStream, addr: Any = None):
        UDPStream.__init__(self, stream)
        self._addr = addr

    async def write(self, data: bytes) -> None:
        await self._stream.send(data, addr=self._addr)


class UDPServerStream:
    _server: UDPServer
    _addr: Any

    def __init__(self, server: UDPServer, addr: Any):
        self._server = server
        self._addr = addr

    async def close(self) -> None:
        self._server.close_handler_stream(self._addr)
        await asyncio.sleep(-1)


class UDPServerStreamReader(UDPServerStream, UDPStreamReader):
    _queue: asyncio.Queue[bytes]

    def __init__(
        self,
        stream: DatagramStream,
        server: UDPServer,
        addr: Any,
        queue: asyncio.Queue[bytes],
    ):
        UDPStreamReader.__init__(self, stream)
        UDPServerStream.__init__(self, server, addr)
        self._queue = queue

    async def _fill_read_stream(self) -> None:
        data = await self._queue.get()
        self._read_stream.write(data)
        self._read_stream.seek(0)


class UDPServerStreamWriter(UDPServerStream, UDPStreamWriter):
    def __init__(self, stream: DatagramStream, server: UDPServer, addr: Any):
        UDPStreamWriter.__init__(self, stream, addr)
        UDPServerStream.__init__(self, server, addr)
