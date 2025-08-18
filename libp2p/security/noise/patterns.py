from abc import (
    ABC,
    abstractmethod,
)

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

from .early_data import (
    EarlyDataHandler,
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
from .pb import noise_pb2 as noise_pb


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
    initiator_early_data_handler: EarlyDataHandler | None
    responder_early_data_handler: EarlyDataHandler | None

    def create_noise_state(self) -> NoiseState:
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypairEnum.STATIC, self.noise_static_key.to_bytes()
        )
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        return noise_state

    async def make_handshake_payload(
        self, conn: IRawConnection, peer_id: ID, is_initiator: bool
    ) -> NoiseHandshakePayload:
        signature = make_handshake_payload_sig(
            self.libp2p_privkey, self.noise_static_key.get_public_key()
        )

        # NEW: Get early data from appropriate handler
        extensions = None
        if is_initiator and self.initiator_early_data_handler:
            extensions = await self.initiator_early_data_handler.send(conn, peer_id)
        elif not is_initiator and self.responder_early_data_handler:
            extensions = await self.responder_early_data_handler.send(conn, peer_id)

        # NEW: Serialize extensions into early_data field
        early_data = None
        if extensions:
            early_data = extensions.SerializeToString()

        return NoiseHandshakePayload(
            self.libp2p_privkey.get_public_key(),
            signature,
            early_data,  # ← This is the key addition
        )

    async def handle_received_payload(
        self, conn: IRawConnection, payload: NoiseHandshakePayload, is_initiator: bool
    ) -> None:
        """Process early data from received payload"""
        if not payload.early_data:
            return

        # Deserialize the NoiseExtensions from early_data field
        try:
            extensions = noise_pb.NoiseExtensions.FromString(payload.early_data)
        except Exception:
            # Invalid extensions, ignore silently
            return

        # Pass to appropriate handler
        if is_initiator and self.initiator_early_data_handler:
            await self.initiator_early_data_handler.received(conn, extensions)
        elif not is_initiator and self.responder_early_data_handler:
            await self.responder_early_data_handler.received(conn, extensions)


class PatternXX(BasePattern):
    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        initiator_early_data_handler: EarlyDataHandler | None,
        responder_early_data_handler: EarlyDataHandler | None,
    ) -> None:
        self.protocol_name = b"Noise_XX_25519_ChaChaPoly_SHA256"
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        self.initiator_early_data_handler = initiator_early_data_handler
        self.responder_early_data_handler = responder_early_data_handler

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        noise_state = self.create_noise_state()
        noise_state.set_as_responder()
        noise_state.start_handshake()
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        handshake_state = noise_state.noise_protocol.handshake_state
        if handshake_state is None:
            raise NoiseStateError("Handshake state is not initialized")

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)

        # 1. Consume msg#1 (just empty bytes)
        await read_writer.read_msg()

        # 2. Send msg#2 with our payload INCLUDING EARLY DATA
        our_payload = await self.make_handshake_payload(
            conn,
            self.local_peer,  # We send our own peer ID in responder role
            is_initiator=False,
        )
        msg_2 = our_payload.serialize()
        await read_writer.write_msg(msg_2)

        # 3. Receive msg#3
        msg_3 = await read_writer.read_msg()
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_3)

        # Extract remote pubkey from noise handshake state
        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#3, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)

        # 4. Verify signature (unchanged)
        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            raise InvalidSignature

        # NEW: Process early data from msg#3 AFTER signature verification
        await self.handle_received_payload(
            conn, peer_handshake_payload, is_initiator=False
        )

        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)

        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished(
                "handshake is done but it is not marked as finished in `noise_state`"
            )

        # NEW: Get negotiated muxer for connection state
        # negotiated_muxer = None
        if self.responder_early_data_handler and hasattr(
            self.responder_early_data_handler, "match_muxers"
        ):
            # negotiated_muxer =
            # self.responder_early_data_handler.match_muxers(is_initiator=False)
            pass

        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=remote_pubkey,
            is_initiator=False,
            conn=transport_read_writer,
            # NOTE: negotiated_muxer would need to be added to SecureSession constructor
            # For now, store it in connection metadata or similar
        )

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        noise_state = self.create_noise_state()

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        handshake_state = noise_state.noise_protocol.handshake_state
        if handshake_state is None:
            raise NoiseStateError("Handshake state is not initialized")

        # 1. Send msg#1 (empty) - no early data possible in XX pattern
        msg_1 = b""
        await read_writer.write_msg(msg_1)

        # 2. Read msg#2 from responder
        msg_2 = await read_writer.read_msg()
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_2)

        # Extract remote pubkey from noise handshake state
        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#2, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)

        # Verify signature BEFORE processing early data (security)
        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            raise InvalidSignature

        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                "peer id does not correspond to the received pubkey: "
                f"remote_peer={remote_peer}, "
                f"remote_peer_id_from_pubkey={remote_peer_id_from_pubkey}"
            )

        # NEW: Process early data from msg#2 AFTER verification
        await self.handle_received_payload(
            conn, peer_handshake_payload, is_initiator=True
        )

        # 3. Send msg#3 with our payload INCLUDING EARLY DATA
        our_payload = await self.make_handshake_payload(
            conn, remote_peer, is_initiator=True
        )
        msg_3 = our_payload.serialize()
        await read_writer.write_msg(msg_3)

        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished(
                "handshake is done but it is not marked as finished in `noise_state`"
            )

        # NEW: Get negotiated muxer
        # negotiated_muxer = None
        if self.initiator_early_data_handler and hasattr(
            self.initiator_early_data_handler, "match_muxers"
        ):
            pass
            # negotiated_muxer =
            # self.initiator_early_data_handler.match_muxers(is_initiator=True)

        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=remote_pubkey,
            is_initiator=True,
            conn=transport_read_writer,
            # NOTE: negotiated_muxer would need to be added to SecureSession constructor
            # For now, store it in connection metadata or similar
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
