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


async def decode_uvarint_from_stream(reader: Reader) -> int:
    """https://en.wikipedia.org/wiki/LEB128."""
    res = 0
    for shift in itertools.count(0, 7):
        if shift > SHIFT_64_BIT_MAX:
            raise ParseError("TODO: better exception msg: Integer is too large...")

        byte = await read_exactly(reader, 1)
        value = byte[0]

        res += (value & LOW_MASK) << shift

        if not value & HIGH_MASK:
            break
    return res


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
