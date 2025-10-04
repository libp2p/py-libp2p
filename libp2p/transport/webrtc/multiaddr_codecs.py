"""
Multiaddr codecs for WebRTC protocols.

This module provides codec functions for WebRTC-specific multiaddr protocols
to enable proper encoding and decoding of multiaddr components.
"""

import base64
from collections.abc import ByteString


def webrtc_encode(s: str) -> ByteString:
    """Encode WebRTC protocol component."""
    # WebRTC protocol has no value, return empty bytes
    return b""


def webrtc_decode(b: ByteString) -> str:
    """Decode WebRTC protocol component."""
    # WebRTC protocol has no value, return empty string
    return ""


def webrtc_direct_encode(s: str) -> ByteString:
    """Encode WebRTC-Direct protocol component."""
    # WebRTC-Direct protocol has no value, return empty bytes
    return b""


def webrtc_direct_decode(b: ByteString) -> str:
    """Decode WebRTC-Direct protocol component."""
    # WebRTC-Direct protocol has no value, return empty string
    return ""


def certhash_decode(s: str) -> tuple[int, bytes]:
    if not s:
        raise ValueError("Empty certhash string.")

    # Remove multibase prefix if present
    if s.startswith("uEi"):
        s = s[3:]
    elif s.startswith("u"):
        s = s[1:]

    # Decode base64url encoded hash
    try:
        s_bytes = s.encode("ascii")
        # Add padding if needed
        padding = 4 - (len(s_bytes) % 4)
        if padding != 4:
            s_bytes += b"=" * padding
        raw_bytes = base64.urlsafe_b64decode(s_bytes)
    except Exception as e:
        raise ValueError("Invalid base64url certhash") from e

    if len(raw_bytes) < 2:
        raise ValueError("Decoded certhash is too short to contain multihash header")

    # Multihash format: <code><length><digest>
    code = raw_bytes[0]
    length = raw_bytes[1]
    digest = raw_bytes[2:]

    if len(digest) != length:
        raise ValueError(
            f"Digest length mismatch: expected {length}, got {len(digest)}"
        )

    return code, digest


def certhash_encode(b: ByteString) -> str:
    """Decode certificate hash component."""
    if not b:
        return ""

    # Encode as base64url and add multibase prefix
    b64_hash = base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"uEi{b64_hash}"


__all__ = [
    "webrtc_encode",
    "webrtc_decode",
    "webrtc_direct_encode",
    "webrtc_direct_decode",
    # "certhash_encode",
    # "certhash_decode",
]
