"""IK handshake pattern implementation for Noise protocol."""

from noise.connection import (
    Keypair as NoiseKeypairEnum,
    NoiseConnection as NoiseState,
)

from libp2p.abc import (
    IRawConnection,
    ISecureConn,
)
from libp2p.crypto.secp256k1 import PrivateKey, PublicKey
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import (
    HandshakeHasNotFinished,
    InvalidSignature,
    NoiseStateError,
    PeerIDMismatchesPubkey,
)
from libp2p.security.noise.messages import (
    NoiseExtensions,
    NoiseHandshakePayload,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)
from libp2p.security.noise.patterns import BasePattern
from libp2p.security.secure_session import SecureSession


class PatternIK(BasePattern):
    """
    Noise IK handshake pattern implementation.

    The IK pattern is a one-way authenticated key exchange where the initiator
    knows the responder's static public key beforehand. This pattern provides:
    - Mutual authentication
    - Forward secrecy
    - Reduced handshake latency (2 messages instead of 3)
    """

    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        early_data: bytes | None = None,
        remote_peer: ID | None = None,
        remote_static_key: PublicKey | None = None,
    ):
        """
        Initialize the IK pattern.

        Args:
            local_peer: Local peer ID
            libp2p_privkey: libp2p private key
            noise_static_key: Noise static private key
            early_data: Optional early data
            remote_peer: Remote peer ID (required for IK pattern)
            remote_static_key: Remote static public key (required for IK pattern)

        """
        # Initialize base pattern attributes
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        self.early_data = early_data

        if remote_peer is None:
            raise ValueError("IK pattern requires remote_peer to be specified")
        if remote_static_key is None:
            raise ValueError("IK pattern requires remote_static_key to be specified")

        self.remote_peer = remote_peer
        self.remote_static_key = remote_static_key
        self.protocol_name = b"Noise_IK_25519_ChaChaPoly_SHA256"

    def create_noise_state(self) -> NoiseState:
        """
        Create and configure Noise state for IK pattern.

        Returns:
            NoiseState: Configured Noise state

        """
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypairEnum.STATIC, self.noise_static_key.to_bytes()
        )

        # Set the remote static key for IK pattern
        noise_state.set_keypair_from_public_bytes(
            NoiseKeypairEnum.REMOTE_STATIC, self.remote_static_key.to_bytes()
        )

        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")

        return noise_state

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID
    ) -> ISecureConn:
        """
        Perform outbound IK handshake (initiator).

        Args:
            conn: Raw connection to perform handshake on
            remote_peer: Remote peer ID

        Returns:
            ISecureConn: Secure connection after handshake

        Raises:
            PeerIDMismatchesPubkey: If remote peer ID doesn't match expected
            InvalidSignature: If signature verification fails
            HandshakeHasNotFinished: If handshake doesn't complete properly

        """
        if remote_peer != self.remote_peer:
            raise ValueError(
                f"Remote peer mismatch: expected {self.remote_peer}, got {remote_peer}"
            )

        noise_state = self.create_noise_state()
        noise_state.set_as_initiator()
        noise_state.start_handshake()

        from libp2p.security.noise.io import NoiseHandshakeReadWriter

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)

        # IK pattern: Send encrypted payload immediately (message 1)
        our_payload = self.make_handshake_payload()
        msg_1 = our_payload.serialize()
        await read_writer.write_msg(msg_1)

        # Receive response (message 2)
        msg_2 = await read_writer.read_msg()
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_2)

        # Verify the response
        if not verify_handshake_payload_sig(
            peer_handshake_payload, self.remote_static_key
        ):
            raise InvalidSignature("Invalid signature in IK handshake response")

        # Verify peer ID matches
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                f"peer id mismatch: expected={remote_peer}, "
                f"got={remote_peer_id_from_pubkey}"
            )

        # Verify handshake is complete
        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished("IK handshake not finished")

        # Create secure session
        from libp2p.security.noise.io import NoiseTransportReadWriter

        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)

        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=self.remote_static_key,
            is_initiator=True,
            conn=transport_read_writer,
        )

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Perform inbound IK handshake (responder).

        Args:
            conn: Raw connection to perform handshake on

        Returns:
            ISecureConn: Secure connection after handshake

        Raises:
            InvalidSignature: If signature verification fails
            HandshakeHasNotFinished: If handshake doesn't complete properly

        """
        noise_state = self.create_noise_state()
        noise_state.set_as_responder()
        noise_state.start_handshake()

        from libp2p.security.noise.io import NoiseHandshakeReadWriter

        read_writer = NoiseHandshakeReadWriter(conn, noise_state)

        # Receive encrypted payload (message 1)
        msg_1 = await read_writer.read_msg()
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_1)

        # Verify the payload
        if not verify_handshake_payload_sig(
            peer_handshake_payload, self.remote_static_key
        ):
            raise InvalidSignature("Invalid signature in IK handshake request")

        # Verify peer ID matches expected
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer_id_from_pubkey != self.remote_peer:
            raise PeerIDMismatchesPubkey(
                f"peer id mismatch: expected={self.remote_peer}, "
                f"got={remote_peer_id_from_pubkey}"
            )

        # Send response (message 2)
        our_payload = self.make_handshake_payload()
        msg_2 = our_payload.serialize()
        await read_writer.write_msg(msg_2)

        # Verify handshake is complete
        if not noise_state.handshake_finished:
            raise HandshakeHasNotFinished("IK handshake not finished")

        # Create secure session
        from libp2p.security.noise.io import NoiseTransportReadWriter

        transport_read_writer = NoiseTransportReadWriter(conn, noise_state)

        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id_from_pubkey,
            remote_permanent_pubkey=self.remote_static_key,
            is_initiator=False,
            conn=transport_read_writer,
        )

    def make_handshake_payload(
        self, extensions: NoiseExtensions | None = None
    ) -> NoiseHandshakePayload:
        """
        Create handshake payload for IK pattern.

        Args:
            extensions: Optional noise extensions

        Returns:
            NoiseHandshakePayload: Handshake payload

        """
        signature = make_handshake_payload_sig(
            self.libp2p_privkey, self.noise_static_key.get_public_key()
        )

        # Handle early data through extensions
        if extensions is not None and self.early_data is not None:
            # Create extensions with early data
            extensions_with_early_data = NoiseExtensions(
                webtransport_certhashes=extensions.webtransport_certhashes,
                early_data=self.early_data,
            )
            return NoiseHandshakePayload(
                self.libp2p_privkey.get_public_key(),
                signature,
                early_data=None,  # Early data is now in extensions
                extensions=extensions_with_early_data,
            )
        elif extensions is not None:
            # Extensions without early data
            return NoiseHandshakePayload(
                self.libp2p_privkey.get_public_key(),
                signature,
                early_data=self.early_data,  # Keep legacy early data
                extensions=extensions,
            )
        else:
            # No extensions, use legacy early data
            return NoiseHandshakePayload(
                self.libp2p_privkey.get_public_key(),
                signature,
                early_data=self.early_data,
                extensions=None,
            )
