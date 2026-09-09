"""
Rendezvous protocol implementation for py-libp2p.

This module provides both client and server implementations of the rendezvous
protocol, allowing peers to advertise themselves and discover other peers
through a centralized rendezvous point.
"""

from .client import RendezvousClient
from .discovery import RendezvousDiscovery
from .service import RendezvousService
from . import config
from .errors import (
    RendezvousError,
    InvalidNamespaceError,
    InvalidPeerInfoError,
    InvalidTTLError,
    InvalidCookieError,
    NotAuthorizedError,
    InternalError,
    UnavailableError,
)

__all__ = [
    "RendezvousClient",
    "RendezvousDiscovery",
    "RendezvousService",
    "config",
    "RendezvousError",
    "InvalidNamespaceError",
    "InvalidPeerInfoError",
    "InvalidTTLError",
    "InvalidCookieError",
    "NotAuthorizedError",
    "InternalError",
    "UnavailableError",
]
