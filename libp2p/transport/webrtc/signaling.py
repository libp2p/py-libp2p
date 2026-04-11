"""
WebRTC signaling protocol for private-to-private connections.

Implements ``/webrtc-signaling/0.0.1`` — the protocol used to exchange SDP
offers/answers and ICE candidates over a Circuit Relay v2 stream so that
two NATed peers can establish a direct WebRTC data-channel connection.

The bilateral ``ICE_DONE`` mechanism (libp2p/specs#585 fix) ensures that
neither side closes the signaling stream before the other has received all
ICE candidates:

.. code-block:: text

    Initiator                              Responder (via relay)
      ──── SDP_OFFER ─────────────────────────>
      <─── SDP_ANSWER ─────────────────────────
      <──> ICE_CANDIDATE (trickle, both ways) <>
      ──── ICE_DONE ───────────────────────────>
      <─── ICE_DONE ───────────────────────────
      (both sides close signaling stream)

Messages are varint-length-prefixed protobuf :class:`SignalingMessage`.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md
"""

from __future__ import annotations

import logging
import struct
from typing import AsyncIterator

import trio

from libp2p.abc import INetStream

from .constants import WEBRTC_SIGNALING_PROTOCOL_ID
from .exceptions import WebRTCSignalingError
from .signaling_pb.signaling_pb2 import SignalingMessage

logger = logging.getLogger(__name__)

# Maximum signaling message size (generous for SDP + candidates)
_MAX_SIGNALING_MSG_SIZE = 65_536

# Timeout for the entire signaling exchange
_SIGNALING_TIMEOUT = 30.0


async def write_signaling_message(
    stream: INetStream,
    msg: SignalingMessage,
) -> None:
    """
    Write a varint-length-prefixed signaling message to the stream.

    :param stream: The relay stream.
    :param msg: The protobuf message to send.
    :raises WebRTCSignalingError: If writing fails.
    """
    data = msg.SerializeToString()
    length = len(data)
    # Encode length as unsigned varint
    varint_buf = _encode_uvarint(length)
    try:
        await stream.write(varint_buf + data)
    except Exception as e:
        raise WebRTCSignalingError(f"Failed to write signaling message: {e}") from e


async def read_signaling_message(stream: INetStream) -> SignalingMessage:
    """
    Read a varint-length-prefixed signaling message from the stream.

    :param stream: The relay stream.
    :returns: The parsed protobuf message.
    :raises WebRTCSignalingError: If reading or parsing fails.
    """
    try:
        length = await _read_uvarint(stream)
        if length > _MAX_SIGNALING_MSG_SIZE:
            raise WebRTCSignalingError(
                f"Signaling message too large: {length} bytes "
                f"(max {_MAX_SIGNALING_MSG_SIZE})"
            )
        data = b""
        while len(data) < length:
            chunk = await stream.read(length - len(data))
            if not chunk:
                raise WebRTCSignalingError(
                    "Stream closed before full signaling message received"
                )
            data += chunk
    except WebRTCSignalingError:
        raise
    except Exception as e:
        raise WebRTCSignalingError(
            f"Failed to read signaling message: {e}"
        ) from e

    msg = SignalingMessage()
    msg.ParseFromString(data)
    return msg


