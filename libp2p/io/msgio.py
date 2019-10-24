"""
``msgio`` is an implementation of `https://github.com/libp2p/go-msgio`.

from that repo: "a simple package to r/w length-delimited slices."

NOTE: currently missing the capability to indicate lengths by "varint" method.
"""
# TODO unify w/ https://github.com/libp2p/py-libp2p/blob/1aed52856f56a4b791696bbcbac31b5f9c2e88c9/libp2p/utils.py#L85-L99  # noqa: E501
from typing import Optional, cast

from libp2p.io.abc import Closer, ReadCloser, Reader, ReadWriteCloser, WriteCloser
from libp2p.io.utils import read_exactly

SIZE_LEN_BYTES = 4
BYTE_ORDER = "big"


async def read_length(reader: Reader) -> int:
    length_bytes = await read_exactly(reader, SIZE_LEN_BYTES)
    return int.from_bytes(length_bytes, byteorder=BYTE_ORDER)


def encode_msg_with_length(msg_bytes: bytes) -> bytes:
    len_prefix = len(msg_bytes).to_bytes(SIZE_LEN_BYTES, "big")
    return len_prefix + msg_bytes


class MsgIOWriter(WriteCloser):
    write_closer: WriteCloser

    def __init__(self, write_closer: WriteCloser) -> None:
        self.write_closer = write_closer

    async def write(self, data: bytes) -> int:
        await self.write_msg(data)
        return len(data)

    async def write_msg(self, msg: bytes) -> None:
        data = encode_msg_with_length(msg)
        await self.write_closer.write(data)

    async def close(self) -> None:
        await self.write_closer.close()


class MsgIOReader(ReadCloser):
    read_closer: ReadCloser
    next_length: Optional[int]

    def __init__(self, read_closer: ReadCloser) -> None:
        # NOTE: the following line is required to satisfy the
        # multiple inheritance but `mypy` does not like it...
        super().__init__(read_closer)  # type: ignore
        self.read_closer = read_closer
        self.next_length = None

    async def read(self, n: int = -1) -> bytes:
        return await self.read_msg()

    async def read_msg(self) -> bytes:
        length = await self.next_msg_len()

        data = await read_exactly(self.read_closer, length)
        if len(data) < length:
            self.next_length = length - len(data)
        else:
            self.next_length = None
        return data

    async def next_msg_len(self) -> int:
        if self.next_length is None:
            self.next_length = await read_length(self.read_closer)
        return self.next_length

    async def close(self) -> None:
        await self.read_closer.close()


class MsgIOReadWriter(MsgIOReader, MsgIOWriter, Closer):
    def __init__(self, read_write_closer: ReadWriteCloser) -> None:
        super().__init__(cast(ReadCloser, read_write_closer))

    async def close(self) -> None:
        await self.read_closer.close()
