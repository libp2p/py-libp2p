from abc import ABC, abstractmethod

from noise.connection import Keypair as NoiseKeypair
from noise.connection import NoiseConnection as NoiseState

from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn

from .connection import NoiseConnection

# FIXME: Choose a serious bound number.
NUM_BYTES_TO_READ = 2048


# TODO: Merged into `BasePattern`?
class PreHandshakeConnection:
    conn: IRawConnection

    def __init__(self, conn: IRawConnection) -> None:
        self.conn = conn

    async def write_msg(self, data: bytes) -> None:
        # TODO:
        await self.conn.write(data)

    async def read_msg(self) -> bytes:
        return await self.conn.read(NUM_BYTES_TO_READ)


class IPattern(ABC):
    @abstractmethod
    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        ...

    @abstractmethod
    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        ...


class BasePattern(IPattern):
    protocol_name: bytes
    noise_static_key: PrivateKey
    local_peer: ID
    libp2p_privkey: PrivateKey

    def create_noise_state(self) -> NoiseState:
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypair.STATIC, self.noise_static_key.to_bytes()
        )
        return noise_state


class PatternXX(BasePattern):
    def __init__(
        self, local_peer: ID, libp2p_privkey: PrivateKey, noise_static_key: PrivateKey
    ) -> None:
        self.protocol_name = b"Noise_XX_25519_ChaChaPoly_SHA256"
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        noise_state = self.create_noise_state()
        handshake_conn = PreHandshakeConnection(conn)
        noise_state.set_as_responder()
        noise_state.start_handshake()
        msg_0_encrypted = await handshake_conn.read_msg()
        msg_0 = noise_state.read_message(msg_0_encrypted)
        # TODO: Parse and save the payload from the other side.

        # TODO: Send our payload.
        our_payload = b"server"
        msg_1_encrypted = noise_state.write_message(our_payload)
        await handshake_conn.write_msg(msg_1_encrypted)

        msg_2_encrypted = await handshake_conn.read_msg()
        msg_2 = noise_state.read_message(msg_2_encrypted)
        # TODO: Parse and save another payload from the other side.

        # TODO: Add a specific exception
        if not noise_state.handshake_finished:
            raise Exception

        # FIXME: `remote_peer` should be derived from the messages.
        return NoiseConnection(self.local_peer, self.libp2p_privkey, None, conn, False)

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        noise_state = self.create_noise_state()
        handshake_conn = PreHandshakeConnection(conn)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        msg_0 = noise_state.write_message()
        await handshake_conn.write_msg(msg_0)
        msg_1_encrypted = await handshake_conn.read_msg()
        msg_1 = noise_state.read_message(msg_1_encrypted)
        # TODO: Parse and save the payload from the other side.

        # TODO: Send our payload.
        our_payload = b"client"
        msg_2_encrypted = noise_state.write_message(our_payload)
        await handshake_conn.write_msg(msg_2_encrypted)

        # TODO: Add a specific exception
        if not noise_state.handshake_finished:
            raise Exception

        return NoiseConnection(
            self.local_peer, self.libp2p_privkey, remote_peer, conn, False
        )
