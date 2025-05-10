from abc import (
    ABC,
    abstractmethod,
)
import logging

from cryptography.hazmat.primitives import (
    serialization,
)
from noise.backends.default.keypairs import KeyPair as NoiseKeyPair
from noise.connection import Keypair as NoiseKeypairEnum
from noise.connection import NoiseConnection as NoiseState

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
    verify_handshake_payload_sig,
)


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
    early_data: bytes

    def create_noise_state(self) -> NoiseState:
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypairEnum.STATIC, self.noise_static_key.to_bytes()
        )
        return noise_state

    def make_handshake_payload(self) -> NoiseHandshakePayload:
        pubkey = self.libp2p_privkey.get_public_key()
        logging.debug(f"Public key bytes: {pubkey.to_bytes().hex()}")
        return NoiseHandshakePayload(pubkey, b"")  # Pass PublicKey object directly


class PatternXX(BasePattern):
    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        early_data: bytes = None,
    ) -> None:
        self.protocol_name = b"Noise_XX_25519_ChaChaPoly_SHA256"
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        libp2p_pubkey = libp2p_privkey.get_public_key().to_bytes()
        noise_pubkey = noise_static_key.get_public_key().to_bytes()
        logging.debug(f"libp2p_privkey pubkey: {libp2p_pubkey.hex()}")
        logging.debug(f"noise_static_key pubkey: {noise_pubkey.hex()}")
        if libp2p_pubkey != noise_pubkey:
            raise ValueError(
                "libp2p_privkey and noise_static_key must match for Noise XX"
            )

    async def handshake_inbound(
        self, conn: IRawConnection, remote_peer_id: ID = None
    ) -> ISecureConn:
        logging.debug(f"Starting outbound handshake with peer {remote_peer_id}")
        noise_state = self.create_noise_state()
        logging.debug(
            f"Noise state initialized with static key: {self.noise_static_key}"
        )
        noise_state.set_as_responder()
        noise_state.start_handshake()
        handshake_state = noise_state.noise_protocol.handshake_state
        read_writer = NoiseHandshakeReadWriter(conn, noise_state)

        # Consume msg#1.
        await read_writer.read_msg()

        # Send msg#2, which should include our handshake payload.
        our_payload = self.make_handshake_payload()
        msg_2 = our_payload.serialize()
        await read_writer.write_msg(msg_2)

        # Receive and consume msg#3.
        msg_3 = await read_writer.read_msg()
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
        logging.debug(f"Starting outbound handshake with peer {remote_peer}")
        noise_state = self.create_noise_state()

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        handshake_state = noise_state.noise_protocol.handshake_state

        # Send Msg #1: e
        msg_1 = b""
        await read_writer.write_msg(msg_1)
        msg_1_sent = read_writer.last_written_data
        logging.debug(f"Sent Msg #1: {msg_1_sent.hex()}")

        # Receive Msg #2: e, ee, s, es
        msg_2 = await read_writer.read_msg()
        logging.debug(f"Received Msg #2: {msg_2.hex()}")
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_2)
        if handshake_state.rs is None:
            raise NoiseStateError("Remote static key missing after Msg #2")
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)
        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            raise InvalidSignature(
                f"Invalid signature in Msg #2 for peer {remote_peer}"
            )
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                f"Expected {remote_peer}, got {remote_peer_id_from_pubkey}"
            )

        # Send Msg #3: s, se
        our_payload = self.make_handshake_payload()
        static_key_bytes = self.libp2p_privkey.get_public_key().to_bytes()
        transcript = b"noise-libp2p-static-key:" + static_key_bytes
        logging.debug(f"Transcript for signature: {transcript.hex()}")
        logging.debug(f"Signing with privkey, pubkey: {static_key_bytes.hex()}")
        signature = self.libp2p_privkey.sign(transcript)
        logging.debug(f"Signature: {signature.hex()}")
        # Self-check signature
        pubkey = self.libp2p_privkey.get_public_key()
        try:
            if not pubkey.verify(transcript, signature):
                raise ValueError("Signature verification failed locally")
            logging.debug("Signature verified locally")
        except Exception as e:
            logging.error(f"Signature verification failed: {str(e)}")
            raise
        our_payload.id_sig = signature
        msg_3_raw = our_payload.serialize()
        logging.debug(
            f"Prepared Msg #3 raw: {msg_3_raw.hex()}, length: {len(msg_3_raw)}"
        )
        await read_writer.write_msg(msg_3_raw)
        msg_3_sent = read_writer.last_written_data
        logging.debug(f"Sent Msg #3 (s, se): {msg_3_sent.hex()}")

        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished("Handshake not marked as finished")
        logging.debug("Handshake completed")
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
        raw_bytes = key_pair.public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return Ed25519PublicKey.from_bytes(raw_bytes)
