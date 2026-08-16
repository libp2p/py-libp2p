"""
Noise XX handshake over WebRTC data channel 0.

Per the libp2p WebRTC spec, after a DTLS connection is established the
two peers perform a Noise XX handshake over data channel 0 to mutually
authenticate.  The Noise prologue binds the handshake to the DTLS session
by incorporating both peers' certificate fingerprints.

Prologue format::

    b"libp2p-webrtc-noise:" + encode(local_fp) + encode(remote_fp)

Where ``encode(fp)`` is the multihash-encoded SHA-256 fingerprint of the
peer's DTLS certificate.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md#noise-handshake
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import struct

from multiaddr import Multiaddr

from libp2p.abc import IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.crypto.keys import PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.patterns import PatternXX

from .constants import NOISE_PROLOGUE_PREFIX
from .exceptions import WebRTCHandshakeError

logger = logging.getLogger(__name__)

# SHA-256 multihash header: code 0x12, length 32
_MH_SHA256_HEADER = struct.pack("BB", 0x12, 32)


def build_noise_prologue(
    dialer_fingerprint: bytes,
    server_fingerprint: bytes,
) -> bytes:
    """
    Build the Noise prologue that binds the handshake to the DTLS session.

    Per the WebRTC-Direct spec the prologue is
    ``"libp2p-webrtc-noise:" || multihash(FP_A) || multihash(FP_B)`` where *A*
    is the dialer (Noise **responder**) and *B* is the server (Noise
    **initiator**). The order is fixed by role, not by "local"/"remote", so both
    sides must pass the same two values in the same order.

    :param dialer_fingerprint: Raw SHA-256 of the dialer's DTLS certificate.
    :param server_fingerprint: Raw SHA-256 of the server's DTLS certificate.
    :returns: The prologue bytes for ``NoiseState.set_prologue()``.
    """
    dialer_mh = _MH_SHA256_HEADER + dialer_fingerprint
    server_mh = _MH_SHA256_HEADER + server_fingerprint
    return NOISE_PROLOGUE_PREFIX + dialer_mh + server_mh


async def perform_noise_handshake(
    conn: IRawConnection,
    local_peer: ID,
    libp2p_privkey: PrivateKey,
    noise_static_key: PrivateKey,
    dialer_fingerprint: bytes,
    server_fingerprint: bytes,
    is_initiator: bool,
    remote_peer: ID | None = None,
) -> ID:
    """
    Run the Noise XX handshake over a data-channel-0 connection.

    Roles follow the WebRTC-Direct spec: the **server (listener) is the Noise
    initiator** and the **dialer is the responder**. This is independent of
    which side opened the WebRTC connection.

    :param conn: A :class:`IRawConnection` wrapping data channel 0.
    :param local_peer: The local peer's ID.
    :param libp2p_privkey: The local peer's libp2p identity private key.
    :param noise_static_key: An ephemeral X25519 key for the Noise session.
    :param dialer_fingerprint: Raw SHA-256 of the dialer's DTLS certificate.
    :param server_fingerprint: Raw SHA-256 of the server's DTLS certificate.
    :param is_initiator: True if this peer is the Noise initiator (the server).
    :param remote_peer: Expected remote peer ID, or ``None`` if unknown (the
        server does not know the dialer's ID; the dialer should verify the
        returned ID against the ``/p2p/`` component itself).
    :returns: The authenticated remote peer ID.
    :raises WebRTCHandshakeError: If the handshake fails.
    """
    prologue = build_noise_prologue(dialer_fingerprint, server_fingerprint)
    logger.debug(
        "Noise handshake prologue: %d bytes (initiator=%s)",
        len(prologue),
        is_initiator,
    )

    pattern = PatternXX(
        local_peer=local_peer,
        libp2p_privkey=libp2p_privkey,
        noise_static_key=noise_static_key,
        prologue=prologue,
    )

    try:
        if is_initiator:
            secure_conn = await pattern.handshake_outbound(conn, remote_peer)
        else:
            secure_conn = await pattern.handshake_inbound(conn)

        authenticated_peer = secure_conn.get_remote_peer()
        logger.debug("Noise handshake completed: remote_peer=%s", authenticated_peer)
        return authenticated_peer

    except WebRTCHandshakeError:
        raise
    except Exception as e:
        raise WebRTCHandshakeError(f"Noise handshake failed: {e}") from e


class DataChannelReadWriter(IRawConnection):
    """
    Wraps a WebRTC data channel (stream) as an ``IRawConnection`` so the
    existing Noise handshake code (:class:`PatternXX`) can read/write
    over it without modification.

    The data channel is represented by ``send_cb`` and ``recv_cb`` callables
    rather than a direct aiortc reference.

    Data channels are message-oriented while the Noise packet reader is
    byte-oriented (``read_exactly(conn, 2)`` for the length prefix, then the
    payload), so ``read(n)`` buffers whole channel messages internally and
    hands out exactly ``n`` bytes at a time.
    """

    def __init__(
        self,
        send_cb: SendCallback,
        recv_cb: RecvCallback,
        is_initiator: bool,
    ) -> None:
        self._send_cb = send_cb
        self._recv_cb = recv_cb
        self._buffer = bytearray()
        self.is_initiator = is_initiator

    async def read(self, n: int | None = None) -> bytes:
        """
        Read from the data channel.

        With ``n=None`` return the next whole channel message (or any buffered
        remainder). With ``n`` return exactly ``n`` bytes, pulling further
        channel messages as needed.
        """
        if n is None:
            if self._buffer:
                data = bytes(self._buffer)
                self._buffer.clear()
                return data
            return await self._recv_cb()
        while len(self._buffer) < n:
            chunk = await self._recv_cb()
            if not chunk:
                break  # channel closed; return what we have (read_exactly raises)
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    async def write(self, data: bytes) -> None:
        """Write a message to the data channel."""
        await self._send_cb(data)

    async def close(self) -> None:
        """No-op — the channel lifecycle is managed by the connection."""

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT


# Callback types for data channel I/O
SendCallback = Callable[[bytes], Awaitable[None]]
RecvCallback = Callable[[], Awaitable[bytes]]
