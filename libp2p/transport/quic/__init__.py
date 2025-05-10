"""
QUIC transport implementation for libp2p.

This module provides QUIC transport functionality for libp2p, enabling
high-performance, secure communication between peers using the QUIC protocol.
"""

from libp2p.transport.quic.transport import (
    Libp2pQuicProtocol,
    QuicTransport,
)

__all__ = [
    "QuicTransport",
    "Libp2pQuicProtocol",
]
