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


def certhash_encode(s: str) -> ByteString:
    """Encode certificate hash component."""
    if not s:
        return b""

    # Remove multibase prefix if present
    if s.startswith("uEi"):
        s = s[3:]
    elif s.startswith("u"):
        s = s[1:]

    # Decode base64url encoded hash
    try:
        # Ensure s is bytes for base64 decoding
        s_bytes = s.encode("ascii") if isinstance(s, str) else s
        # Add padding if needed
        padding = 4 - (len(s_bytes) % 4)
        if padding != 4:
            s_bytes += b"=" * padding
        return base64.urlsafe_b64decode(s_bytes)
    except Exception:
        # Fallback to raw bytes
        return s.encode("utf-8")


def certhash_decode(b: ByteString) -> str:
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
    "certhash_encode",
    "certhash_decode",
]
