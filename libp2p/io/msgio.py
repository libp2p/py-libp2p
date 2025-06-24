"""
``msgio`` is an implementation of `https://github.com/libp2p/go-msgio`.

from that repo: "a simple package to r/w length-delimited slices."

NOTE: currently missing the capability to indicate lengths by "varint" method.
"""

from abc import (
    abstractmethod,
)
from typing import (
    Literal,
)

from libp2p.io.abc import (
    MsgReadWriteCloser,
    Reader,
    ReadWriteCloser,
)
from libp2p.io.utils import (
    read_exactly,
)
from libp2p.utils import (
    decode_uvarint_from_stream,
    encode_varint_prefixed,
)

from .exceptions import (
    MessageTooLarge,
)

BYTE_ORDER: Literal["big", "little"] = "big"


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
    read_write_closer: ReadWriteCloser
    size_len_bytes: int

    def __init__(self, read_write_closer: ReadWriteCloser) -> None:
        self.read_write_closer = read_write_closer

    async def read_msg(self) -> bytes:
        length = await self.next_msg_len()
        return await read_exactly(self.read_write_closer, length)

    @abstractmethod
    async def next_msg_len(self) -> int: ...

    @abstractmethod
    def encode_msg(self, msg: bytes) -> bytes: ...

    async def close(self) -> None:
        await self.read_write_closer.close()

    async def write_msg(self, msg: bytes) -> None:
        encoded_msg = self.encode_msg(msg)
        await self.read_write_closer.write(encoded_msg)


class FixedSizeLenMsgReadWriter(BaseMsgReadWriter):
    size_len_bytes: int

    async def next_msg_len(self) -> int:
        return await read_length(self.read_write_closer, self.size_len_bytes)

    def encode_msg(self, msg: bytes) -> bytes:
        return encode_msg_with_length(msg, self.size_len_bytes)


class VarIntLengthMsgReadWriter(BaseMsgReadWriter):
    max_msg_size: int

    async def next_msg_len(self) -> int:
        msg_len = await decode_uvarint_from_stream(self.read_write_closer)
        if msg_len > self.max_msg_size:
            raise MessageTooLarge(
                f"msg_len={msg_len} > max_msg_size={self.max_msg_size}"
            )
        return msg_len

    def encode_msg(self, msg: bytes) -> bytes:
        msg_len = len(msg)
        if msg_len > self.max_msg_size:
            raise MessageTooLarge(
                f"msg_len={msg_len} > max_msg_size={self.max_msg_size}"
            )
        return encode_varint_prefixed(msg)
