import io
from typing import Optional

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.io.msgio import MsgIOReadWriter
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn


class BaseSession(ISecureConn):
    """
    ``BaseSession`` is not fully instantiated from its abstract classes as it
    is only meant to be used in clases that derive from it.
    """

    buf: io.BytesIO
    low_watermark: int
    high_watermark: int

    local_peer: ID
    local_private_key: PrivateKey
    remote_peer_id: ID
    remote_permanent_pubkey: PublicKey

    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        conn: MsgIOReadWriter,
        initiator: bool,
        peer_id: Optional[ID] = None,
    ) -> None:
        self.local_peer = local_peer
        self.local_private_key = local_private_key
        self.remote_peer_id = peer_id
        self.remote_permanent_pubkey = None
        self.conn = conn
        self.initiator = initiator

        self._reset_internal_buffer()

    def get_local_peer(self) -> ID:
        return self.local_peer

    def get_local_private_key(self) -> PrivateKey:
        return self.local_private_key

    def get_remote_peer(self) -> ID:
        return self.remote_peer_id

    def get_remote_public_key(self) -> Optional[PublicKey]:
        return self.remote_permanent_pubkey

    async def next_msg_len(self) -> int:
        return await self.conn.next_msg_len()

    def _reset_internal_buffer(self) -> None:
        self.buf = io.BytesIO()
        self.low_watermark = 0
        self.high_watermark = 0

    def _drain(self, n: int) -> bytes:
        if self.low_watermark == self.high_watermark:
            return bytes()

        data = self.buf.getbuffer()[self.low_watermark : self.high_watermark]

        if n < 0:
            n = len(data)
        result = data[:n].tobytes()
        self.low_watermark += len(result)

        if self.low_watermark == self.high_watermark:
            del data  # free the memoryview so we can free the underlying BytesIO
            self.buf.close()
            self._reset_internal_buffer()
        return result

    async def _fill(self) -> None:
        msg = await self.read_msg()
        self.buf.write(msg)
        self.low_watermark = 0
        self.high_watermark = len(msg)

    async def read(self, n: int = -1) -> bytes:
        data_from_buffer = self._drain(n)
        if len(data_from_buffer) > 0:
            return data_from_buffer

        next_length = await self.next_msg_len()

        if n < next_length:
            await self._fill()
            return self._drain(n)
        else:
            return await self.read_msg()

    async def read_msg(self) -> bytes:
        return await self.conn.read_msg()

    async def write(self, data: bytes) -> int:
        await self.write_msg(data)
        return len(data)

    async def write_msg(self, msg: bytes) -> None:
        await self.conn.write_msg(msg)

    async def close(self) -> None:
        await self.conn.close()
