"""
QUIC transport implementation for libp2p.

This module provides QUIC transport functionality for libp2p, enabling
high-performance, secure communication between peers using the QUIC protocol.
"""

# Avoid importing Libp2pQuicProtocol to prevent circular dependencies

from .transport import (
    QuicTransport,
)

__all__ = [
    "QuicTransport",
]
