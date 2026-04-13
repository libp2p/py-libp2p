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

import logging
import struct
from typing import Awaitable, Callable

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
    local_fingerprint: bytes,
    remote_fingerprint: bytes,
) -> bytes:
    """
    Build the Noise prologue that binds the handshake to the DTLS session.

    :param local_fingerprint: Raw SHA-256 of the local DTLS certificate.
    :param remote_fingerprint: Raw SHA-256 of the remote DTLS certificate.
    :returns: The prologue bytes for ``NoiseState.set_prologue()``.
    """
    local_mh = _MH_SHA256_HEADER + local_fingerprint
    remote_mh = _MH_SHA256_HEADER + remote_fingerprint
    return NOISE_PROLOGUE_PREFIX + local_mh + remote_mh


async def perform_noise_handshake(
    conn: IRawConnection,
    local_peer: ID,
    libp2p_privkey: PrivateKey,
    noise_static_key: PrivateKey,
    local_fingerprint: bytes,
    remote_fingerprint: bytes,
    is_initiator: bool,
    remote_peer: ID | None = None,
) -> ID:
    """
    Run the Noise XX handshake over a data-channel-0 connection.

    :param conn: A :class:`IRawConnection` wrapping data channel 0.
    :param local_peer: The local peer's ID.
    :param libp2p_privkey: The local peer's libp2p identity private key.
    :param noise_static_key: An ephemeral X25519 key for the Noise session.
    :param local_fingerprint: Raw SHA-256 of the local DTLS certificate.
    :param remote_fingerprint: Raw SHA-256 of the remote DTLS certificate.
    :param is_initiator: True if this peer initiated the connection.
    :param remote_peer: Expected remote peer ID (for outbound connections).
    :returns: The authenticated remote peer ID.
    :raises WebRTCHandshakeError: If the handshake fails.
    """
    prologue = build_noise_prologue(local_fingerprint, remote_fingerprint)
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
            if remote_peer is None:
                raise WebRTCHandshakeError(
                    "remote_peer is required for outbound Noise handshake"
                )
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
    """

    def __init__(
        self,
        send_cb: SendCallback,
        recv_cb: RecvCallback,
        is_initiator: bool,
    ) -> None:
        self._send_cb = send_cb
        self._recv_cb = recv_cb
        self.is_initiator = is_initiator

    async def read(self, n: int | None = None) -> bytes:
        """Read the next message from the data channel."""
        return await self._recv_cb()

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
