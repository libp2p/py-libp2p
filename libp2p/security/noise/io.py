import logging
from typing import (
    cast,
)

from noise.connection import NoiseConnection as NoiseState

from libp2p.abc import (
    IRawConnection,
)
from libp2p.io.abc import (
    EncryptedMsgReadWriter,
    ReadWriteCloser,
)
from libp2p.io.msgio import (
    FixedSizeLenMsgReadWriter,
)

logger = logging.getLogger(__name__)

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

    read_writer: NoisePacketReadWriter
    noise_state: NoiseState

    # NOTE: This prefix is added in msg#3 in Go.
    #       Support in py-libp2p is available but not used
    prefix: bytes = b"\x00" * 32

    def __init__(self, conn: IRawConnection, noise_state: NoiseState) -> None:
        self.read_writer = NoisePacketReadWriter(cast(ReadWriteCloser, conn))
        self.noise_state = noise_state

    async def write_msg(self, msg: bytes, prefix_encoded: bool = False) -> None:
        logger.debug(f"Noise write_msg: encrypting {len(msg)} bytes")
        data_encrypted = self.encrypt(msg)
        if prefix_encoded:
            # Manually add the prefix if needed
            data_encrypted = self.prefix + data_encrypted
        logger.debug(f"Noise write_msg: writing {len(data_encrypted)} encrypted bytes")
        await self.read_writer.write_msg(data_encrypted)
        logger.debug("Noise write_msg: write completed successfully")

    async def read_msg(self, prefix_encoded: bool = False) -> bytes:
        logger.debug("Noise read_msg: reading encrypted message")
        noise_msg_encrypted = await self.read_writer.read_msg()
        logger.debug(f"Noise read_msg: read {len(noise_msg_encrypted)} encrypted bytes")
        if prefix_encoded:
            result = self.decrypt(noise_msg_encrypted[len(self.prefix) :])
        else:
            result = self.decrypt(noise_msg_encrypted)
        logger.debug(f"Noise read_msg: decrypted to {len(result)} bytes")
        return result

    async def close(self) -> None:
        await self.read_writer.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        # Delegate to the underlying connection if possible
        if hasattr(self.read_writer, "read_write_closer") and hasattr(
            self.read_writer.read_write_closer,
            "get_remote_address",
        ):
            return self.read_writer.read_write_closer.get_remote_address()
        return None


class NoiseHandshakeReadWriter(BaseNoiseMsgReadWriter):
    def encrypt(self, data: bytes) -> bytes:
        return bytes(self.noise_state.write_message(data))

    def decrypt(self, data: bytes) -> bytes:
        return bytes(self.noise_state.read_message(data))


class NoiseTransportReadWriter(BaseNoiseMsgReadWriter):
    def encrypt(self, data: bytes) -> bytes:
        return self.noise_state.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self.noise_state.decrypt(data)
