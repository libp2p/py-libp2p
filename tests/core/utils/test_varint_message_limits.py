import pytest

from libp2p.exceptions import ParseError
from libp2p.io.abc import Reader
from libp2p.io.exceptions import IncompleteReadError, MessageTooLarge
from libp2p.utils.varint import (
    encode_uvarint,
    encode_varint_prefixed,
    read_varint_prefixed_bytes_limited,
)


class MockReader(Reader):
    """Mock reader for testing bounded varint reads."""

    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    async def read(self, n: int | None = None) -> bytes:
        if self.position >= len(self.data):
            return b""
        if n is None:
            n = len(self.data) - self.position
        result = self.data[self.position : self.position + n]
        self.position += len(result)
        return result


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_success():
    payload = b"hello-world"
    reader = MockReader(encode_varint_prefixed(payload))

    result = await read_varint_prefixed_bytes_limited(reader, max_length=64)
    assert result == payload


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_rejects_oversize():
    # Claim 10_000 bytes with a tiny limit; must raise before reading the body.
    claimed_length = 10_000
    reader = MockReader(encode_uvarint(claimed_length) + b"x" * 64)

    with pytest.raises(MessageTooLarge, match="exceeds maximum allowed 64"):
        await read_varint_prefixed_bytes_limited(reader, max_length=64)

    # Only the varint prefix should have been consumed (not the claimed body).
    assert reader.position == len(encode_uvarint(claimed_length))


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_rejects_non_positive_max():
    reader = MockReader(encode_varint_prefixed(b"x"))
    with pytest.raises(ValueError, match="max_length"):
        await read_varint_prefixed_bytes_limited(reader, max_length=0)


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_incomplete_prefix():
    reader = MockReader(b"\x80")  # incomplete multi-byte varint
    with pytest.raises(IncompleteReadError):
        await read_varint_prefixed_bytes_limited(reader, max_length=64)


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_incomplete_body():
    reader = MockReader(encode_uvarint(5) + b"ab")  # claims 5, only 2 bytes follow
    with pytest.raises(IncompleteReadError):
        await read_varint_prefixed_bytes_limited(reader, max_length=64)


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_limited_oversized_varint_encoding():
    # 11 continuation bytes — exceeds 64-bit uvarint width
    reader = MockReader(b"\x80" * 11)
    with pytest.raises(ParseError, match="64 bits"):
        await read_varint_prefixed_bytes_limited(reader, max_length=64)
