"""
Network layer for libp2p.

This package provides connection management, dial queue, reconnection,
rate limiting, address management, DNS resolution, and tagging functionality.
"""

from libp2p.network.auto_connector import AutoConnector
from libp2p.network.connection_pruner import ConnectionPruner
from libp2p.network.tag_store import (
    CommonTags,
    TagInfo,
    TagStore,
    upsert_add,
    upsert_bounded,
    upsert_set,
)

__all__ = [
    "AutoConnector",
    "CommonTags",
    "ConnectionPruner",
    "TagInfo",
    "TagStore",
    "upsert_add",
    "upsert_bounded",
    "upsert_set",
]
