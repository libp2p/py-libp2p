from libp2p.network.connection.raw_connection_interface import IRawConnection

from .exceptions import MissingLengthException, MissingMessageException

SIZE_LEN_BYTES = 4

# TODO unify w/ https://github.com/libp2p/py-libp2p/blob/1aed52856f56a4b791696bbcbac31b5f9c2e88c9/libp2p/utils.py#L85-L99  # noqa: E501


def encode(msg_bytes: bytes) -> bytes:
    len_prefix = len(msg_bytes).to_bytes(SIZE_LEN_BYTES, "big")
    return len_prefix + msg_bytes


async def read_next_message(reader: IRawConnection) -> bytes:
    len_bytes = await reader.read(SIZE_LEN_BYTES)
    if len(len_bytes) != SIZE_LEN_BYTES:
        raise MissingLengthException()
    len_int = int.from_bytes(len_bytes, "big")
    next_msg = await reader.read(len_int)
    if len(next_msg) != len_int:
        # TODO makes sense to keep reading until this condition is true?
        raise MissingMessageException()
    return next_msg
