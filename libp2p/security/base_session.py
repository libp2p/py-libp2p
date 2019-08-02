from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn


class BaseSession(ISecureConn, IRawConnection):
    """
    ``BaseSession`` is not fully instantiated from its abstract classes as it
    is only meant to be used in clases that derive from it.
    """

    def __init__(
        self, transport: BaseSecureTransport, conn: IRawConnection, peer_id: ID
    ) -> None:
        self.local_peer = self.transport.local_peer
        self.local_private_key = self.transport.local_private_key
        self.insecure_conn = conn
        self.remote_peer_id = peer_id
        self.remote_permanent_pubkey = b""

    def get_local_peer(self) -> ID:
        return self.local_peer

    def get_local_private_key(self) -> bytes:
        return self.local_private_key

    def get_remote_peer(self) -> ID:
        return self.remote_peer_id

    def get_remote_public_key(self) -> bytes:
        return self.remote_permanent_pubkey
