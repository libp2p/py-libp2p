"""
Synchronous persistent peerstore implementation.

This module provides a fully synchronous persistent peerstore implementation
that stores peer data in various datastore backends without any async operations.
"""

from .peerstore import SyncPersistentPeerStore

__all__ = [
    "SyncPersistentPeerStore",
]
