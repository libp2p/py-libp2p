from libp2p.crypto.keys import KeyPair, PrivateKey
from libp2p.io.msgio import ReadWriteCloser
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.typing import TProtocol

PROTOCOL_ID = TProtocol("/")


class NoiseConnection(BaseSession):
    conn: ReadWriteCloser

    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        conn: ReadWriteCloser,
        is_initiator: bool,
    ) -> None:
        super().__init__(local_peer, local_private_key, is_initiator, remote_peer)
        self.conn = conn

    async def read(self, n: int = None) -> bytes:
        return await self.conn.read(n)

    async def write(self, data: bytes) -> int:
        return await self.conn.write(data)

    async def close(self) -> None:
        await self.conn.close()


class Transport(ISecureTransport):
    libp2p_privkey: PrivateKey
    noise_privkey: PrivateKey
    local_peer: ID
    early_data: bytes
    with_noise_pipes: bool

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey = None,
        early_data: bytes = None,
        with_noise_pipes: bool = False,
    ) -> None:
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.early_data = early_data
        self.with_noise_pipes = with_noise_pipes

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        # TODO: SecureInbound attempts to complete a noise-libp2p handshake initiated
        #   by a remote peer over the given InsecureConnection.
        return NoiseConnection(self.local_peer, self.libp2p_privkey, None, conn, False)

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        # TODO: Validate libp2p pubkey with `peer_id`. Abort if not correct.
        # NOTE: Implementations that support Noise Pipes must decide whether to use
        #   an XX or IK handshake based on whether they possess a cached static
        #   Noise key for the remote peer.
        return NoiseConnection(
            self.local_peer, self.libp2p_privkey, peer_id, conn, False
        )
