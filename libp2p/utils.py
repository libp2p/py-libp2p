import asyncio
import struct
from typing import Tuple

from libp2p.typing import StreamReader


def encode_uvarint(number: int) -> bytes:
    """Pack `number` into varint bytes"""
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


def decode_uvarint(buff: bytes, index: int) -> Tuple[int, int]:
    shift = 0
    result = 0
    while True:
        i = buff[index]
        result |= (i & 0x7F) << shift
        shift += 7
        if not i & 0x80:
            break
        index += 1

    return result, index + 1


async def decode_uvarint_from_stream(reader: StreamReader, timeout: float) -> int:
    shift = 0
    result = 0
    while True:
        byte = await asyncio.wait_for(reader.read(1), timeout=timeout)
        i = struct.unpack(">H", b"\x00" + byte)[0]
        result |= (i & 0x7F) << shift
        shift += 7
        if not i & 0x80:
            break

    return result


# Varint-prefixed read/write


def encode_varint_prefixed(msg_bytes: bytes) -> bytes:
    varint_len = encode_uvarint(len(msg_bytes))
    return varint_len + msg_bytes


async def read_varint_prefixed_bytes(reader: StreamReader) -> bytes:
    len_msg = await decode_uvarint_from_stream(reader, None)
    data = await reader.read(len_msg)
    if len(data) != len_msg:
        raise ValueError(
            f"failed to read enough bytes: len_msg={len_msg}, data={data!r}"
        )
    return data


# Delimited read/write, used by multistream-select.
# Reference: https://github.com/gogo/protobuf/blob/07eab6a8298cf32fac45cceaac59424f98421bbc/io/varint.go#L109-L126  # noqa: E501


def encode_delim(msg: bytes) -> bytes:
    delimited_msg = msg + b"\n"
    return encode_varint_prefixed(delimited_msg)


async def read_delim(reader: StreamReader) -> bytes:
    msg_bytes = await read_varint_prefixed_bytes(reader)
    # TODO: Investigate if it is possible to have empty `msg_bytes`
    if len(msg_bytes) != 0 and msg_bytes[-1:] != b"\n":
        raise ValueError(f'msg_bytes is not delimited by b"\\n": msg_bytes={msg_bytes}')
    return msg_bytes[:-1]


SIZE_LEN_BYTES = 4

# Fixed-prefixed read/write, used by "/plaintext/2.0.0".
# Reference: https://github.com/libp2p/go-msgio/blob/d5bbf59d3c4240266b1d2e5df9dc993454c42011/num.go#L11-L33  # noqa: E501  # noqa: E501


def encode_fixedint_prefixed(msg_bytes: bytes) -> bytes:
    len_prefix = len(msg_bytes).to_bytes(SIZE_LEN_BYTES, "big")
    return len_prefix + msg_bytes


async def read_fixedint_prefixed(reader: StreamReader) -> bytes:
    len_bytes = await reader.read(SIZE_LEN_BYTES)
    len_int = int.from_bytes(len_bytes, "big")
    return await reader.read(len_int)
