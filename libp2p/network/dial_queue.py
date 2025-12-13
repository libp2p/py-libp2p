"""
Dial queue implementation with priority scheduling.

This module provides a priority-based dial queue matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/dial-queue.ts
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import heapq
import logging
import time
from typing import TYPE_CHECKING

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver
import trio

from libp2p.abc import INetConn
from libp2p.network.address_manager import AddressManager
from libp2p.network.config import (
    DEFAULT_DIAL_PRIORITY,
    MAX_DIAL_QUEUE_LENGTH,
    MAX_PARALLEL_DIALS,
)
from libp2p.peer.id import ID

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.network.dial_queue")


@dataclass
class DialJob:
    """Represents a dial job in the queue."""

    priority: int = DEFAULT_DIAL_PRIORITY
    peer_id: ID | None = None
    multiaddrs: set[str] = field(default_factory=set)
    job_id: int = field(default_factory=lambda: id(object()))
    # Send channel for result/exception
    send_channel: trio.MemorySendChannel[INetConn | BaseException] | None = None
    # Receive channel for waiting on result
    receive_channel: trio.MemoryReceiveChannel[INetConn | BaseException] | None = None
    # Cancel scope for the job
    cancel_scope: trio.CancelScope | None = None
    # Job function
    fn: Callable[[], Awaitable[INetConn]] | None = None
    # Whether job is currently running
    running: bool = False
    # Timestamp when job was added
    added_at: float = field(default_factory=time.time)

    def __lt__(self, other: "DialJob") -> bool:
        """Compare jobs by priority (higher = lower value for heapq min-heap)."""
        # Invert priority comparison: higher priority comes first
        if self.priority != other.priority:
            return self.priority > other.priority
        # FIFO within same priority
        return self.added_at < other.added_at


class DialQueue:
    """
    Priority-based dial queue for connection management.

    Provides priority scheduling, concurrency control, and deduplication
    matching JavaScript libp2p dial queue behavior.
    """

    def __init__(
        self,
        swarm: "Swarm",
        max_parallel_dials: int = MAX_PARALLEL_DIALS,
        max_dial_queue_length: int = MAX_DIAL_QUEUE_LENGTH,
        dial_timeout: float = 10.0,
        address_manager: AddressManager | None = None,
        dns_resolver: DNSResolver | None = None,
    ):
        """
        Initialize dial queue.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance for dialing
        max_parallel_dials : int
            Maximum concurrent dial attempts
        max_dial_queue_length : int
            Maximum queue size before rejecting new dials
        dial_timeout : float
            Default timeout for dial operations (seconds)
        address_manager : AddressManager | None
            Address manager for sorting and filtering addresses
        dns_resolver : DNSResolver | None
            DNS resolver for resolving DNS addresses

        """
        self.swarm = swarm
        self.max_parallel_dials = max_parallel_dials
        self.max_dial_queue_length = max_dial_queue_length
        self.dial_timeout = dial_timeout

        # Address management
        self.address_manager = address_manager or AddressManager()
        self.dns_resolver = dns_resolver or DNSResolver()

        # Priority queue (min-heap) - lower values = higher priority
        self._queue: list[DialJob] = []
        self._queue_lock = trio.Lock()

        # Track running jobs
        self._running_jobs: set[DialJob] = set()
        self._running_lock = trio.Lock()

        # Job counter for unique IDs
        self._job_counter = 0
        self._shutdown_event = trio.Event()
        self._started = False

    async def start(self) -> None:
        """Start the dial queue."""
        self._started = True
        self._shutdown_event = trio.Event()

    async def stop(self) -> None:
        """Stop the dial queue and cancel all pending jobs."""
        self._started = False
        self._shutdown_event.set()

        # Cancel all running and queued jobs
        async with self._running_lock:
            for job in list(self._running_jobs):
                if job.cancel_scope:
                    job.cancel_scope.cancel()

        async with self._queue_lock:
            for job in self._queue:
                if job.send_channel:
                    try:
                        # Send cancellation - raise Cancelled exception
                        await job.send_channel.send(RuntimeError("Queue shutdown"))
                    except Exception:
                        pass

        self._queue.clear()
        self._running_jobs.clear()

    async def dial(
        self,
        peer_id_or_multiaddr: ID | Multiaddr | list[Multiaddr],
        priority: int = DEFAULT_DIAL_PRIORITY,
        signal: trio.CancelScope | None = None,
    ) -> INetConn:
        """
        Add a dial request to the queue.

        Parameters
        ----------
        peer_id_or_multiaddr : ID | Multiaddr | list[Multiaddr]
            Target peer ID, multiaddr, or list of multiaddrs
        priority : int
            Dial priority (higher = processed first, default: 50)
        signal : trio.CancelScope | None
            Cancel scope for cancellation

        Returns
        -------
        INetConn
            The established connection

        Raises
        ------
        RuntimeError
            If queue is full or not started

        """
        if not self._started:
            raise RuntimeError("Dial queue not started")

        # Convert peer_id_or_multiaddr to peer_id and multiaddrs
        peer_id: ID | None = None
        multiaddrs: list[Multiaddr] = []

        if isinstance(peer_id_or_multiaddr, ID):
            peer_id = peer_id_or_multiaddr
            # Get addresses from peer store
            try:
                addrs = self.swarm.peerstore.addrs(peer_id)
                multiaddrs = list(addrs) if addrs else []
            except Exception:
                multiaddrs = []
        elif isinstance(peer_id_or_multiaddr, Multiaddr):
            multiaddrs = [peer_id_or_multiaddr]
            # Extract peer ID from multiaddr if present
            peer_id_str = peer_id_or_multiaddr.value_for_protocol("p2p")
            if peer_id_str:
                try:
                    peer_id = ID.from_base58(peer_id_str)
                except Exception:
                    pass
        elif isinstance(peer_id_or_multiaddr, list):
            multiaddrs = peer_id_or_multiaddr
            # Try to extract peer ID from first multiaddr
            if multiaddrs:
                peer_id_str = multiaddrs[0].value_for_protocol("p2p")
                if peer_id_str:
                    try:
                        peer_id = ID.from_base58(peer_id_str)
                    except Exception:
                        pass

        multiaddr_strings = {str(ma) for ma in multiaddrs}

        # Check for existing connection
        if peer_id:
            existing_conns = self.swarm.get_connections(peer_id)
            if existing_conns:
                logger.debug(f"Already connected to {peer_id}, reusing connection")
                return existing_conns[0]

        # Check for existing dial in queue
        async with self._queue_lock:
            existing_job = self._find_existing_dial(peer_id, multiaddr_strings)

            if existing_job:
                logger.debug(
                    f"Joining existing dial for peer {peer_id}",
                )
                # Add multiaddrs to existing job
                existing_job.multiaddrs.update(multiaddr_strings)
                # Return existing job result
                if existing_job.receive_channel:
                    result = await existing_job.receive_channel.receive()
                    if isinstance(result, BaseException):
                        raise result
                    return result

        # Check queue size
        async with self._queue_lock:
            if len(self._queue) >= self.max_dial_queue_length:
                raise RuntimeError("Dial queue is full")

            # Create new job with channel for result
            self._job_counter += 1
            send_channel, receive_channel = trio.open_memory_channel[
                INetConn | BaseException
            ](1)

            job = DialJob(
                priority=priority,
                peer_id=peer_id,
                multiaddrs=multiaddr_strings,
                job_id=self._job_counter,
                send_channel=send_channel,
                receive_channel=receive_channel,
                fn=lambda: self._execute_dial(peer_id, multiaddrs, signal),
            )

            heapq.heappush(self._queue, job)
            logger.debug(
                f"Added dial job {job.job_id} for peer {peer_id} "
                f"with priority {priority}"
            )

        # Start processing
        await self._process_queue()

        # Wait for result
        if job.receive_channel:
            result = await job.receive_channel.receive()
            if isinstance(result, BaseException):
                raise result
            return result

        raise RuntimeError("Job channel not initialized")

    def _find_existing_dial(
        self, peer_id: ID | None, multiaddr_strings: set[str]
    ) -> DialJob | None:
        """Find existing dial job for the same peer or multiaddrs."""
        for job in self._queue + list(self._running_jobs):
            if job.running:
                continue

            # Match by peer ID
            if peer_id and job.peer_id and peer_id == job.peer_id:
                return job

            # Match by multiaddr
            if multiaddr_strings.intersection(job.multiaddrs):
                return job

        return None

    async def _process_queue(self) -> None:
        """Process the dial queue, starting jobs up to concurrency limit."""
        async with self._running_lock:
            # Check if we can start more jobs
            if len(self._running_jobs) >= self.max_parallel_dials:
                return

            # Start jobs from queue
            async with self._queue_lock:
                while self._queue and len(self._running_jobs) < self.max_parallel_dials:
                    job = heapq.heappop(self._queue)
                    self._running_jobs.add(job)
                    job.running = True

                    # Start job in background
                    # (manager should be available when queue is started)
                    try:
                        if (
                            hasattr(self.swarm, "manager")
                            and self.swarm.manager is not None
                        ):
                            self.swarm.manager.run_task(self._run_job, job)
                        else:
                            # Manager not available yet - spawn using trio directly
                            trio.lowlevel.spawn_system_task(self._run_job, job)
                    except AttributeError:
                        # Fallback to trio spawn if manager not available
                        trio.lowlevel.spawn_system_task(self._run_job, job)

    async def _run_job(self, job: DialJob) -> None:
        """Run a dial job."""
        if not job.fn or not job.send_channel:
            return

        # Create cancel scope
        cancel_scope = trio.CancelScope()
        job.cancel_scope = cancel_scope

        try:
            with cancel_scope:
                connection = await job.fn()
                if job.send_channel:
                    await job.send_channel.send(connection)
        except trio.Cancelled:
            if job.send_channel:
                try:
                    # Send cancellation error
                    await job.send_channel.send(RuntimeError("Dial job cancelled"))
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Dial job {job.job_id} failed: {e}")
            if job.send_channel:
                try:
                    await job.send_channel.send(e)
                except Exception:
                    pass
        finally:
            # Remove from running jobs
            async with self._running_lock:
                self._running_jobs.discard(job)
                job.running = False

            # Close send channel
            if job.send_channel:
                await job.send_channel.aclose()

            # Process next item in queue
            await self._process_queue()

    async def _execute_dial(
        self,
        peer_id: ID | None,
        multiaddrs: list[Multiaddr],
        signal: trio.CancelScope | None,
    ) -> INetConn:
        """
        Execute the actual dial operation.

        This calls swarm's internal dial methods directly to avoid recursion.
        """
        if self._shutdown_event.is_set():
            raise RuntimeError("Dial queue shutdown")

        # Call swarm's internal dial methods directly
        # (bypassing queue to avoid recursion)
        # First try dialing by peer ID using internal method
        if peer_id:
            try:
                # Get addresses from peer store
                try:
                    addrs = self.swarm.peerstore.addrs(peer_id)
                except Exception:
                    addrs = []

                # Resolve DNS addresses if any
                resolved_addrs: list[Multiaddr] = []
                for addr in addrs:
                    try:
                        resolved = await self.dns_resolver.resolve(addr)
                        resolved_addrs.extend(resolved)
                    except Exception as e:
                        logger.debug(f"DNS resolution failed for {addr}: {e}")
                        resolved_addrs.append(addr)

                # Prepare addresses (filter, sort, limit)
                max_addrs = self.swarm.connection_config.max_peer_addrs_to_dial
                prepared_addrs = self.address_manager.prepare_addresses(
                    resolved_addrs, peer_id=peer_id, max_addresses=max_addrs
                )

                if prepared_addrs:
                    # Try addresses in sorted order
                    for addr in prepared_addrs:
                        try:
                            connection = await self.swarm._dial_with_retry(
                                addr, peer_id
                            )
                            return connection
                        except Exception as e:
                            logger.debug(f"Dial failed for {addr}: {e}, trying next")
                            continue
            except Exception as e:
                logger.debug(f"Direct dial failed for {peer_id}: {e}")

        # Fall back to dialing provided multiaddrs directly
        if not peer_id:
            raise RuntimeError("Failed to dial peer - no peer_id provided")

        # Resolve and prepare provided multiaddrs
        resolved_multiaddrs: list[Multiaddr] = []
        for addr in multiaddrs:
            try:
                resolved = await self.dns_resolver.resolve(addr)
                resolved_multiaddrs.extend(resolved)
            except Exception:
                resolved_multiaddrs.append(addr)

        prepared_addrs = self.address_manager.prepare_addresses(
            resolved_multiaddrs, peer_id=peer_id
        )

        for multiaddr in prepared_addrs:
            try:
                connection = await self.swarm._dial_with_retry(multiaddr, peer_id)
                return connection
            except Exception as e:
                logger.debug(f"dial_addr failed for {multiaddr}: {e}")
                continue

        raise RuntimeError(f"Failed to dial peer {peer_id}")

    def get_queue_size(self) -> int:
        """Get current queue size."""
        return len(self._queue)

    def get_running_count(self) -> int:
        """Get number of running dial jobs."""
        return len(self._running_jobs)
