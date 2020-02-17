from libp2p.io.abc import MsgReadWriteCloser, ReadWriteCloser
from libp2p.utils import encode_fixedint_prefixed, read_fixedint_prefixed


class PlaintextHandshakeReadWriter(MsgReadWriteCloser):
    conn: ReadWriteCloser

    def __init__(self, conn: ReadWriteCloser) -> None:
        self.conn = conn

    async def read_msg(self) -> bytes:
        return await read_fixedint_prefixed(self.conn)

    async def write_msg(self, msg: bytes) -> None:
        encoded_msg_bytes = encode_fixedint_prefixed(msg)
        await self.conn.write(encoded_msg_bytes)

    async def close(self) -> None:
        await self.conn.close()
