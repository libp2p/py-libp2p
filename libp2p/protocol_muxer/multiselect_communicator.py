from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.stream_muxer.abc import IMuxedStream
from libp2p.utils import encode_delim, read_delim

from .multiselect_communicator_interface import IMultiselectCommunicator


class RawConnectionCommunicator(IMultiselectCommunicator):
    conn: IRawConnection

    def __init__(self, conn: IRawConnection) -> None:
        self.conn = conn

    async def write(self, msg_str: str) -> None:
        msg_bytes = encode_delim(msg_str)
        self.conn.writer.write(msg_bytes)
        await self.conn.writer.drain()

    async def read(self) -> str:
        return await read_delim(self.conn.reader)


class StreamCommunicator(IMultiselectCommunicator):
    stream: IMuxedStream

    def __init__(self, stream: IMuxedStream) -> None:
        self.stream = stream

    async def write(self, msg_str: str) -> None:
        msg_bytes = encode_delim(msg_str)
        await self.stream.write(msg_bytes)

    async def read(self) -> str:
        return await read_delim(self.stream)