class SignalingSession:
    """
    Manages a signaling exchange between two peers.

    Handles the ordered message flow: SDP_OFFER → SDP_ANSWER → ICE
    candidates (trickle) → bilateral ICE_DONE.

    Usage (initiator side)::

        session = SignalingSession(stream)
        await session.send_offer(sdp_offer_bytes)
        answer_bytes = await session.receive_answer()
        async for candidate in session.receive_candidates():
            # apply candidate to RTCPeerConnection
            pass
        await session.send_candidates(my_candidates)
        await session.complete()  # bilateral ICE_DONE

    Usage (responder side)::

        session = SignalingSession(stream)
        offer_bytes = await session.receive_offer()
        await session.send_answer(sdp_answer_bytes)
        async for candidate in session.receive_candidates():
            pass
        await session.send_candidates(my_candidates)
        await session.complete()
    """

    def __init__(self, stream: INetStream, timeout: float = _SIGNALING_TIMEOUT) -> None:
        self._stream = stream
        self._timeout = timeout
        self._ice_done_sent = False
        self._ice_done_received = False
        self._closed = False

    # ------------------------------------------------------------------
    # SDP exchange
    # ------------------------------------------------------------------

    async def send_offer(self, sdp: bytes) -> None:
        """Send an SDP offer."""
        msg = SignalingMessage(type=SignalingMessage.SDP_OFFER, data=sdp)
        await write_signaling_message(self._stream, msg)
        logger.debug("Sent SDP_OFFER (%d bytes)", len(sdp))

    async def receive_offer(self) -> bytes:
        """Wait for and return the SDP offer."""
        msg = await self._receive_expected(SignalingMessage.SDP_OFFER)
        logger.debug("Received SDP_OFFER (%d bytes)", len(msg.data))
        return msg.data

    async def send_answer(self, sdp: bytes) -> None:
        """Send an SDP answer."""
        msg = SignalingMessage(type=SignalingMessage.SDP_ANSWER, data=sdp)
        await write_signaling_message(self._stream, msg)
        logger.debug("Sent SDP_ANSWER (%d bytes)", len(sdp))

    async def receive_answer(self) -> bytes:
        """Wait for and return the SDP answer."""
        msg = await self._receive_expected(SignalingMessage.SDP_ANSWER)
        logger.debug("Received SDP_ANSWER (%d bytes)", len(msg.data))
        return msg.data

    # ------------------------------------------------------------------
    # ICE candidate exchange (trickle)
    # ------------------------------------------------------------------

    async def send_candidates(self, candidates: list[bytes]) -> None:
        """
        Send all gathered ICE candidates, then send ICE_DONE.

        :param candidates: List of serialized ICE candidate strings.
        """
        for candidate in candidates:
            msg = SignalingMessage(
                type=SignalingMessage.ICE_CANDIDATE, data=candidate
            )
            await write_signaling_message(self._stream, msg)
        logger.debug("Sent %d ICE candidates", len(candidates))

        # Signal that we're done sending candidates
        done_msg = SignalingMessage(type=SignalingMessage.ICE_DONE)
        await write_signaling_message(self._stream, done_msg)
        self._ice_done_sent = True
        logger.debug("Sent ICE_DONE")

    async def receive_candidates(self) -> AsyncIterator[bytes]:
        """
        Yield ICE candidates from the remote peer until ICE_DONE is received.

        This is an async generator — iterate it to get candidates as they
        arrive.  The generator completes when the remote sends ICE_DONE.
        """
        while True:
            msg = await read_signaling_message(self._stream)
            if msg.type == SignalingMessage.ICE_CANDIDATE:
                yield msg.data
            elif msg.type == SignalingMessage.ICE_DONE:
                self._ice_done_received = True
                logger.debug("Received ICE_DONE from remote")
                return
            else:
                logger.warning(
                    "Unexpected signaling message type %s during ICE exchange",
                    msg.type,
                )

    # ------------------------------------------------------------------
    # Completion (bilateral ICE_DONE — specs#585 fix)
    # ------------------------------------------------------------------

    async def complete(self) -> None:
        """
        Complete the signaling exchange.

        Ensures both sides have sent AND received ICE_DONE before closing
        the stream.  This prevents the race condition in specs#585 where
        one side closes the stream before the other has received all
        candidates.
        """
        # If we haven't sent ICE_DONE yet, send it now
        if not self._ice_done_sent:
            done_msg = SignalingMessage(type=SignalingMessage.ICE_DONE)
            await write_signaling_message(self._stream, done_msg)
            self._ice_done_sent = True

        # If we haven't received ICE_DONE yet, wait for it
        if not self._ice_done_received:
            with trio.move_on_after(self._timeout) as scope:
                while not self._ice_done_received:
                    msg = await read_signaling_message(self._stream)
                    if msg.type == SignalingMessage.ICE_DONE:
                        self._ice_done_received = True
                    # Silently discard any late ICE_CANDIDATEs
            if scope.cancelled_caught:
                logger.warning("Timed out waiting for remote ICE_DONE")

        self._closed = True
        logger.debug(
            "Signaling complete (sent_done=%s, recv_done=%s)",
            self._ice_done_sent,
            self._ice_done_received,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _receive_expected(self, expected_type: int) -> SignalingMessage:
        """Read a message and verify its type."""
        msg: SignalingMessage | None = None
        with trio.move_on_after(self._timeout) as scope:
            msg = await read_signaling_message(self._stream)
        if scope.cancelled_caught or msg is None:
            raise WebRTCSignalingError(
                f"Timed out waiting for signaling message type {expected_type}"
            )
        if msg.type != expected_type:
            raise WebRTCSignalingError(
                f"Expected signaling message type {expected_type}, got {msg.type}"
            )
        return msg


# ------------------------------------------------------------------
# Varint encoding/decoding (unsigned, for length prefixing)
# ------------------------------------------------------------------


def _encode_uvarint(value: int) -> bytes:
    """Encode an unsigned integer as a varint."""
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


async def _read_uvarint(stream: INetStream) -> int:
    """Read an unsigned varint from the stream."""
    result = 0
    shift = 0
    for _ in range(10):  # Max 10 bytes for uint64 varint
        byte_data = await stream.read(1)
        if not byte_data:
            raise WebRTCSignalingError("Stream closed while reading varint")
        byte = byte_data[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result
        shift += 7
    raise WebRTCSignalingError("Varint too long (> 10 bytes)")
