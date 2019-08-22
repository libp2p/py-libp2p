import asyncio

SIZE_LEN_BYTES = 4

# TODO unify w/ https://github.com/libp2p/py-libp2p/blob/1aed52856f56a4b791696bbcbac31b5f9c2e88c9/libp2p/utils.py#L85-L99


def encode(msg_bytes: bytes) -> bytes:
    len_prefix = len(msg_bytes).to_bytes(SIZE_LEN_BYTES, "big")
    return len_prefix + msg_bytes


async def read_next_message(reader: asyncio.StreamReader) -> bytes:
    len_bytes = await reader.readexactly(SIZE_LEN_BYTES)
    len_int = int.from_bytes(len_bytes, "big")
    return await reader.readexactly(len_int)
