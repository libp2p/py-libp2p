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
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_APPLIED_ATTR = "_libp2p_keep_pending_fin"


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
