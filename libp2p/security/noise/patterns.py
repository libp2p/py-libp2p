from abc import (
    ABC,
    abstractmethod,
)
import logging

from cryptography.hazmat.primitives import (
    serialization,
)
from noise.backends.default.keypairs import KeyPair as NoiseKeyPair
from noise.connection import (
    Keypair as NoiseKeypairEnum,
    NoiseConnection as NoiseState,
)

from libp2p.abc import (
    IRawConnection,
    ISecureConn,
)
from libp2p.crypto.ed25519 import (
    Ed25519PublicKey,
)
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.secure_session import (
    SecureSession,
)

from .exceptions import (
    HandshakeHasNotFinished,
    InvalidSignature,
    NoiseStateError,
    PeerIDMismatchesPubkey,
)
from .io import (
    NoiseHandshakeReadWriter,
    NoiseTransportReadWriter,
)
from .messages import (
    NoiseHandshakePayload,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)

logger = logging.getLogger(__name__)


class IPattern(ABC):
    @abstractmethod
    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn: ...

    @abstractmethod
    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn: ...


class BasePattern(IPattern):
    protocol_name: bytes
    noise_static_key: PrivateKey
    local_peer: ID
    libp2p_privkey: PrivateKey
    early_data: bytes | None

    def create_noise_state(self) -> NoiseState:
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypairEnum.STATIC, self.noise_static_key.to_bytes()
        )
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        return noise_state

    def make_handshake_payload(self) -> NoiseHandshakePayload:
        signature = make_handshake_payload_sig(
            self.libp2p_privkey, self.noise_static_key.get_public_key()
        )
        return NoiseHandshakePayload(self.libp2p_privkey.get_public_key(), signature)


class PatternXX(BasePattern):
    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        early_data: bytes | None = None,
    ) -> None:
        self.protocol_name = b"Noise_XX_25519_ChaChaPoly_SHA256"
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        self.early_data = early_data

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        logger.debug(f"Noise XX handshake_inbound started for peer {self.local_peer}")
        noise_state = self.create_noise_state()
        noise_state.set_as_responder()
        noise_state.start_handshake()
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        handshake_state = noise_state.noise_protocol.handshake_state
        if handshake_state is None:
            raise NoiseStateError("Handshake state is not initialized")

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)

        # Consume msg#1.
        logger.debug("Noise XX handshake_inbound: reading msg#1")
        await read_writer.read_msg()
        logger.debug("Noise XX handshake_inbound: read msg#1 successfully")

        # Send msg#2, which should include our handshake payload.
        logger.debug("Noise XX handshake_inbound: preparing msg#2")
        our_payload = self.make_handshake_payload()
        msg_2 = our_payload.serialize()
        logger.debug(f"Noise XX handshake_inbound: sending msg#2 ({len(msg_2)} bytes)")
        await read_writer.write_msg(msg_2)
        logger.debug("Noise XX handshake_inbound: sent msg#2 successfully")

        # Receive and consume msg#3.
        logger.debug("Noise XX handshake_inbound: reading msg#3")
        msg_3 = await read_writer.read_msg()
        logger.debug(f"Noise XX handshake_inbound: read msg#3 ({len(msg_3)} bytes)")
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_3)

        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#3, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)

        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            raise InvalidSignature
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)

        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished(
                "handshake is done but it is not marked as finished in `noise_state`"
            )
        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=remote_pubkey,
            is_initiator=False,
            conn=transport_read_writer,
        )

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        logger.debug(f"Noise XX handshake_outbound started to peer {remote_peer}")
        noise_state = self.create_noise_state()

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        handshake_state = noise_state.noise_protocol.handshake_state
        if handshake_state is None:
            raise NoiseStateError("Handshake state is not initialized")

        # Send msg#1, which is *not* encrypted.
        logger.debug("Noise XX handshake_outbound: sending msg#1")
        msg_1 = b""
        await read_writer.write_msg(msg_1)
        logger.debug("Noise XX handshake_outbound: sent msg#1 successfully")

        # Read msg#2 from the remote, which contains the public key of the peer.
        logger.debug("Noise XX handshake_outbound: reading msg#2")
        msg_2 = await read_writer.read_msg()
        logger.debug(f"Noise XX handshake_outbound: read msg#2 ({len(msg_2)} bytes)")
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_2)

        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#3, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)

        logger.debug(
            f"Noise XX handshake_outbound: verifying signature for peer {remote_peer}"
        )
        logger.debug(
            f"Noise XX handshake_outbound: remote_pubkey type: {type(remote_pubkey)}"
        )
        id_pubkey_repr = peer_handshake_payload.id_pubkey.to_bytes().hex()
        logger.debug(
            f"Noise XX handshake_outbound: peer_handshake_payload.id_pubkey: "
            f"{id_pubkey_repr}"
        )
        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            logger.error(
                f"Noise XX handshake_outbound: signature verification failed for peer "
                f"{remote_peer}"
            )
            raise InvalidSignature
        logger.debug(
            f"Noise XX handshake_outbound: signature verification successful for peer "
            f"{remote_peer}"
        )
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                "peer id does not correspond to the received pubkey: "
                f"remote_peer={remote_peer}, "
                f"remote_peer_id_from_pubkey={remote_peer_id_from_pubkey}"
            )

        # Send msg#3, which includes our encrypted payload and our noise static key.
        our_payload = self.make_handshake_payload()
        msg_3 = our_payload.serialize()
        await read_writer.write_msg(msg_3)

        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished(
                "handshake is done but it is not marked as finished in `noise_state`"
            )
        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=remote_pubkey,
            is_initiator=True,
            conn=transport_read_writer,
        )

    @staticmethod
    def _get_pubkey_from_noise_keypair(key_pair: NoiseKeyPair) -> PublicKey:
        # Use `Ed25519PublicKey` since 25519 is used in our pattern.
        if key_pair.public is None:
            raise NoiseStateError("public key is not initialized")
        raw_bytes = key_pair.public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return Ed25519PublicKey.from_bytes(raw_bytes)
