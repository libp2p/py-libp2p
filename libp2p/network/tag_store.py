"""
Connection tagging system for py-libp2p.

This module provides peer tagging functionality similar to go-libp2p's ConnManager.
Tags allow different parts of the system to assign numerical values to peers,
which influences connection pruning decisions.

Reference: https://pkg.go.dev/github.com/libp2p/go-libp2p/core/connmgr
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.network.tag_store")


# Common tag names used across libp2p
class CommonTags:
    """Common tag names used throughout libp2p."""

    # High-priority connections
    KEEP_ALIVE = "keep-alive"
    BOOTSTRAP = "bootstrap"
    RELAY = "relay"
    DHT = "dht"

    # Protocol-specific tags
    PUBSUB = "pubsub"
    BITSWAP = "bitswap"

    # Application tags
    APPLICATION = "application"

    # Stream-based tags
    ACTIVE_STREAMS = "active-streams"


@dataclass
class TagInfo:
    """
    Metadata associated with a peer for connection management.

    This matches the go-libp2p TagInfo struct.

    Attributes
    ----------
    first_seen : float
        Unix timestamp when this peer was first seen.
    value : int
        Total aggregated tag value for this peer.
    tags : dict[str, int]
        Individual tag names mapped to their values.
    conns : dict[str, float]
        Connection identifiers mapped to their creation time.

    """

    first_seen: float = field(default_factory=time.time)
    value: int = 0
    tags: dict[str, int] = field(default_factory=dict)
    conns: dict[str, float] = field(default_factory=dict)

    def get_total_value(self) -> int:
        """
        Calculate total value from all tags.

        Returns
        -------
        int
            Sum of all tag values.

        """
        return sum(self.tags.values())

    def to_dict(self) -> dict[str, Any]:
        """
        Convert TagInfo to dictionary for serialization.

        Returns
        -------
        dict
            Dictionary representation of the tag info.

        """
        return {
            "first_seen": self.first_seen,
            "value": self.value,
            "tags": self.tags.copy(),
            "conns": self.conns.copy(),
        }


class TagStore:
    """
    Thread-safe store for peer tags.

    The TagStore manages tags for peers, allowing different components
    to assign importance values that influence connection pruning.

    Similar to go-libp2p's ConnManager tagging functionality.
    """

    def __init__(self) -> None:
        """Initialize the tag store."""
        self._tags: dict[ID, TagInfo] = defaultdict(TagInfo)
        self._protected: dict[ID, set[str]] = defaultdict(set)
        self._lock = threading.RLock()

    def tag_peer(self, peer_id: ID, tag: str, value: int) -> None:
        """
        Tag a peer with a string, associating a weight with the tag.

        If the tag already exists, it will be overwritten with the new value.

        Parameters
        ----------
        peer_id : ID
            The peer to tag.
        tag : str
            The tag name.
        value : int
            The weight/value associated with the tag.

        """
        with self._lock:
            tag_info = self._tags[peer_id]
            old_value = tag_info.tags.get(tag, 0)
            tag_info.tags[tag] = value
            tag_info.value += value - old_value
            logger.debug(f"Tagged peer {peer_id} with {tag}={value}")

    def untag_peer(self, peer_id: ID, tag: str) -> None:
        """
        Remove the tagged value from the peer.

        Parameters
        ----------
        peer_id : ID
            The peer to untag.
        tag : str
            The tag name to remove.

        """
        with self._lock:
            if peer_id in self._tags:
                tag_info = self._tags[peer_id]
                if tag in tag_info.tags:
                    value = tag_info.tags.pop(tag)
                    tag_info.value -= value
                    logger.debug(f"Untagged peer {peer_id}, removed {tag}")

    def upsert_tag(
        self,
        peer_id: ID,
        tag: str,
        upsert_fn: Callable[[int], int],
    ) -> None:
        """
        Update an existing tag or insert a new one.

        The upsert function is called with the current value of the tag
        (or zero if it doesn't exist). The return value becomes the new
        value of the tag.

        Parameters
        ----------
        peer_id : ID
            The peer to tag.
        tag : str
            The tag name.
        upsert_fn : Callable[[int], int]
            Function that takes current value and returns new value.

        """
        with self._lock:
            tag_info = self._tags[peer_id]
            current_value = tag_info.tags.get(tag, 0)
            new_value = upsert_fn(current_value)
            tag_info.tags[tag] = new_value
            tag_info.value += new_value - current_value
            logger.debug(f"Upserted tag {tag} for peer {peer_id}: {new_value}")

    def get_tag_info(self, peer_id: ID) -> TagInfo | None:
        """
        Get the metadata associated with a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to get info for.

        Returns
        -------
        TagInfo | None
            The tag info for the peer, or None if no tags recorded.

        """
        with self._lock:
            if peer_id in self._tags:
                return self._tags[peer_id]
            return None

    def get_tag_value(self, peer_id: ID) -> int:
        """
        Get the total tag value for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to get value for.

        Returns
        -------
        int
            Total tag value (sum of all tags), or 0 if not found.

        """
        with self._lock:
            if peer_id in self._tags:
                return self._tags[peer_id].value
            return 0

    def get_tag(self, peer_id: ID, tag: str) -> int:
        """
        Get a specific tag value for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to get tag for.
        tag : str
            The tag name.

        Returns
        -------
        int
            The tag value, or 0 if not found.

        """
        with self._lock:
            if peer_id in self._tags:
                return self._tags[peer_id].tags.get(tag, 0)
            return 0

    def protect(self, peer_id: ID, tag: str) -> None:
        """
        Protect a peer from having its connection(s) pruned.

        Tagging allows different parts of the system to manage protections
        without interfering with one another.

        Calls to Protect() with the same tag are idempotent.

        Parameters
        ----------
        peer_id : ID
            The peer to protect.
        tag : str
            Protection tag (different components can use different tags).

        """
        with self._lock:
            self._protected[peer_id].add(tag)
            logger.debug(f"Protected peer {peer_id} with tag {tag}")

    def unprotect(self, peer_id: ID, tag: str) -> bool:
        """
        Remove a protection that may have been placed on a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to unprotect.
        tag : str
            The protection tag to remove.

        Returns
        -------
        bool
            True if the peer is still protected by other tags, False otherwise.

        """
        with self._lock:
            if peer_id in self._protected:
                self._protected[peer_id].discard(tag)
                if not self._protected[peer_id]:
                    del self._protected[peer_id]
                    logger.debug(f"Peer {peer_id} is no longer protected")
                    return False
                logger.debug(
                    f"Removed protection tag {tag} from peer {peer_id}, "
                    f"still protected by: {self._protected[peer_id]}"
                )
                return True
            return False

    def is_protected(self, peer_id: ID, tag: str = "") -> bool:
        """
        Check if a peer is protected.

        Parameters
        ----------
        peer_id : ID
            The peer to check.
        tag : str
            If provided, check if protected by this specific tag.
            If empty string, check if protected by any tag.

        Returns
        -------
        bool
            True if the peer is protected.

        """
        with self._lock:
            if peer_id not in self._protected:
                return False
            if tag == "":
                return len(self._protected[peer_id]) > 0
            return tag in self._protected[peer_id]

    def record_connection(self, peer_id: ID, conn_id: str) -> None:
        """
        Record a new connection for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer that connected.
        conn_id : str
            Identifier for the connection (e.g., remote multiaddr).

        """
        with self._lock:
            tag_info = self._tags[peer_id]
            if tag_info.first_seen == 0:
                tag_info.first_seen = time.time()
            tag_info.conns[conn_id] = time.time()

    def remove_connection(self, peer_id: ID, conn_id: str) -> None:
        """
        Remove a connection record for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer that disconnected.
        conn_id : str
            Identifier for the connection.

        """
        with self._lock:
            if peer_id in self._tags:
                self._tags[peer_id].conns.pop(conn_id, None)

    def clear_peer(self, peer_id: ID) -> None:
        """
        Clear all tag data for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to clear.

        """
        with self._lock:
            self._tags.pop(peer_id, None)
            self._protected.pop(peer_id, None)
            logger.debug(f"Cleared all tag data for peer {peer_id}")

    def get_all_peers(self) -> list[ID]:
        """
        Get all peers with tags.

        Returns
        -------
        list[ID]
            List of all peer IDs with tags.

        """
        with self._lock:
            return list(self._tags.keys())

    def get_protected_peers(self) -> list[ID]:
        """
        Get all protected peers.

        Returns
        -------
        list[ID]
            List of all protected peer IDs.

        """
        with self._lock:
            return list(self._protected.keys())


# Upsert helper functions (similar to go-libp2p's BumpFn presets)


def upsert_add(delta: int) -> Callable[[int], int]:
    """
    Create an upsert function that adds a delta to the current value.

    Parameters
    ----------
    delta : int
        The value to add.

    Returns
    -------
    Callable[[int], int]
        Upsert function.

    """
    return lambda current: current + delta


def upsert_set(value: int) -> Callable[[int], int]:
    """
    Create an upsert function that sets a specific value.

    Parameters
    ----------
    value : int
        The value to set.

    Returns
    -------
    Callable[[int], int]
        Upsert function.

    """
    return lambda _: value


def upsert_bounded(delta: int, min_val: int, max_val: int) -> Callable[[int], int]:
    """
    Create an upsert function that adds a delta but keeps within bounds.

    Parameters
    ----------
    delta : int
        The value to add.
    min_val : int
        Minimum allowed value.
    max_val : int
        Maximum allowed value.

    Returns
    -------
    Callable[[int], int]
        Upsert function.

    """
    return lambda current: max(min_val, min(max_val, current + delta))
