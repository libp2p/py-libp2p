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

    local_peer: ID
    local_private_key: PrivateKey
    conn: MsgIOReadWriter
    remote_peer_id: ID
    remote_permanent_pubkey: PublicKey

    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        conn: MsgIOReadWriter,
        peer_id: Optional[ID] = None,
    ) -> None:
        self.local_peer = local_peer
        self.local_private_key = local_private_key
        self.remote_peer_id = peer_id
        self.remote_permanent_pubkey = None

        self.conn = conn
        self.initiator = peer_id is not None

    async def write(self, data: bytes) -> int:
        await self.conn.write(data)
        return len(data)

    async def read(self, n: int = -1) -> bytes:
        return await self.conn.read(n)

    async def close(self) -> None:
        await self.conn.close()

    def get_local_peer(self) -> ID:
        return self.local_peer

    def get_local_private_key(self) -> PrivateKey:
        return self.local_private_key

    def get_remote_peer(self) -> ID:
        return self.remote_peer_id

    def get_remote_public_key(self) -> Optional[PublicKey]:
        return self.remote_permanent_pubkey
