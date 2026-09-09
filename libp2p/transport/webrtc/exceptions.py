"""
WebRTC transport exception hierarchy.

``WebRTCConnectionError`` also subclasses :class:`OpenConnectionError` so that
generic transport error handling in the swarm layer catches WebRTC dial
failures the same way it catches TCP/QUIC failures.
"""

from libp2p.exceptions import BaseLibp2pError
from libp2p.transport.exceptions import OpenConnectionError


class WebRTCError(BaseLibp2pError):
    """Base exception for all WebRTC transport errors."""


class WebRTCCertificateError(WebRTCError):
    """Certificate generation, parsing, or fingerprint errors."""


class WebRTCMultiaddrError(WebRTCError):
    """Invalid or unparseable WebRTC multiaddr."""


class WebRTCHandshakeError(WebRTCError):
    """Noise handshake failure over data-channel 0."""


class WebRTCConnectionError(WebRTCError, OpenConnectionError):
    """ICE negotiation, DTLS, or peer connection failure."""


class WebRTCStreamError(WebRTCError):
    """Data-channel stream read/write or lifecycle error."""


class WebRTCSignalingError(WebRTCError):
    """SDP/ICE signaling exchange failure (private-to-private mode)."""
