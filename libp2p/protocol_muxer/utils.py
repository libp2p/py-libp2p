from libp2p.stream_muxer.mplex.utils import (
    decode_uvarint_from_stream,
    encode_uvarint,
)


def encode_delim(msg: str) -> bytes:
    varint_len_msg = encode_uvarint(len(msg) + 1)
    return varint_len_msg + msg.encode() + b"\n"


async def delim_write(writer, msg: str) -> bytes:
    delim_msg = encode_delim(msg)
    writer.write(delim_msg)
    await writer.drain()


async def delim_read(reader):
    timeout = 10
    len_msg = await decode_uvarint_from_stream(reader, timeout)
    msg_bytes = await reader.read(len_msg)
    return msg_bytes.decode().rstrip()
