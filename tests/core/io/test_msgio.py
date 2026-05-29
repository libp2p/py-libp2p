import pytest

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import MessageTooLarge
from libp2p.io.msgio import VarIntLengthMsgReadWriter
from libp2p.utils import encode_varint_prefixed


class MemoryReadWriteCloser(ReadWriteCloser):
    def __init__(self, initial_bytes: bytes = b"") -> None:
        self._buffer = bytearray(initial_bytes)
        self.written = bytearray()
        self.closed = False

    async def read(self, n: int | None = None) -> bytes:
        if n is None:
            n = len(self._buffer)
        chunk = bytes(self._buffer[:n])
        del self._buffer[:n]
        return chunk

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def close(self) -> None:
        self.closed = True

    def get_remote_address(self) -> tuple[str, int] | None:
        return None


@pytest.mark.trio
async def test_varint_msgio_round_trip() -> None:
    rw = MemoryReadWriteCloser(encode_varint_prefixed(b"hello"))
    msgio = VarIntLengthMsgReadWriter(rw, max_msg_size=16)

    assert await msgio.read_msg() == b"hello"


@pytest.mark.trio
async def test_varint_msgio_write_prefixes_and_limits() -> None:
    rw = MemoryReadWriteCloser()
    msgio = VarIntLengthMsgReadWriter(rw, max_msg_size=8)

    await msgio.write_msg(b"hello")

    assert bytes(rw.written) == encode_varint_prefixed(b"hello")


@pytest.mark.trio
async def test_varint_msgio_rejects_oversized_reads() -> None:
    rw = MemoryReadWriteCloser(encode_varint_prefixed(b"toolong"))
    msgio = VarIntLengthMsgReadWriter(rw, max_msg_size=4)

    with pytest.raises(MessageTooLarge):
        await msgio.read_msg()


@pytest.mark.trio
async def test_varint_msgio_rejects_oversized_writes() -> None:
    rw = MemoryReadWriteCloser()
    msgio = VarIntLengthMsgReadWriter(rw, max_msg_size=4)

    with pytest.raises(MessageTooLarge):
        await msgio.write_msg(b"toolong")


def test_varint_msgio_requires_positive_limit() -> None:
    rw = MemoryReadWriteCloser()

    with pytest.raises(ValueError, match="max_msg_size"):
        VarIntLengthMsgReadWriter(rw, max_msg_size=0)
