from noise.connection import NoiseConnection as NoiseState

from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.noise.io import MsgReadWriter, NoiseTransportReadWriter


class NoiseConnection(BaseSession):
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
    ) -> None:
        super().__init__(local_peer, local_private_key, is_initiator, remote_peer)
        self.conn = conn
        self.noise_state = noise_state

    def get_msg_read_writer(self) -> MsgReadWriter:
        return NoiseTransportReadWriter(self.conn, self.noise_state)

    async def read(self, n: int = None) -> bytes:
        # TODO: Use a buffer to handle buffered messages.
        return await self.get_msg_read_writer().read_msg()

    async def write(self, data: bytes) -> None:
        await self.get_msg_read_writer().write_msg(data)

    async def close(self) -> None:
        await self.conn.close()
