"""
Helpers for aioquic state that its public API does not expose.

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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aioquic.quic.connection import QuicConnection


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
