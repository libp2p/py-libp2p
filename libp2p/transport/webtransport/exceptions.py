"""
WebTransport transport exception hierarchy.
"""

from libp2p.exceptions import BaseLibp2pError
from libp2p.transport.exceptions import OpenConnectionError


class WebTransportError(BaseLibp2pError):
    """Base exception for all WebTransport transport errors."""


class WebTransportCertificateError(WebTransportError):
    """Certificate generation, parsing, or fingerprint errors."""


class WebTransportMultiaddrError(WebTransportError):
    """Invalid or unparseable WebTransport multiaddr."""


class WebTransportHandshakeError(WebTransportError):
    """Noise handshake or certhash verification failure."""


class WebTransportConnectionError(WebTransportError, OpenConnectionError):
    """QUIC / HTTP/3 / WebTransport session failure."""


class WebTransportStreamError(WebTransportError):
    """WebTransport stream read/write or lifecycle error."""
