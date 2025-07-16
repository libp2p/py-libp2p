import itertools
import logging
import math

from libp2p.exceptions import (
    ParseError,
)
from libp2p.io.abc import (
    Reader,
)
from libp2p.io.utils import (
    read_exactly,
)

logger = logging.getLogger("libp2p.utils.varint")

# Unsigned LEB128(varint codec)
# Reference: https://github.com/ethereum/py-wasm/blob/master/wasm/parsers/leb128.py

LOW_MASK = 2**7 - 1
HIGH_MASK = 2**7

# The maximum shift width for a 64 bit integer.  We shouldn't have to decode
# integers larger than this.
SHIFT_64_BIT_MAX = int(math.ceil(64 / 7)) * 7


def encode_uvarint(number: int) -> bytes:
    """Pack `number` into varint bytes."""
    buf = b""
    while True:
        towrite = number & 0x7F
        number >>= 7
        if number:
            buf += bytes((towrite | 0x80,))
        else:
            buf += bytes((towrite,))
            break
    return buf


def decode_varint_from_bytes(data: bytes) -> int:
    """
    Decode a varint from bytes and return the value.

    This is a synchronous version of decode_uvarint_from_stream for already-read bytes.
    """
    res = 0
    for shift in itertools.count(0, 7):
        if shift > SHIFT_64_BIT_MAX:
            raise ParseError("Integer is too large...")

        if not data:
            raise ParseError("Unexpected end of data")

        value = data[0]
        data = data[1:]

        res += (value & LOW_MASK) << shift

        if not value & HIGH_MASK:
            break
    return res


async def decode_uvarint_from_stream(reader: Reader) -> int:
    """https://en.wikipedia.org/wiki/LEB128."""
    res = 0
    for shift in itertools.count(0, 7):
        if shift > SHIFT_64_BIT_MAX:
            raise ParseError(
                "Varint decoding error: integer exceeds maximum size of 64 bits."
            )

        byte = await read_exactly(reader, 1)
        value = byte[0]

        res += (value & LOW_MASK) << shift

        if not value & HIGH_MASK:
            break
    return res


def decode_varint_with_size(data: bytes) -> tuple[int, int]:
    """
    Decode a varint from bytes and return (value, bytes_consumed).
    Returns (0, 0) if the data doesn't start with a valid varint.
    """
    try:
        # Calculate how many bytes the varint consumes
        varint_size = 0
        for i, byte in enumerate(data):
            varint_size += 1
            if (byte & 0x80) == 0:
                break

        if varint_size == 0:
            return 0, 0

        # Extract just the varint bytes
        varint_bytes = data[:varint_size]

        # Decode the varint
        value = decode_varint_from_bytes(varint_bytes)

        return value, varint_size
    except Exception:
        return 0, 0


def encode_varint_prefixed(msg_bytes: bytes) -> bytes:
    varint_len = encode_uvarint(len(msg_bytes))
    return varint_len + msg_bytes


async def read_varint_prefixed_bytes(reader: Reader) -> bytes:
    len_msg = await decode_uvarint_from_stream(reader)
    data = await read_exactly(reader, len_msg)
    return data


# Delimited read/write, used by multistream-select.
# Reference: https://github.com/gogo/protobuf/blob/07eab6a8298cf32fac45cceaac59424f98421bbc/io/varint.go#L109-L126  # noqa: E501


def encode_delim(msg: bytes) -> bytes:
    delimited_msg = msg + b"\n"
    return encode_varint_prefixed(delimited_msg)


async def read_delim(reader: Reader) -> bytes:
    msg_bytes = await read_varint_prefixed_bytes(reader)
    if len(msg_bytes) == 0:
        raise ParseError("`len(msg_bytes)` should not be 0")
    if msg_bytes[-1:] != b"\n":
        raise ParseError(
            f'`msg_bytes` is not delimited by b"\\n": `msg_bytes`={msg_bytes!r}'
        )
    return msg_bytes[:-1]
