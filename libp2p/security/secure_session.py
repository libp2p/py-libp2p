import io

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.io.abc import (
    EncryptedMsgReadWriter,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.base_session import (
    BaseSession,
)


class SecureSession(BaseSession):
    buf: io.BytesIO
    low_watermark: int
    high_watermark: int

    def __init__(
        self,
        *,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        remote_permanent_pubkey: PublicKey,
        is_initiator: bool,
        conn: EncryptedMsgReadWriter,
    ) -> None:
        super().__init__(
            local_peer=local_peer,
            local_private_key=local_private_key,
            remote_peer=remote_peer,
            remote_permanent_pubkey=remote_permanent_pubkey,
            is_initiator=is_initiator,
        )
        self.conn = conn

        self._reset_internal_buffer()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying connection's get_remote_address method."""
        return self.conn.get_remote_address()

    def _reset_internal_buffer(self) -> None:
        self.buf = io.BytesIO()
        self.low_watermark = 0
        self.high_watermark = 0

    def _drain(self, n: int | None) -> bytes:
        if self.low_watermark == self.high_watermark:
            return b""

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

    def _fill(self, msg: bytes) -> None:
        self.buf.write(msg)
        self.low_watermark = 0
        self.high_watermark = len(msg)

    async def read(self, n: int | None = None) -> bytes:
        if n == 0:
            return b""

        data_from_buffer = self._drain(n)
        if len(data_from_buffer) > 0:
            return data_from_buffer

        msg = await self.conn.read_msg()

        if n is None:
            return msg

        if n < len(msg):
            self._fill(msg)
            return self._drain(n)
        else:
            return msg

    async def write(self, data: bytes) -> None:
        await self.conn.write_msg(data)

    async def close(self) -> None:
        await self.conn.close()
