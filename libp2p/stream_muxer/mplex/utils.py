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
