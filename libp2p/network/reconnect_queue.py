"""
Reconnection queue implementation with KEEP_ALIVE support.

This module provides automatic reconnection for peers tagged with KEEP_ALIVE,
matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/reconnect-queue.ts
"""

from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING

import trio

from libp2p.abc import IPeerStore
from libp2p.network.config import (
    MAX_PARALLEL_RECONNECTS,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_RETRIES,
    RECONNECT_RETRY_INTERVAL,
)
from libp2p.peer.id import ID

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.network.reconnect_queue")

# KEEP_ALIVE tag prefix matching JS libp2p
KEEP_ALIVE = "keep-alive"

# Metadata key for tracking KEEP_ALIVE status (until tags are implemented)
KEEP_ALIVE_METADATA_KEY = "_keep_alive_tag"


def has_keep_alive_tag(peer_store: IPeerStore, peer_id: ID) -> bool:
    """
    Check if peer has KEEP_ALIVE tag.

    Parameters
    ----------
    peer_store : IPeerStore
        Peer store to check
    peer_id : ID
        Peer ID to check

    Returns
    -------
    bool
        True if peer has KEEP_ALIVE tag

    """
    try:
        # Access peer_data_map - it exists on PeerStore implementation
        peer_data_map = getattr(peer_store, "peer_data_map", None)
        if peer_data_map is None:
            return False
        peer_data = peer_data_map.get(peer_id)
        if peer_data is None:
            return False

        # Check metadata for KEEP_ALIVE (temporary until tags are implemented)
        # TODO: Replace with proper tags support when peer tags are implemented
        if hasattr(peer_data, "metadata") and peer_data.metadata:
            keep_alive_value = peer_data.metadata.get(KEEP_ALIVE_METADATA_KEY)
            if keep_alive_value is not None:
                return True

            # Also check for any metadata key starting with "keep-alive"
            for key in peer_data.metadata.keys():
                if isinstance(key, str) and key.startswith(KEEP_ALIVE):
                    return True

        return False
    except Exception:
        return False


@dataclass
class ReconnectJob:
    """Represents a reconnection job in the queue."""

    peer_id: ID
    attempt: int = 0
    next_retry_at: float = 0.0
    cancel_scope: trio.CancelScope | None = None


