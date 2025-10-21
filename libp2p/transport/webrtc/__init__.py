"""
WebRTC Transport Module for py-libp2p.

Provides both private-to-private and private-to-public WebRTC transport
implementations.
"""

import sys
from .private_to_private.transport import WebRTCTransport
from .constants import (
    DEFAULT_ICE_SERVERS,
    SIGNALING_PROTOCOL,
    MUXER_PROTOCOL,
    WebRTCError,
    SDPHandshakeError,
    ConnectionStateError,
    CertificateError,
    STUNError,
    CODEC_WEBRTC,
    CODEC_WEBRTC_DIRECT,
    CODEC_CERTHASH,
    PROTOCOL_WEBRTC,
    PROTOCOL_WEBRTC_DIRECT,
    PROTOCOL_CERTHASH,
)
from typing import Dict, Any, Protocol as TypingProtocol
from multiaddr import protocols
from multiaddr.protocols import Protocol
from multiaddr import codecs


class WebRTCCodec:
    """Codec for WebRTC protocol (empty protocol with no value)."""
    SIZE = 0
    IS_PATH = False

    @staticmethod
    def to_bytes(proto: Any, s: str) -> bytes:
        return b""

    @staticmethod
    def to_string(proto: Any, b: bytes) -> str:
        return ""


class WebRTCDirectCodec:
    """Codec for WebRTC-Direct protocol (empty protocol with no value)."""
    SIZE = 0
    IS_PATH = False

    @staticmethod
    def to_bytes(proto: Any, s: str) -> bytes:
        return b""

    @staticmethod
    def to_string(proto: Any, b: bytes) -> str:
        return ""


class CerthashCodec:
    """Codec for certificate hash protocol (handles certificate hash encoding/decoding)."""
    SIZE = -1  # Variable size protocol
    LENGTH_PREFIXED_VAR_SIZE = -1
    IS_PATH = False

    @staticmethod
    def to_bytes(proto: Any, s: str) -> bytes:
        if not s:
            return b""
        # Remove multibase prefix if present
        if s.startswith('uEi'):
            s = s[3:]
        elif s.startswith('u'):
            s = s[1:]
        # Decode base64url encoded hash
        try:
            import base64
            # Ensure s is encoded as bytes for base64 decoding
            s_bytes = s.encode('ascii') if isinstance(s, str) else s
            padding = 4 - (len(s_bytes) % 4)
            if padding != 4:
                s_bytes += b'=' * padding
            return base64.urlsafe_b64decode(s_bytes)
        except Exception:
            return s.encode('utf-8')

    @staticmethod
    def to_string(proto: Any, b: bytes) -> str:
        if not b:
            return ""
        import base64
        b64_hash = base64.urlsafe_b64encode(b).decode().rstrip('=')
        return f"uEi{b64_hash}"


# Register WebRTC protocols with multiaddr
try:

    # Create codec instances
    webrtc_codec = WebRTCCodec()
    webrtc_direct_codec = WebRTCDirectCodec()
    certhash_codec = CerthashCodec()

    # Register codec modules for multiaddr
    sys.modules['multiaddr.codecs.webrtc'] = webrtc_codec  # type: ignore
    sys.modules['multiaddr.codecs.webrtc_direct'] = webrtc_direct_codec  # type: ignore
    sys.modules['multiaddr.codecs.certhash'] = certhash_codec  # type: ignore

    setattr(codecs, 'webrtc', webrtc_codec)
    setattr(codecs, 'webrtc_direct', webrtc_direct_codec)
    setattr(codecs, 'certhash', certhash_codec)

    # Create Protocol objects with string codec names
    webrtc_protocol = Protocol(
        code=CODEC_WEBRTC,
        name=PROTOCOL_WEBRTC,
        codec="webrtc"
    )

    webrtc_direct_protocol = Protocol(
        code=CODEC_WEBRTC_DIRECT,
        name=PROTOCOL_WEBRTC_DIRECT,
        codec="webrtc_direct"
    )

    certhash_protocol = Protocol(
        code=CODEC_CERTHASH,
        name=PROTOCOL_CERTHASH,
        codec="certhash"
    )

    # Register protocols using the add_protocol function
    protocols.add_protocol(webrtc_protocol)
    protocols.add_protocol(webrtc_direct_protocol)
    protocols.add_protocol(certhash_protocol)

    print("✅ WebRTC protocols registered with multiaddr")

except ImportError as e:
    print(f"⚠️ Failed to register WebRTC protocols: {e}")
except Exception as e:
    print(f"⚠️ Error registering WebRTC protocols: {e}")

__all__ = [
    "WebRTCTransport",
    "WebRTCDirectTransport",
    "DEFAULT_ICE_SERVERS",
    "SIGNALING_PROTOCOL",
    "MUXER_PROTOCOL",
    "WebRTCError",
    "SDPHandshakeError",
    "ConnectionStateError",
    "CertificateError",
    "STUNError",
    "CODEC_WEBRTC",
    "CODEC_WEBRTC_DIRECT",
    "CODEC_CERTHASH",
]


def webrtc(config: dict[str, Any] | None = None) -> WebRTCTransport:
    """Create a WebRTC transport instance (private-to-private)."""
    return WebRTCTransport(config)


def webrtc_direct() -> "WebRTCDirectTransport":
    """Create a WebRTC-Direct transport instance (private-to-public)."""
    from .private_to_public.transport import WebRTCDirectTransport

    return WebRTCDirectTransport()
