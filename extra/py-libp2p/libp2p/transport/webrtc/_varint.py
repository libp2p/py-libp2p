"""
Unsigned varint encoding for WebRTC data-channel and signaling framing.

Both stream-level data-channel framing and signaling stream framing use the
same unsigned-varint length-prefix encoding documented in the libp2p
WebRTC spec.  These sync helpers are shared between modules; for streaming
async reads see :func:`libp2p.transport.webrtc.signaling._read_uvarint`.
"""

from __future__ import annotations

# Spec ceiling: a varint encodes at most uint64, which fits in 10 bytes.
_MAX_VARINT_BYTES = 10


def encode_uvarint(value: int) -> bytes:
    """Encode a non-negative integer as an unsigned varint."""
    if value < 0:
        raise ValueError("uvarint cannot encode negative values")
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def decode_uvarint(data: bytes | bytearray, offset: int = 0) -> tuple[int, int]:
    """
    Decode an unsigned varint from *data* starting at *offset*.

    :returns: ``(value, bytes_consumed)``.
    :raises ValueError: If the varint is truncated or exceeds 10 bytes.
    """
    result = 0
    shift = 0
    for i in range(_MAX_VARINT_BYTES):
        pos = offset + i
        if pos >= len(data):
            raise ValueError("truncated uvarint")
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, i + 1
        shift += 7
    raise ValueError(f"uvarint exceeds {_MAX_VARINT_BYTES} bytes")
