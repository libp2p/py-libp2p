import asyncio
import struct
from .constants import HEADER_TAGS


def encode_uvarint(number):
    """Pack `number` into varint bytes"""
    buf = b''
    while True:
        towrite = number & 0x7f
        number >>= 7
        if number:
            buf += bytes((towrite | 0x80, ))
        else:
            buf += bytes((towrite, ))
            break
    return buf


def decode_uvarint(buff, index):
    shift = 0
    result = 0
    while True:
        i = buff[index]
        result |= (i & 0x7f) << shift
        shift += 7
        if not i & 0x80:
            break
        index += 1

    return result, index + 1

async def decode_uvarint_from_stream(reader, timeout):
    shift = 0
    result = 0
    while True:
        byte = await asyncio.wait_for(reader.read(1), timeout=timeout)
        i = struct.unpack('>H', b'\x00' + byte)[0]
        result |= (i & 0x7f) << shift
        shift += 7
        if not i & 0x80:
            break

    return result

def get_flag(initiator, action):
    """
    get header flag based on action for mplex
    :param action: action type in str
    :return: int flag
    """
    if initiator or HEADER_TAGS[action] == 0:
        return HEADER_TAGS[action]

    return HEADER_TAGS[action] - 1
