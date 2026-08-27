"""
Noise XX handshake over WebRTC data channel 0.

Per the libp2p WebRTC spec, after a DTLS connection is established the
two peers perform a Noise XX handshake over data channel 0 to mutually
authenticate. Roles are fixed by the spec, not by who dialed: the **server
(listener) is the Noise initiator** and the **dialer is the responder**.

The prologue binds the handshake to the DTLS session with both certificate
fingerprints in **role order** — dialer first, then server — so both sides
must pass the same two values in the same order (see
:func:`build_noise_prologue`)::

    b"libp2p-webrtc-noise:" + encode(dialer_fp) + encode(server_fp)

Where ``encode(fp)`` is the multihash-encoded SHA-256 fingerprint of that
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
from libp2p.utils.varint import decode_varint_with_size

from .constants import MAX_PAYLOAD_SIZE, NOISE_PROLOGUE_PREFIX
from .exceptions import WebRTCHandshakeError
from .pb.webrtc_pb2 import Message
from .stream import _frame

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


def _unframe(raw: bytes) -> tuple[bytes, bool]:
    """
    Decode one uvarint-prefixed ``webrtc.pb.Message`` from a channel message.

    :returns: ``(payload, fin)`` — the ``message`` bytes (possibly empty for a
        pure flag frame) and whether the peer signalled FIN/RESET.
    :raises WebRTCHandshakeError: on malformed framing.
    """
    try:
        length, consumed = decode_varint_with_size(raw)
    except ValueError as e:
        raise WebRTCHandshakeError(f"malformed handshake frame: {e}") from e
    if consumed == 0 or raw[consumed - 1] & 0x80 or consumed + length != len(raw):
        raise WebRTCHandshakeError("malformed handshake frame length")
    msg = Message()
    try:
        msg.ParseFromString(raw[consumed:])
    except Exception as e:  # DecodeError
        raise WebRTCHandshakeError(f"malformed handshake frame: {e}") from e
    fin = msg.HasField("flag") and msg.flag in (Message.FIN, Message.RESET)
    return msg.message, fin


class DataChannelReadWriter(IRawConnection):
    """
    Wraps a WebRTC data channel (stream) as an ``IRawConnection`` so the
    existing Noise handshake code (:class:`PatternXX`) can read/write
    over it without modification.

    The data channel is represented by ``send_cb`` and ``recv_cb`` callables
    rather than a direct aiortc reference.

    Wire format (spec, "Multiplexing" + go/js behaviour): the handshake runs
    over a WebRTC *stream* on channel 0, i.e. every data-channel message is a
    uvarint-length-prefixed ``webrtc.pb.Message`` whose ``message`` field
    carries a chunk of the Noise byte stream (2-byte length prefix + payload).
    ``write`` frames, ``read`` unframes and buffers, so the byte-oriented
    Noise packet reader (``read_exactly(conn, 2)`` then the payload) works
    unchanged and the bytes on the wire match other implementations.
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
        self._closed = False
        self.is_initiator = is_initiator

    async def _fill(self) -> bool:
        """Pull one channel message into the buffer. False once the peer is done."""
        if self._closed:
            return False
        raw = await self._recv_cb()
        if not raw:
            self._closed = True
            return False
        payload, fin = _unframe(raw)
        self._buffer.extend(payload)
        if fin:
            self._closed = True
        return True

    async def read(self, n: int | None = None) -> bytes:
        """
        Read from the data channel.

        With ``n=None`` return whatever is buffered, or the payload of the next
        channel message. With ``n`` return exactly ``n`` bytes, pulling further
        channel messages as needed (short only if the peer closed).
        """
        if n is None:
            if not self._buffer:
                await self._fill()
            data = bytes(self._buffer)
            self._buffer.clear()
            return data
        while len(self._buffer) < n:
            if not await self._fill():
                break  # closed; return what we have (read_exactly raises)
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    async def write(self, data: bytes) -> None:
        """Write Noise bytes to the data channel, framed as stream messages."""
        for offset in range(0, len(data), MAX_PAYLOAD_SIZE):
            chunk = data[offset : offset + MAX_PAYLOAD_SIZE]
            await self._send_cb(_frame(Message(message=chunk)))

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
