"""
Noise XX over the first client-opened WebTransport stream.

Per the WebTransport spec the **client (dialer) is the Noise initiator** and
the server is the responder. The server includes ``webtransport_certhashes``
in its Noise extensions; the client verifies the TLS cert hash is present.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from libp2p.abc import IRawConnection, ISecureConn
from libp2p.connection_types import ConnectionType
from libp2p.crypto.keys import PrivateKey
from libp2p.crypto.x25519 import create_new_key_pair as create_x25519_keypair
from libp2p.peer.id import ID
from libp2p.security.noise.messages import NoiseExtensions, NoiseHandshakePayload
from libp2p.security.noise.patterns import PatternXX
from libp2p.security.secure_session import SecureSession

from .exceptions import WebTransportHandshakeError

if TYPE_CHECKING:
    from multiaddr import Multiaddr

    from .stream import WebTransportStream

logger = logging.getLogger(__name__)


class _StreamRawConn(IRawConnection):
    """Adapt a :class:`WebTransportStream` to :class:`IRawConnection` for Noise."""

    def __init__(self, stream: WebTransportStream, is_initiator: bool) -> None:
        self._stream = stream
        self.is_initiator = is_initiator
        self._closed = False

    async def read(self, n: int | None = None) -> bytes:
        return await self._stream.read(n)

    async def write(self, data: bytes) -> None:
        await self._stream.write(data)

    async def close(self) -> None:
        self._closed = True

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._stream.get_remote_address()

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT


class _PatternXXWithCerthashes(PatternXX):
    """PatternXX that sends / captures ``webtransport_certhashes`` extensions."""

    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        responder_certhashes: list[bytes] | None = None,
    ) -> None:
        super().__init__(
            local_peer=local_peer,
            libp2p_privkey=libp2p_privkey,
            noise_static_key=noise_static_key,
        )
        self._responder_certhashes = responder_certhashes
        self.remote_extensions: NoiseExtensions | None = None

    def make_handshake_payload(
        self, extensions: NoiseExtensions | None = None
    ) -> NoiseHandshakePayload:
        if extensions is None and self._responder_certhashes is not None:
            extensions = NoiseExtensions(
                webtransport_certhashes=list(self._responder_certhashes)
            )
        return super().make_handshake_payload(extensions)

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID | None
    ) -> SecureSession:
        # Re-implement lightly so we can capture responder extensions from msg#2.
        from libp2p.security.noise.exceptions import (
            HandshakeHasNotFinished,
            InvalidSignature,
            NoiseStateError,
            PeerIDMismatchesPubkey,
        )
        from libp2p.security.noise.io import (
            NoiseHandshakeReadWriter,
            NoiseTransportReadWriter,
        )
        from libp2p.security.noise.messages import verify_handshake_payload_sig

        noise_state = self.create_noise_state(prologue=self.prologue)
        read_writer = NoiseHandshakeReadWriter(conn, noise_state)
        noise_state.set_as_initiator()
        noise_state.start_handshake()
        if noise_state.noise_protocol is None:
            raise NoiseStateError("noise_protocol is not initialized")
        handshake_state = noise_state.noise_protocol.handshake_state
        if handshake_state is None:
            raise NoiseStateError("Handshake state is not initialized")

        await read_writer.write_msg(b"")
        msg_2 = await read_writer.read_msg()
        peer_handshake_payload = NoiseHandshakePayload.deserialize(msg_2)
        self.remote_extensions = peer_handshake_payload.extensions

        if handshake_state.rs is None:
            raise NoiseStateError("remote static key missing after msg#2")
        remote_pubkey = self._get_pubkey_from_noise_keypair(handshake_state.rs)
        if not verify_handshake_payload_sig(peer_handshake_payload, remote_pubkey):
            raise InvalidSignature
        remote_peer_id_from_pubkey = ID.from_pubkey(peer_handshake_payload.id_pubkey)
        if remote_peer is not None and remote_peer_id_from_pubkey != remote_peer:
            raise PeerIDMismatchesPubkey(
                "peer id does not correspond to the received pubkey: "
                f"remote_peer={remote_peer}, "
                f"remote_peer_id_from_pubkey={remote_peer_id_from_pubkey}"
            )

        our_payload = self.make_handshake_payload()
        await read_writer.write_msg(our_payload.serialize())

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


def verify_certhashes_extension(
    used_cert_multihash: bytes,
    dial_certhashes: list[bytes],
    remote_extensions: NoiseExtensions | None,
) -> None:
    """
    Client-side check: used TLS cert multihash must appear in the server's
    ``webtransport_certhashes`` extension (and dial-time hashes ⊆ extension).
    """
    if remote_extensions is None or not remote_extensions.has_webtransport_certhashes():
        raise WebTransportHandshakeError(
            "Server did not include webtransport_certhashes Noise extension"
        )
    reported = list(remote_extensions.webtransport_certhashes)
    if used_cert_multihash not in reported:
        raise WebTransportHandshakeError(
            "TLS certificate hash not present in server webtransport_certhashes"
        )
    for expected in dial_certhashes:
        if expected not in reported:
            raise WebTransportHandshakeError(
                "Dial certhash missing from server webtransport_certhashes extension"
            )


async def perform_noise_handshake(
    stream: WebTransportStream,
    *,
    local_peer: ID,
    libp2p_privkey: PrivateKey,
    is_initiator: bool,
    remote_peer: ID | None = None,
    responder_certhashes: list[bytes] | None = None,
    used_cert_multihash: bytes | None = None,
    dial_certhashes: list[bytes] | None = None,
) -> ID:
    """
    Run Noise XX on *stream*.

    :returns: Authenticated remote peer ID.
    """
    noise_kp = create_x25519_keypair()
    pattern = _PatternXXWithCerthashes(
        local_peer=local_peer,
        libp2p_privkey=libp2p_privkey,
        noise_static_key=noise_kp.private_key,
        responder_certhashes=responder_certhashes if not is_initiator else None,
    )
    raw = _StreamRawConn(stream, is_initiator=is_initiator)
    try:
        secure_conn: ISecureConn
        if is_initiator:
            secure_conn = await pattern.handshake_outbound(raw, remote_peer)
            verify_certhashes_extension(
                used_cert_multihash=used_cert_multihash or b"",
                dial_certhashes=dial_certhashes or [],
                remote_extensions=pattern.remote_extensions,
            )
        else:
            secure_conn = await pattern.handshake_inbound(raw)
        remote = secure_conn.get_remote_peer()
        logger.debug(
            "WebTransport Noise handshake complete (initiator=%s, remote=%s)",
            is_initiator,
            remote,
        )
        return remote
    except WebTransportHandshakeError:
        raise
    except Exception as e:
        raise WebTransportHandshakeError(f"Noise handshake failed: {e}") from e
