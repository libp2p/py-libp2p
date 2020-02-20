from typing import cast

from noise.connection import NoiseConnection as NoiseState

from libp2p.io.abc import EncryptedMsgReadWriter, MsgReadWriteCloser, ReadWriteCloser
from libp2p.io.msgio import FixedSizeLenMsgReadWriter, encode_msg_with_length
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


class NoisePacketReadWriter(FixedSizeLenMsgReadWriter):
    size_len_bytes = SIZE_NOISE_MESSAGE_LEN


def encode_msg_body(msg_body: bytes) -> bytes:
    encoded_msg_body = encode_msg_with_length(msg_body, SIZE_NOISE_MESSAGE_BODY_LEN)
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


class BaseNoiseMsgReadWriter(EncryptedMsgReadWriter):
    """
    The base implementation of noise message reader/writer.

    `encrypt` and `decrypt` are not implemented here, which should be
    implemented by the subclasses.
    """

    read_writer: MsgReadWriteCloser
    noise_state: NoiseState

    def __init__(self, conn: IRawConnection, noise_state: NoiseState) -> None:
        self.read_writer = NoisePacketReadWriter(cast(ReadWriteCloser, conn))
        self.noise_state = noise_state

    async def write_msg(self, data: bytes) -> None:
        noise_msg = encode_msg_body(data)
        data_encrypted = self.encrypt(noise_msg)
        await self.read_writer.write_msg(data_encrypted)

    async def read_msg(self) -> bytes:
        noise_msg_encrypted = await self.read_writer.read_msg()
        noise_msg = self.decrypt(noise_msg_encrypted)
        return decode_msg_body(noise_msg)

    async def close(self) -> None:
        await self.read_writer.close()


class NoiseHandshakeReadWriter(BaseNoiseMsgReadWriter):
    def encrypt(self, data: bytes) -> bytes:
        return self.noise_state.write_message(data)

    def decrypt(self, data: bytes) -> bytes:
        return self.noise_state.read_message(data)


class NoiseTransportReadWriter(BaseNoiseMsgReadWriter):
    def encrypt(self, data: bytes) -> bytes:
        return self.noise_state.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self.noise_state.decrypt(data)
