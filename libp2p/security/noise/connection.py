from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession


class NoiseConnection(BaseSession):
    conn: IRawConnection

    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        conn: IRawConnection,
        is_initiator: bool,
    ) -> None:
        super().__init__(local_peer, local_private_key, is_initiator, remote_peer)
        self.conn = conn

    async def read(self, n: int = None) -> bytes:
        # TODO: Add decryption logic here
        return await self.conn.read(n)

    async def write(self, data: bytes) -> None:
        # TODO: Add encryption logic here
        await self.conn.write(data)

    async def close(self) -> None:
        await self.conn.close()
