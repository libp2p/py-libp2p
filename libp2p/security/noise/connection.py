import io

from noise.connection import NoiseConnection as NoiseState

from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.noise.io import MsgReadWriter, NoiseTransportReadWriter


class NoiseConnection(BaseSession):
    buf: io.BytesIO
    low_watermark: int
    high_watermark: int

    read_writer: IRawConnection
    noise_state: NoiseState

    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        conn: IRawConnection,
        is_initiator: bool,
        noise_state: NoiseState,
        # remote_permanent_pubkey
    ) -> None:
        super().__init__(local_peer, local_private_key, is_initiator, remote_peer)
        self.conn = conn
        self.noise_state = noise_state
        self._reset_internal_buffer()

    def get_msg_read_writer(self) -> MsgReadWriter:
        return NoiseTransportReadWriter(self.conn, self.noise_state)

    async def close(self) -> None:
        await self.conn.close()

    def _reset_internal_buffer(self) -> None:
        self.buf = io.BytesIO()
        self.low_watermark = 0
        self.high_watermark = 0

    def _drain(self, n: int) -> bytes:
        if self.low_watermark == self.high_watermark:
            return bytes()

        data = self.buf.getbuffer()[self.low_watermark : self.high_watermark]

        if n is None:
            n = len(data)
        result = data[:n].tobytes()
        self.low_watermark += len(result)

        if self.low_watermark == self.high_watermark:
            del data  # free the memoryview so we can free the underlying BytesIO
            self.buf.close()
            self._reset_internal_buffer()
        return result

    async def read(self, n: int = None) -> bytes:
        if n == 0:
            return bytes()

        data_from_buffer = self._drain(n)
        if len(data_from_buffer) > 0:
            return data_from_buffer

        msg = await self.read_msg()

        if n < len(msg):
            self.buf.write(msg)
            self.low_watermark = 0
            self.high_watermark = len(msg)
            return self._drain(n)
        else:
            return msg

    async def read_msg(self) -> bytes:
        return await self.get_msg_read_writer().read_msg()

    async def write(self, data: bytes) -> None:
        await self.write_msg(data)

    async def write_msg(self, msg: bytes) -> None:
        await self.get_msg_read_writer().write_msg(msg)
