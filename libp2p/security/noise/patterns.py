"""
Noise protocol handshake patterns implementation.

This module provides the core handshake patterns for the Noise protocol,
including the abstract interface and concrete implementations like the XX pattern.
The XX pattern is the standard for libp2p Noise connections, providing mutual
authentication and forward secrecy through a three-message handshake.
"""

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import logging
from typing import Any

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
from libp2p.crypto.keys import (
    KeyType,
    PrivateKey,
    PublicKey,
)
from libp2p.crypto.x25519 import (
    X25519PublicKey,
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
    NoiseExtensions,
    NoiseHandshakePayload,
    build_handshake_payload,
    verify_handshake_payload_sig,
)
from .transcript_binding import (
    TranscriptBindingConfig,
    check_negotiation,
    is_enabled,
)

logger = logging.getLogger(__name__)


class _DeferredPayload(bytes):
    """
    Placeholder plaintext for a payload that is built at encryption time.

    ``noiseprotocol`` runs a message's tokens and encrypts its payload inside
    one ``write_message`` call, so the payload has to be handed over before the
    transcript hash reaches the value it will be encrypted under. An instance
    of this class is passed instead, and the hook installed by
    :func:`_transcript_bound_payload` swaps in the real payload.
    """


def _get_symmetric_state(noise_state: NoiseState) -> Any:
    """
    Return the Noise SymmetricState, which holds the transcript hash ``h``.

    Args:
        noise_state: The connection driving this handshake.

    Returns:
        The underlying library's SymmetricState object.

    Raises:
        NoiseStateError: If the handshake state is not initialized.

    """
    protocol = noise_state.noise_protocol
    if protocol is None or protocol.handshake_state is None:
        raise NoiseStateError("noise handshake state is not initialized")
    return protocol.handshake_state.symmetric_state


def _reject_nested_hook(symmetric_state: Any, name: str) -> None:
    """
    Refuse to install a hook over one that is already installed.

    Nesting would capture the outer hook as ``original`` and then remove it on
    the inner exit, leaving the outer context running without its hook. The
    placeholder would be encrypted verbatim as an empty payload. Nothing nests
    today; this makes sure a later refactor that does nest fails loudly.

    Args:
        symmetric_state: The library symmetric state being patched.
        name: The method being replaced.

    Raises:
        NoiseStateError: If an instance attribute of that name already exists.

    """
    if name in symmetric_state.__dict__:
        raise NoiseStateError(
            f"{name} is already patched on this symmetric state; "
            "transcript-binding hooks must not be nested"
        )


def _remove_hook(symmetric_state: Any, name: str) -> None:
    """
    Remove a hook, tolerating its absence.

    ``del`` would raise from a ``finally`` block if the attribute were already
    gone, replacing whatever exception was in flight with an unrelated
    ``AttributeError``.

    Args:
        symmetric_state: The library symmetric state being patched.
        name: The method to restore to its class implementation.

    """
    symmetric_state.__dict__.pop(name, None)


@contextmanager
def _transcript_bound_payload(
    noise_state: NoiseState, build_payload: Callable[[bytes], bytes]
) -> Iterator[bytes]:
    """
    Let a payload commit to the transcript hash it is encrypted under.

    Yields a placeholder to hand to ``write_msg``. When the library reaches the
    payload, ``h`` is final, and the placeholder is replaced by
    ``build_payload(h)``. The static-key token also encrypts through this hook,
    which is why only the placeholder is substituted.

    Args:
        noise_state: The connection driving this handshake.
        build_payload: Builds the serialized payload from the transcript hash.

    Yields:
        bytes: The placeholder to pass to ``write_msg``.

    """
    symmetric_state = _get_symmetric_state(noise_state)
    _reject_nested_hook(symmetric_state, "encrypt_and_hash")
    original = symmetric_state.encrypt_and_hash
    fired = False

    def encrypt_and_hash(plaintext: bytes) -> bytes:
        nonlocal fired
        if isinstance(plaintext, _DeferredPayload):
            fired = True
            plaintext = build_payload(symmetric_state.h)
        return original(plaintext)

    symmetric_state.encrypt_and_hash = encrypt_and_hash
    try:
        yield _DeferredPayload()
        # Reached only when the caller completed without raising. If the hook
        # never fired, the library encrypted the empty placeholder as the
        # handshake payload and shipped it, which the remote would reject as a
        # bad signature. Fail loudly here instead of producing that.
        if not fired:
            raise NoiseStateError(
                "transcript-bound payload hook did not fire: the handshake "
                "payload was not built, which means the underlying noise "
                "library no longer routes payloads through encrypt_and_hash"
            )
    finally:
        _remove_hook(symmetric_state, "encrypt_and_hash")


