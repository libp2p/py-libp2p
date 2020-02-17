"""
``msgio`` is an implementation of `https://github.com/libp2p/go-msgio`.

from that repo: "a simple package to r/w length-delimited slices."

NOTE: currently missing the capability to indicate lengths by "varint" method.
"""

from typing import Optional

from libp2p.io.abc import MsgReadWriteCloser, Reader, ReadWriteCloser
from libp2p.io.utils import read_exactly

BYTE_ORDER = "big"


async def read_length(reader: Reader, size_len_bytes: int) -> int:
    length_bytes = await read_exactly(reader, size_len_bytes)
    return int.from_bytes(length_bytes, byteorder=BYTE_ORDER)


def encode_msg_with_length(msg_bytes: bytes, size_len_bytes: int) -> bytes:
    try:
        len_prefix = len(msg_bytes).to_bytes(size_len_bytes, byteorder=BYTE_ORDER)
    except OverflowError:
        raise ValueError(
            "msg_bytes is too large for `size_len_bytes` bytes length: "
            f"msg_bytes={msg_bytes!r}, size_len_bytes={size_len_bytes}"
        )
    return len_prefix + msg_bytes


class BaseMsgReadWriter(MsgReadWriteCloser):
    next_length: Optional[int]
    read_write_closer: ReadWriteCloser
    size_len_bytes: int

    def __init__(self, read_write_closer: ReadWriteCloser) -> None:
        self.read_write_closer = read_write_closer
        self.next_length = None

    async def read_msg(self) -> bytes:
        length = await self.next_msg_len()

        data = await read_exactly(self.read_write_closer, length)
        if len(data) < length:
            self.next_length = length - len(data)
        else:
            self.next_length = None
        return data

    async def next_msg_len(self) -> int:
        if self.next_length is None:
            self.next_length = await read_length(
                self.read_write_closer, self.size_len_bytes
            )
        return self.next_length

    async def close(self) -> None:
        await self.read_write_closer.close()

    async def write_msg(self, msg: bytes) -> None:
        data = encode_msg_with_length(msg, self.size_len_bytes)
        await self.read_write_closer.write(data)
