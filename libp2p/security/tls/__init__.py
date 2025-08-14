"""
TLS security transport for libp2p.

This module provides a comprehensive TLS transport implementation
that follows the Go libp2p TLS specification.
"""

from libp2p.security.tls.transport import (
    TLSTransport,
    IdentityConfig,
    create_tls_transport,
    PROTOCOL_ID,
)
from libp2p.security.tls.io import TLSReadWriter
from libp2p.security.tls.certificate import (
    generate_certificate,
    create_cert_template,
    verify_certificate_chain,
    pub_key_from_cert_chain,
    SignedKey,
    ALPN_PROTOCOL
)

__all__ = [
    "TLSTransport",
    "IdentityConfig",
    "TLSReadWriter",
    "create_tls_transport",
    "generate_certificate",
    "create_cert_template",
    "verify_certificate_chain",
    "pub_key_from_cert_chain",
    "SignedKey",
    "PROTOCOL_ID",
    "ALPN_PROTOCOL"
]
