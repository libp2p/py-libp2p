import asyncio
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.connection_interface import IConnection
from typing import Tuple
import msquic  # Assuming msquic Python bindings are available

class MsQuicConnection(IConnection):
    def __init__(self, stream):
        self.stream = stream

    async def read(self, n: int) -> bytes:
        return await self.stream.recv(n)

    async def write(self, data: bytes) -> None:
        await self.stream.send(data)

    async def close(self) -> None:
        await self.stream.close()

class MsQuicTransport(ITransport):
    def __init__(self):
        self.connections = []

    async def dial(self, peer_addr: Tuple[str, int]) -> MsQuicConnection:
        conn = msquic.connect(peer_addr[0], peer_addr[1])
        stream = await conn.open_stream()
        connection = MsQuicConnection(stream)
        self.connections.append(connection)
        return connection

    async def listen(self, listen_addr: Tuple[str, int]):
        listener = msquic.create_listener(listen_addr[0], listen_addr[1])
        async for stream in listener.accept():
            connection = MsQuicConnection(stream)
            self.connections.append(connection)
            yield connection

    async def close(self) -> None:
        for conn in self.connections:
            await conn.close()
        self.connections.clear()
