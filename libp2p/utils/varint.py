import itertools
import logging
import math
from typing import BinaryIO

from libp2p.abc import INetStream
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


def encode_uvarint(value: int) -> bytes:
    """Encode an unsigned integer as a varint."""
    if value < 0:
        raise ValueError("Cannot encode negative value as uvarint")

    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_uvarint(data: bytes) -> int:
    """Decode a varint from bytes."""
    if not data:
        raise ParseError("Unexpected end of data")

    result = 0
    shift = 0

    for byte in data:
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
        if shift >= 64:
            raise ValueError("Varint too long")

    return result


def decode_varint_from_bytes(data: bytes) -> int:
    """Decode a varint from bytes (alias for decode_uvarint for backward comp)."""
    return decode_uvarint(data)


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
    Decode a varint from bytes and return both the value and the number of bytes
    consumed.

    Returns:
        Tuple[int, int]: (value, bytes_consumed)

    """
    result = 0
    shift = 0
    bytes_consumed = 0

    for byte in data:
        result |= (byte & 0x7F) << shift
        bytes_consumed += 1
        if (byte & 0x80) == 0:
            break
        shift += 7
        if shift >= 64:
            raise ValueError("Varint too long")

    return result, bytes_consumed


def encode_varint_prefixed(data: bytes) -> bytes:
    """Encode data with a varint length prefix."""
    length_bytes = encode_uvarint(len(data))
    return length_bytes + data


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


def read_varint_prefixed_bytes_sync(
    stream: BinaryIO, max_length: int = 1024 * 1024
) -> bytes:
    """
    Read varint-prefixed bytes from a stream.

    Args:
        stream: A stream-like object with a read() method
        max_length: Maximum allowed data length to prevent memory exhaustion

    Returns:
        bytes: The data without the length prefix

    Raises:
        ValueError: If the length prefix is invalid or too large
        EOFError: If the stream ends unexpectedly

    """
    # Read the varint length prefix
    length_bytes = b""
    while True:
        byte_data = stream.read(1)
        if not byte_data:
            raise EOFError("Stream ended while reading varint length prefix")

        length_bytes += byte_data
        if byte_data[0] & 0x80 == 0:
            break

    # Decode the length
    length = decode_uvarint(length_bytes)

    if length > max_length:
        raise ValueError(f"Data length {length} exceeds maximum allowed {max_length}")

    # Read the data
    data = stream.read(length)
    if len(data) != length:
        raise EOFError(f"Expected {length} bytes, got {len(data)}")

    return data


async def read_length_prefixed_protobuf(
    stream: INetStream, use_varint_format: bool = True, max_length: int = 1024 * 1024
) -> bytes:
    """Read a protobuf message from a stream, handling both formats."""
    if use_varint_format:
        # Read length-prefixed protobuf message from the stream
        # First read the varint length prefix
        length_bytes = b""
        while True:
            b = await stream.read(1)
            if not b:
                raise Exception("No length prefix received")

            length_bytes += b
            if b[0] & 0x80 == 0:
                break

        msg_length = decode_varint_from_bytes(length_bytes)

        if msg_length > max_length:
            raise Exception(
                f"Message length {msg_length} exceeds maximum allowed {max_length}"
            )

        # Read the protobuf message
        data = await stream.read(msg_length)
        if len(data) != msg_length:
            raise Exception(
                f"Incomplete message: expected {msg_length}, got {len(data)}"
            )

        return data
    else:
        # Read raw protobuf message from the stream
        # For raw format, read all available data in one go
        data = await stream.read()

        # If we got no data, raise an exception
        if not data:
            raise Exception("No data received in raw format")

        if len(data) > max_length:
            raise Exception(
                f"Message length {len(data)} exceeds maximum allowed {max_length}"
            )

        return data
