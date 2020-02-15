from abc import ABC, abstractmethod

from noise.connection import Keypair as NoiseKeypair
from noise.connection import NoiseConnection as NoiseState

from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn

from .connection import NoiseConnection
from .exceptions import HandshakeHasNotFinished
from .io import NoiseHandshakeReadWriter


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
        noise_state.set_as_responder()
        noise_state.start_handshake()
        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        # TODO: Parse and save the payload from the other side.
        _ = await read_writer.read_msg()

        # TODO: Send our payload.
        our_payload = b"server"
        await read_writer.write_msg(our_payload)

        # TODO: Parse and save another payload from the other side.
        _ = await read_writer.read_msg()

        # TODO: Add a specific exception
        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished(
                "handshake done but it is not marked as finished in `noise_state`"
            )

        # FIXME: `remote_peer` should be derived from the messages.
        return NoiseConnection(self.local_peer, self.libp2p_privkey, None, conn, False)

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        noise_state = self.create_noise_state()
        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        await read_writer.write_msg(b"")

        # TODO: Parse and save the payload from the other side.
        _ = await read_writer.read_msg()

        # TODO: Send our payload.
        our_payload = b"client"
        await read_writer.write_msg(our_payload)

        # TODO: Add a specific exception
        if not noise_state.handshake_finished:
            raise Exception

        return NoiseConnection(
            self.local_peer, self.libp2p_privkey, remote_peer, conn, False
        )