@contextmanager
def _captured_payload_hashes(noise_state: NoiseState) -> Iterator[list[bytes]]:
    """
    Record the transcript hash used as associated data for each decryption.

    The handshake payload is the last thing a message decrypts, so the last
    recorded value is the one the remote peer signed.

    Args:
        noise_state: The connection driving this handshake.

    Yields:
        list[bytes]: The recorded hashes, filled in as decryption happens.

    """
    symmetric_state = _get_symmetric_state(noise_state)
    _reject_nested_hook(symmetric_state, "decrypt_and_hash")
    original = symmetric_state.decrypt_and_hash
    hashes: list[bytes] = []

    def decrypt_and_hash(ciphertext: bytes) -> bytes:
        hashes.append(symmetric_state.h)
        return original(ciphertext)

    symmetric_state.decrypt_and_hash = decrypt_and_hash
    try:
        yield hashes
    finally:
        _remove_hook(symmetric_state, "decrypt_and_hash")


class IPattern(ABC):
    """
    Abstract interface for Noise protocol handshake patterns.

    Defines the contract that all Noise handshake implementations must follow,
    ensuring consistent behavior across different protocol patterns.
    """

    @abstractmethod
    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Perform inbound handshake as responder.

        Args:
            conn: Raw connection to perform handshake on

        Returns:
            ISecureConn: Established secure connection

        Raises:
            NoiseStateError: If handshake state is invalid
            InvalidSignature: If signature verification fails
            HandshakeHasNotFinished: If handshake doesn't complete properly

        """
        ...

    @abstractmethod
    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID | None
    ) -> ISecureConn:
        """
        Perform outbound handshake as initiator.

        ``remote_peer=None`` is for initiators that do not know the
        responder's identity up front (e.g. a WebRTC-Direct listener, which
        is the Noise initiator per spec): the remote is still authenticated by
        its signed handshake payload; only the peer-ID equality check is
        skipped.

        Args:
            conn: Raw connection to perform handshake on
            remote_peer: Expected remote peer ID for verification, or ``None``

        Returns:
            ISecureConn: Established secure connection

        Raises:
            NoiseStateError: If handshake state is invalid
            InvalidSignature: If signature verification fails
            PeerIDMismatchesPubkey: If peer ID doesn't match public key
            HandshakeHasNotFinished: If handshake doesn't complete properly

        """
        ...


class BasePattern(IPattern):
    """
    Base implementation for Noise protocol handshake patterns.

    Provides common functionality for Noise handshake patterns including:
    - Noise state creation and management
    - Handshake payload generation with early data support
    - Protocol-specific configuration
    """

    protocol_name: bytes
    noise_static_key: PrivateKey
    local_peer: ID
    libp2p_privkey: PrivateKey
    early_data: bytes | None
    transcript_binding: TranscriptBindingConfig | None = None

    def create_noise_state(self, prologue: bytes | None = None) -> NoiseState:
        noise_state = NoiseState.from_name(self.protocol_name)
        noise_state.set_keypair_from_private_bytes(
            NoiseKeypairEnum.STATIC, self.noise_static_key.to_bytes()
        )
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        if prologue is not None:
            noise_state.noise_protocol.prologue = prologue
        return noise_state

    def _validate_noise_static_key(self) -> X25519PublicKey:
        """
        Validate and return the X25519 public key from noise_static_key.

        Raises:
            NoiseStateError: If noise_static_key is not X25519 type

        """
        if self.noise_static_key.get_type() != KeyType.X25519:
            raise NoiseStateError(
                "noise_static_key must be X25519 for Noise DH; "
                f"got {self.noise_static_key.get_type()}"
            )
        pubkey = self.noise_static_key.get_public_key()
        assert isinstance(pubkey, X25519PublicKey), "Expected X25519PublicKey"
        return pubkey

    def make_handshake_payload(
        self,
        extensions: NoiseExtensions | None = None,
        payload_hash: bytes | None = None,
    ) -> NoiseHandshakePayload:
        """
        Build this peer's handshake payload.

        Args:
            extensions: Extensions to carry, or None.
            payload_hash: The transcript hash this payload will be encrypted
            under, or None when transcript binding is off.

        Returns:
            NoiseHandshakePayload: The payload, ready to serialize.

        """
        # Sign the X25519 public key (not the Ed25519 public key)
        # The Noise protocol uses X25519 keys for the DH exchange
        noise_static_pubkey = self._validate_noise_static_key()
        noise_static_pubkey_hex = noise_static_pubkey.to_bytes().hex()
        logger.debug(
            f"make_handshake_payload: X25519 pubkey: {noise_static_pubkey_hex}"
        )

        # Prefer explicit early_data and fall back to self.early_data.
        final_extensions = extensions
        if (
            extensions is not None
            and extensions.early_data is None
            and self.early_data is not None
        ):
            final_extensions = NoiseExtensions(
                webtransport_certhashes=extensions.webtransport_certhashes,
                stream_muxers=extensions.stream_muxers,
                security_protocols=extensions.security_protocols,
                transcript_sig=extensions.transcript_sig,
                early_data=self.early_data,
            )

        return build_handshake_payload(
            self.libp2p_privkey,
            noise_static_pubkey,
            extensions=final_extensions,
            config=self.transcript_binding,
            payload_hash=payload_hash,
        )

    async def write_handshake_payload(
        self,
        read_writer: NoiseHandshakeReadWriter,
        noise_state: NoiseState,
        extensions: NoiseExtensions | None = None,
    ) -> None:
        """
        Write one handshake message carrying this peer's payload.

        With transcript binding off this is the plain "serialize, then send"
        it has always been. With it on, the payload is built inside the
        library's encryption step so that it can commit to the transcript hash
        that step uses as associated data.

        Args:
            read_writer: The handshake message reader/writer.
            noise_state: The connection driving this handshake.
            extensions: Extensions to carry, or None.

        """
        if not is_enabled(self.transcript_binding):
            await read_writer.write_msg(
                self.make_handshake_payload(extensions).serialize()
            )
            return

        def build_payload(payload_hash: bytes) -> bytes:
            return self.make_handshake_payload(extensions, payload_hash).serialize()

        with _transcript_bound_payload(noise_state, build_payload) as placeholder:
            await read_writer.write_msg(placeholder)

    async def read_handshake_payload(
        self, read_writer: NoiseHandshakeReadWriter, noise_state: NoiseState
    ) -> tuple[NoiseHandshakePayload, bytes | None]:
        """
        Read one handshake message and decode the remote peer's payload.

        Args:
            read_writer: The handshake message reader/writer.
            noise_state: The connection driving this handshake.

        Returns:
            tuple: The decoded payload and the transcript hash it was
            encrypted under, which is None when transcript binding is off.

        """
        if not is_enabled(self.transcript_binding):
            return NoiseHandshakePayload.deserialize(await read_writer.read_msg()), None

        with _captured_payload_hashes(noise_state) as hashes:
            msg = await read_writer.read_msg()

        return NoiseHandshakePayload.deserialize(msg), (hashes[-1] if hashes else None)


class PatternXX(BasePattern):
    """
    Noise XX handshake pattern implementation.

    The XX pattern provides mutual authentication and forward secrecy through
    a three-message handshake:
    1. Initiator sends empty message
    2. Responder sends static public key + handshake payload
    3. Initiator sends static public key + handshake payload

    This pattern is the standard for libp2p Noise connections.
    """

    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        early_data: bytes | None = None,
        prologue: bytes | None = None,
        transcript_binding: TranscriptBindingConfig | None = None,
    ) -> None:
        self.protocol_name = b"Noise_XX_25519_ChaChaPoly_SHA256"
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        self.early_data = early_data
        self.prologue = prologue
        self.transcript_binding = transcript_binding

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        logger.debug(f"Noise XX handshake_inbound started for peer {self.local_peer}")
        noise_state = self.create_noise_state(prologue=self.prologue)
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
        await self.write_handshake_payload(read_writer, noise_state)
        logger.debug("Noise XX handshake_inbound: sent msg#2 successfully")

        # Receive and consume msg#3.
        logger.debug("Noise XX handshake_inbound: reading msg#3")
        peer_handshake_payload, payload_hash = await self.read_handshake_payload(
            read_writer, noise_state
        )
        logger.debug("Noise XX handshake_inbound: read msg#3")

        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#3, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)
        logger.debug(
            f"handshake_inbound: received remote pubkey: "
            f"{remote_pubkey.to_bytes().hex()}"
        )

        if not verify_handshake_payload_sig(
            peer_handshake_payload,
            remote_pubkey,
            config=self.transcript_binding,
            payload_hash=payload_hash,
        ):
            raise InvalidSignature
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)

        # Both signed offers are in hand, so the negotiation can be replayed.
        check_negotiation(
            self.transcript_binding,
            is_initiator=False,
            remote_extensions=peer_handshake_payload.extensions,
        )

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
        self, conn: IRawConnection, remote_peer: ID | None
    ) -> ISecureConn:
        logger.debug(f"Noise XX handshake_outbound started to peer {remote_peer}")
        noise_state = self.create_noise_state(prologue=self.prologue)

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
        peer_handshake_payload, payload_hash = await self.read_handshake_payload(
            read_writer, noise_state
        )
        logger.debug("Noise XX handshake_outbound: read msg#2")

        if handshake_state.rs is None:
            raise NoiseStateError(
                "something is wrong in the underlying noise `handshake_state`: "
                "we received and consumed msg#2, which should have included the "
                "remote static public key, but it is not present in the handshake_state"
            )
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)
        logger.debug(
            f"handshake_outbound: received remote pubkey: "
            f"{remote_pubkey.to_bytes().hex()}"
        )

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
        if not verify_handshake_payload_sig(
            peer_handshake_payload,
            remote_pubkey,
            config=self.transcript_binding,
            payload_hash=payload_hash,
        ):
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
        if remote_peer is not None and remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                "peer id does not correspond to the received pubkey: "
                f"remote_peer={remote_peer}, "
                f"remote_peer_id_from_pubkey={remote_peer_id_from_pubkey}"
            )

        # Both signed offers are in hand once msg#2 is verified, so replay the
        # negotiation before msg#3: sending first would put our payload, and
        # any early data, into a session we are about to call a downgrade.
        check_negotiation(
            self.transcript_binding,
            is_initiator=True,
            remote_extensions=peer_handshake_payload.extensions,
        )

        # Send msg#3, which includes our encrypted payload and our noise static key.
        await self.write_handshake_payload(read_writer, noise_state)

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
        # Use `X25519PublicKey` since X25519 is used for Noise DH.
        if key_pair.public is None:
            raise NoiseStateError("public key is not initialized")
        raw_bytes = key_pair.public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return X25519PublicKey.from_bytes(raw_bytes)