class ReconnectQueue:
    """
    Reconnection queue for peers tagged with KEEP_ALIVE.

    Automatically attempts to reconnect to peers that disconnect,
    using exponential backoff for retry attempts.
    """

    def __init__(
        self,
        swarm: "Swarm",
        retries: int = RECONNECT_RETRIES,
        retry_interval: float = RECONNECT_RETRY_INTERVAL,
        backoff_factor: float = RECONNECT_BACKOFF_FACTOR,
        max_parallel_reconnects: int = MAX_PARALLEL_RECONNECTS,
    ):
        """
        Initialize reconnection queue.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance for reconnecting
        retries : int
            Maximum number of reconnection attempts
        retry_interval : float
            Initial delay between retry attempts (seconds)
        backoff_factor : float
            Exponential backoff factor
        max_parallel_reconnects : int
            Maximum concurrent reconnection attempts

        """
        self.swarm = swarm
        self.retries = retries
        self.retry_interval = retry_interval
        self.backoff_factor = backoff_factor
        self.max_parallel_reconnects = max_parallel_reconnects

        # Track reconnection jobs
        self._reconnect_jobs: dict[ID, ReconnectJob] = {}
        self._running_reconnects: set[ID] = set()
        self._jobs_lock = trio.Lock()
        self._running_lock = trio.Lock()

        self._started = False
        self._shutdown_event = trio.Event()

    async def start(self) -> None:
        """Start the reconnection queue."""
        self._started = True
        self._shutdown_event = trio.Event()

        # Reconnect to any existing KEEP_ALIVE peers
        await self._reconnect_keep_alive_peers()

    async def stop(self) -> None:
        """Stop the reconnection queue and cancel all pending reconnects."""
        self._started = False
        self._shutdown_event.set()

        # Cancel all running and pending reconnects
        async with self._running_lock:
            for peer_id in list(self._running_reconnects):
                job = self._reconnect_jobs.get(peer_id)
                if job and job.cancel_scope:
                    job.cancel_scope.cancel()

        async with self._jobs_lock:
            self._reconnect_jobs.clear()

        self._running_reconnects.clear()

    async def maybe_reconnect(self, peer_id: ID) -> None:
        """
        Check if peer should be reconnected and add to queue if needed.

        Parameters
        ----------
        peer_id : ID
            Peer that disconnected

        """
        if not self._started:
            return

        # Check if peer has KEEP_ALIVE tag
        if not has_keep_alive_tag(self.swarm.peerstore, peer_id):
            return

        async with self._jobs_lock:
            # Check if already reconnecting
            if peer_id in self._reconnect_jobs:
                return

            # Create new reconnection job
            job = ReconnectJob(
                peer_id=peer_id,
                attempt=0,
                next_retry_at=time.time() + self.retry_interval,
            )
            self._reconnect_jobs[peer_id] = job

        # Start reconnection process
        await self._process_reconnect(peer_id)

    async def _process_reconnect(self, peer_id: ID) -> None:
        """Process a reconnection attempt."""
        async with self._running_lock:
            if len(self._running_reconnects) >= self.max_parallel_reconnects:
                # Will be processed later when slot becomes available
                return

            if peer_id in self._running_reconnects:
                return

            self._running_reconnects.add(peer_id)

        job = None
        async with self._jobs_lock:
            job = self._reconnect_jobs.get(peer_id)

        if not job:
            async with self._running_lock:
                self._running_reconnects.discard(peer_id)
            return

        # Wait until next retry time
        current_time = time.time()
        if job.next_retry_at > current_time:
            wait_time = job.next_retry_at - current_time
            try:
                await trio.sleep(wait_time)
            except trio.Cancelled:
                async with self._running_lock:
                    self._running_reconnects.discard(peer_id)
                async with self._jobs_lock:
                    self._reconnect_jobs.pop(peer_id, None)
                return

        # Attempt reconnection
        if not self._started:
            async with self._running_lock:
                self._running_reconnects.discard(peer_id)
            return

        cancel_scope = trio.CancelScope()
        job.cancel_scope = cancel_scope

        try:
            with cancel_scope:
                logger.debug(
                    f"Reconnecting to {peer_id} attempt "
                    f"{job.attempt + 1} of {self.retries}"
                )

                # Attempt to dial peer
                connections = await self.swarm.dial_peer(peer_id)
                if connections:
                    logger.info(f"Successfully reconnected to {peer_id}")
                    # Remove from queue on success
                    async with self._jobs_lock:
                        self._reconnect_jobs.pop(peer_id, None)
                    async with self._running_lock:
                        self._running_reconnects.discard(peer_id)
                    return

        except Exception as e:
            logger.debug(
                f"Reconnection attempt {job.attempt + 1} failed for {peer_id}: {e}"
            )

            # Check if we should retry
            job.attempt += 1
            if job.attempt >= self.retries:
                # Max retries reached - remove KEEP_ALIVE tag
                logger.warning(
                    f"Max reconnection attempts ({self.retries}) reached "
                    f"for {peer_id}, removing KEEP_ALIVE tag"
                )
                await self._remove_keep_alive_tag(peer_id)
                async with self._jobs_lock:
                    self._reconnect_jobs.pop(peer_id, None)
                async with self._running_lock:
                    self._running_reconnects.discard(peer_id)
                return

            # Calculate next retry time with exponential backoff
            delay = self.retry_interval * (self.backoff_factor**job.attempt)
            job.next_retry_at = time.time() + delay

            # Try again later (schedule retry)
            try:
                if hasattr(self.swarm, "manager") and self.swarm.manager is not None:
                    self.swarm.manager.run_task(self._process_reconnect, peer_id)
                else:
                    # Manager not available - spawn using trio directly
                    trio.lowlevel.spawn_system_task(self._process_reconnect, peer_id)
            except AttributeError:
                # Fallback if manager not available
                trio.lowlevel.spawn_system_task(self._process_reconnect, peer_id)

        finally:
            async with self._running_lock:
                self._running_reconnects.discard(peer_id)

    async def _remove_keep_alive_tag(self, peer_id: ID) -> None:
        """
        Remove KEEP_ALIVE tag from peer when reconnection fails.

        Parameters
        ----------
        peer_id : ID
            Peer to remove tag from

        """
        try:
            # Access peer_data_map - it exists on PeerStore implementation
            peer_data_map = getattr(self.swarm.peerstore, "peer_data_map", None)
            if peer_data_map is None:
                return
            peer_data = peer_data_map.get(peer_id)
            if peer_data and hasattr(peer_data, "metadata"):
                # Remove KEEP_ALIVE metadata
                # TODO: Replace with proper tags removal when tags are implemented
                keys_to_remove = [
                    key
                    for key in peer_data.metadata.keys()
                    if isinstance(key, str) and key.startswith(KEEP_ALIVE)
                ]
                for key in keys_to_remove:
                    peer_data.metadata.pop(key, None)
        except Exception as e:
            logger.error(f"Failed to remove KEEP_ALIVE tag from {peer_id}: {e}")

    async def _reconnect_keep_alive_peers(self) -> None:
        """Reconnect to all peers with KEEP_ALIVE tag on startup."""
        try:
            # Get all peers from peer store
            peer_ids = self.swarm.peerstore.peer_ids()

            keep_alive_peers = [
                peer_id
                for peer_id in peer_ids
                if has_keep_alive_tag(self.swarm.peerstore, peer_id)
            ]

            logger.debug(
                f"Found {len(keep_alive_peers)} peers with KEEP_ALIVE tag, "
                f"attempting to reconnect"
            )

            # Attempt to reconnect to each (don't wait for all to complete)
            for peer_id in keep_alive_peers:
                try:
                    # Check if already connected
                    existing = self.swarm.get_connections(peer_id)
                    if existing:
                        continue

                    # Attempt connection
                    await self.swarm.dial_peer(peer_id)
                except Exception as e:
                    logger.error(
                        f"Could not reconnect to KEEP_ALIVE peer {peer_id}: {e}"
                    )
        except Exception as e:
            logger.error(f"Error reconnecting to KEEP_ALIVE peers: {e}")
