from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.stream_muxer.abc import IMuxedStream
from libp2p.stream_muxer.mplex.utils import decode_uvarint_from_stream, encode_uvarint
from libp2p.typing import StreamReader

from .multiselect_communicator_interface import IMultiselectCommunicator


def delim_encode(msg_str: str) -> bytes:
    msg_bytes = msg_str.encode()
    varint_len_msg = encode_uvarint(len(msg_bytes) + 1)
    return varint_len_msg + msg_bytes + b"\n"


async def delim_read(reader: StreamReader, timeout: int = 10) -> str:
    len_msg = await decode_uvarint_from_stream(reader, timeout)
    msg_bytes = await reader.read(len_msg)
    return msg_bytes.decode().rstrip()


class RawConnectionCommunicator(IMultiselectCommunicator):
    conn: IRawConnection

    def __init__(self, conn: IRawConnection) -> None:
        self.conn = conn

    async def write(self, msg_str: str) -> None:
        msg_bytes = delim_encode(msg_str)
        self.conn.writer.write(msg_bytes)
        await self.conn.writer.drain()

    async def read(self) -> str:
        return await delim_read(self.conn.reader)


class StreamCommunicator(IMultiselectCommunicator):
    stream: IMuxedStream

    def __init__(self, stream: IMuxedStream) -> None:
        self.stream = stream

    async def write(self, msg_str: str) -> None:
        msg_bytes = delim_encode(msg_str)
        await self.stream.write(msg_bytes)

    async def read(self) -> str:
        return await delim_read(self.stream)
