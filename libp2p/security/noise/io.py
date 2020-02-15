from abc import ABC, abstractmethod
from typing import cast

from noise.connection import NoiseConnection as NoiseState

from libp2p.io.abc import ReadWriter
from libp2p.io.utils import read_exactly
from libp2p.network.connection.raw_connection_interface import IRawConnection

SIZE_NOISE_MESSAGE_LEN = 2
MAX_NOISE_MESSAGE_LEN = 2 ** (8 * SIZE_NOISE_MESSAGE_LEN) - 1
SIZE_NOISE_MESSAGE_BODY_LEN = 2
MAX_NOISE_MESSAGE_BODY_LEN = MAX_NOISE_MESSAGE_LEN - SIZE_NOISE_MESSAGE_BODY_LEN
BYTE_ORDER = "big"

# |                         Noise packet                            |
#   <   2 bytes   -><-                   65535                   ->
#  | noise msg len |                   noise msg                   |
#                  | body len |          body          | padding |
#                   <-2 bytes-><-       max=65533 bytes        ->


def encode_data(data: bytes, size_len: int) -> bytes:
    len_data = len(data)
    try:
        len_bytes = len_data.to_bytes(size_len, BYTE_ORDER)
    except OverflowError as e:
        raise ValueError from e
    return len_bytes + data


class MsgReader(ABC):
    @abstractmethod
    async def read_msg(self) -> bytes:
        ...


class MsgWriter(ABC):
    @abstractmethod
    async def write_msg(self, msg: bytes) -> None:
        ...


class MsgReadWriter(MsgReader, MsgWriter):
    pass


# TODO: Add comments
class NoisePacketReadWriter(MsgReadWriter):
    """Encode and decode the low level noise messages."""

    read_writer: ReadWriter

    def __init__(self, read_writer: ReadWriter) -> None:
        self.read_writer = read_writer

    async def read_msg(self) -> bytes:
        len_bytes = await read_exactly(self.read_writer, SIZE_NOISE_MESSAGE_LEN)
        len_int = int.from_bytes(len_bytes, BYTE_ORDER)
        return await read_exactly(self.read_writer, len_int)

    async def write_msg(self, msg: bytes) -> None:
        encoded_data = encode_data(msg, SIZE_NOISE_MESSAGE_LEN)
        await self.read_writer.write(encoded_data)


# TODO: Add comments
def encode_msg_body(msg_body: bytes) -> bytes:
    encoded_msg_body = encode_data(msg_body, SIZE_NOISE_MESSAGE_BODY_LEN)
    if len(encoded_msg_body) > MAX_NOISE_MESSAGE_BODY_LEN:
        raise ValueError(
            f"msg_body is too long: {len(msg_body)}, "
            f"maximum={MAX_NOISE_MESSAGE_BODY_LEN}"
        )
    # NOTE: Improvements:
    #   1. Senders *SHOULD* use a source of random data to populate the padding field.
    #   2. and *may* use any length of padding that does not cause the total length of
    #      the Noise message to exceed 65535 bytes.
    #   Ref: https://github.com/libp2p/specs/tree/master/noise#encrypted-payloads
    return encoded_msg_body  # + padding


def decode_msg_body(noise_msg: bytes) -> bytes:
    len_body = int.from_bytes(noise_msg[:SIZE_NOISE_MESSAGE_BODY_LEN], BYTE_ORDER)
    # Just ignore the padding
    return noise_msg[
        SIZE_NOISE_MESSAGE_BODY_LEN : (SIZE_NOISE_MESSAGE_BODY_LEN + len_body)
    ]


# TODO: Add comments
class NoiseHandshakeReadWriter(MsgReadWriter):
    read_writer: MsgReadWriter
    noise_state: NoiseState

    def __init__(self, conn: IRawConnection, noise_state: NoiseState) -> None:
        self.read_writer = NoisePacketReadWriter(cast(ReadWriter, conn))
        self.noise_state = noise_state

    async def write_msg(self, data: bytes) -> None:
        noise_msg = encode_msg_body(data)
        data_encrypted = self.noise_state.write_message(noise_msg)
        await self.read_writer.write_msg(data_encrypted)

    async def read_msg(self) -> bytes:
        noise_msg_encrypted = await self.read_writer.read_msg()
        noise_msg = self.noise_state.read_message(noise_msg_encrypted)
        return decode_msg_body(noise_msg)
