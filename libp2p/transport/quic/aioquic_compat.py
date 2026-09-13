"""
Runtime fixes for aioquic behaviour that breaks libp2p stream semantics.

Currently applied:

``QuicStreamSender.get_frame`` loses FIN-only frames on full packets
    When a stream has no pending data but a pending FIN, aioquic clears
    ``_pending_eof`` and returns a FIN-only frame *before* the packet builder
    checks whether the packet has room for it. If ``start_frame`` then raises
    ``QuicPacketBuilderStop`` (typical when earlier streams filled the packet
    with data), the FIN is silently dropped: it is never retransmitted because
    the sender no longer considers it pending, and ``write()`` cannot re-arm it
    ("cannot call write() after FIN").

    In libp2p this shows up whenever a stream is half-closed while other
    streams on the same connection are still draining (e.g. the perf protocol
    client sends its request and half-closes right after a series of large
    uploads): the peer never observes EOF and waits until its read timeout.

    The wrapper defers the FIN-only frame when ``max_size`` is negative, which
    is exactly the condition under which ``start_frame`` would reject it, so
    the FIN stays pending and is emitted in the next packet.

``stream_send_buffer_size`` exposes the un-ACKed send buffer of a stream
    aioquic's ``QuicConnection.send_stream_data`` only appends to an unbounded
    per-stream buffer and returns; nothing in its public API reports how much
    of that buffer is still waiting to be sent or acknowledged. libp2p needs
    that number to apply send-side backpressure in ``QUICStream.write()``
    (otherwise a writer can enqueue gigabytes in memory and "finish" long
    before the peer receives anything). The helper reads the sender's private
    ``_buffer_start`` / ``_buffer_stop`` offsets, which are the only place this
    information exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aioquic.quic.connection import QuicConnection

logger = logging.getLogger(__name__)

_APPLIED_ATTR = "_libp2p_keep_pending_fin"


def stream_send_buffer_size(quic: QuicConnection, stream_id: int) -> int:
    """
    Return the number of bytes written to ``stream_id`` that the peer has not
    acknowledged yet (queued for transmission or in flight).

    Returns 0 when the stream is unknown to aioquic, which also covers the
    normal case of a stream that has been fully delivered and discarded.
    """
    streams = getattr(quic, "_streams", None)
    if not isinstance(streams, dict):
        return 0
    stream = streams.get(stream_id)
    if stream is None:
        return 0
    sender = getattr(stream, "sender", None)
    start = getattr(sender, "_buffer_start", None)
    stop = getattr(sender, "_buffer_stop", None)
    if not isinstance(start, int) or not isinstance(stop, int):
        return 0
    return max(0, stop - start)


def apply() -> None:
    """Install the aioquic fixes. Idempotent and safe to call multiple times."""
    try:
        from aioquic.quic.stream import QuicStreamSender
    except ImportError:  # pragma: no cover - aioquic is a hard dependency
        return

    original = QuicStreamSender.get_frame
    if getattr(original, _APPLIED_ATTR, False):
        return

    def get_frame(self: Any, max_size: int, max_offset: int | None = None) -> Any:
        if (
            max_size < 0
            and getattr(self, "_pending_eof", False)
            and len(self._pending) == 0
        ):
            # Not enough room in this packet for a FIN-only STREAM frame; keep
            # the FIN pending instead of letting aioquic drop it.
            return None
        return original(self, max_size, max_offset)

    setattr(get_frame, _APPLIED_ATTR, True)
    QuicStreamSender.get_frame = get_frame  # type: ignore[method-assign]
    logger.debug("Applied aioquic FIN-only frame fix to QuicStreamSender.get_frame")
