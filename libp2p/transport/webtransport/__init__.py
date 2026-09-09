"""
WebTransport transport for libp2p.

HTTP/3 WebTransport (ALPN ``h3``) with Noise XX on the first client-opened
stream and dual self-signed certificate rotation.

Spec: https://github.com/libp2p/specs/blob/master/webtransport/README.md
"""

from libp2p.transport.webtransport.certificate import (
    WebTransportCertificate,
    fingerprint_from_multibase,
    multihash_from_der,
    multihash_from_multibase,
)
from libp2p.transport.webtransport.cert_manager import WebTransportCertManager
from libp2p.transport.webtransport.config import WELL_KNOWN_PATH, WebTransportConfig
from libp2p.transport.webtransport.exceptions import (
    WebTransportCertificateError,
    WebTransportConnectionError,
    WebTransportError,
    WebTransportHandshakeError,
    WebTransportMultiaddrError,
    WebTransportStreamError,
)
from libp2p.transport.webtransport.multiaddr_utils import (
    build_webtransport_multiaddr,
    extract_certhashes,
    is_webtransport_multiaddr,
    parse_webtransport_multiaddr,
)
from libp2p.transport.webtransport.transport import WebTransportTransport

__all__ = [
    "WELL_KNOWN_PATH",
    "WebTransportCertificate",
    "WebTransportCertManager",
    "WebTransportConfig",
    "WebTransportCertificateError",
    "WebTransportConnectionError",
    "WebTransportError",
    "WebTransportHandshakeError",
    "WebTransportMultiaddrError",
    "WebTransportStreamError",
    "WebTransportTransport",
    "build_webtransport_multiaddr",
    "extract_certhashes",
    "fingerprint_from_multibase",
    "is_webtransport_multiaddr",
    "multihash_from_der",
    "multihash_from_multibase",
    "parse_webtransport_multiaddr",
]
