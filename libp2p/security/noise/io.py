from typing import cast

from noise.connection import NoiseConnection as NoiseState

from libp2p.io.abc import EncryptedMsgReadWriter, MsgReadWriteCloser, ReadWriteCloser
from libp2p.io.msgio import FixedSizeLenMsgReadWriter
from libp2p.network.connection.raw_connection_interface import IRawConnection

SIZE_NOISE_MESSAGE_LEN = 2
MAX_NOISE_MESSAGE_LEN = 2 ** (8 * SIZE_NOISE_MESSAGE_LEN) - 1
SIZE_NOISE_MESSAGE_BODY_LEN = 2
MAX_NOISE_MESSAGE_BODY_LEN = MAX_NOISE_MESSAGE_LEN - SIZE_NOISE_MESSAGE_BODY_LEN
BYTE_ORDER = "big"

# |                         Noise packet                            |
#   <   2 bytes   -><-                   65535                   ->
#  | noise msg len |                   noise msg                   |


class NoisePacketReadWriter(FixedSizeLenMsgReadWriter):
    size_len_bytes = SIZE_NOISE_MESSAGE_LEN


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
        data_encrypted = self.encrypt(data)
        # FIXME: Decide whether this prefix should be added or not.
        # if not first:
        #     data_encrypted = b"\x00" * 32 + data_encrypted
        await self.read_writer.write_msg(data_encrypted)

    async def read_msg(self) -> bytes:
        noise_msg_encrypted = await self.read_writer.read_msg()
        # FIXME: Decide whether this prefix should be added or not.
        # if not first:
        #     noise_msg_encrypted = noise_msg_encrypted[32:]
        return self.decrypt(noise_msg_encrypted)

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
