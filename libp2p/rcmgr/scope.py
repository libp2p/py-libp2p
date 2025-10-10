"""
Resource scopes for the resource manager.

This module implements the hierarchical resource scope system that tracks
and constrains resource usage across different levels of the libp2p stack.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Protocol

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .exceptions import (
    MemoryLimitExceeded,
    ResourceScopeClosed,
    StreamOrConnLimitExceeded,
)
from .limits import BaseLimit, Direction, ScopeStat
from .metrics import Metrics


class ResourceScope(Protocol):
    """Interface for resource scopes."""

    def reserve_memory(self, size: int, priority: int = 1) -> None:
        """Reserve memory in this scope."""
        ...

    def release_memory(self, size: int) -> None:
        """Release memory in this scope."""
        ...

    def add_stream(self, direction: Direction) -> None:
        """Add a stream to this scope."""
        ...

    def remove_stream(self, direction: Direction) -> None:
        """Remove a stream from this scope."""
        ...

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Add a connection to this scope."""
        ...

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Remove a connection from this scope."""
        ...

    def stat(self) -> ScopeStat:
        """Get current resource usage statistics."""
        ...

    def done(self) -> None:
        """Release all resources and close the scope."""
        ...


@dataclass
class Resources:
    """Tracks current resource usage within a scope."""

    def __init__(self, limit: BaseLimit):
        self.limit = limit
        self.memory: int = 0
        self.streams_inbound: int = 0
        self.streams_outbound: int = 0
        self.conns_inbound: int = 0
        self.conns_outbound: int = 0
        self.num_fd: int = 0

    def check_memory(self, size: int, priority: int = 1) -> None:
        """Check if memory reservation would exceed limits."""
        new_memory = self.memory + size
        limit = self.limit.get_memory_limit()

        # Priority-based rejection: higher priority allows using more memory
        # threshold = limit * (128 + priority) / 256
        # This means priority 255 gets (128+255)/256 = 383/256 = ~150% of limit (high)
        # priority 1 gets (128+1)/256 = 129/256 = ~50% of limit
        threshold = limit * (128 + priority) // 256

        if new_memory > threshold:
            raise MemoryLimitExceeded(
                current=self.memory, attempted=size, limit=limit, priority=priority
            )

    def add_memory(self, size: int) -> None:
        """Add memory usage."""
        self.memory += size

    def remove_memory(self, size: int) -> None:
        """Remove memory usage."""
        self.memory = max(0, self.memory - size)

    def check_streams(self, direction: Direction) -> None:
        """Check if adding a stream would exceed limits."""
        current = (
            self.streams_inbound
            if direction == Direction.INBOUND
            else self.streams_outbound
        )
        limit = self.limit.get_stream_limit(direction)
        total_limit = self.limit.get_stream_total_limit()
        total_streams = self.streams_inbound + self.streams_outbound

        # Check total limit first (as it's more restrictive)
        if total_streams + 1 > total_limit:
            raise StreamOrConnLimitExceeded(
                current=total_streams,
                attempted=1,
                limit=total_limit,
                resource_type="streams_total",
            )

        # Then check direction-specific limit
        if current + 1 > limit:
            raise StreamOrConnLimitExceeded(
                current=current,
                attempted=1,
                limit=limit,
                resource_type=f"streams_{direction.value}",
            )

    def add_stream(self, direction: Direction) -> None:
        """Add a stream."""
        if direction == Direction.INBOUND:
            self.streams_inbound += 1
        else:
            self.streams_outbound += 1

    def remove_stream(self, direction: Direction) -> None:
        """Remove a stream."""
        if direction == Direction.INBOUND:
            self.streams_inbound = max(0, self.streams_inbound - 1)
        else:
            self.streams_outbound = max(0, self.streams_outbound - 1)

    def check_conns(self, direction: Direction, use_fd: bool = True) -> None:
        """Check if adding a connection would exceed limits."""
        current = (
            self.conns_inbound
            if direction == Direction.INBOUND
            else self.conns_outbound
        )
        limit = self.limit.get_conn_limit(direction)
        total_limit = self.limit.get_conn_total_limit()
        total_conns = self.conns_inbound + self.conns_outbound

        # Check FD limit first if using file descriptor
        if use_fd:
            fd_limit = self.limit.get_fd_limit()
            if self.num_fd + 1 > fd_limit:
                raise StreamOrConnLimitExceeded(
                    current=self.num_fd, attempted=1, limit=fd_limit, resource_type="fd"
                )

        # Check direction-specific limit
        if current + 1 > limit:
            raise StreamOrConnLimitExceeded(
                current=current,
                attempted=1,
                limit=limit,
                resource_type=f"conns_{direction.value}",
            )

        # Check total connection limit
        if total_conns + 1 > total_limit:
            raise StreamOrConnLimitExceeded(
                current=total_conns,
                attempted=1,
                limit=total_limit,
                resource_type="conns_total",
            )

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Add a connection."""
        if direction == Direction.INBOUND:
            self.conns_inbound += 1
        else:
            self.conns_outbound += 1

        if use_fd:
            self.num_fd += 1

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Remove a connection."""
        if direction == Direction.INBOUND:
            self.conns_inbound = max(0, self.conns_inbound - 1)
        else:
            self.conns_outbound = max(0, self.conns_outbound - 1)

        if use_fd:
            self.num_fd = max(0, self.num_fd - 1)

    def stat(self) -> ScopeStat:
        """Get current resource usage statistics."""
        return ScopeStat(
            memory=self.memory,
            num_streams_inbound=self.streams_inbound,
            num_streams_outbound=self.streams_outbound,
            num_conns_inbound=self.conns_inbound,
            num_conns_outbound=self.conns_outbound,
            num_fd=self.num_fd,
        )


class BaseResourceScope:
    """Base implementation of resource scope with DAG support."""

    def __init__(
        self,
        limit: BaseLimit,
        edges: list[BaseResourceScope] | None = None,
        name: str = "",
        metrics: Metrics | None = None,
    ):
        self.limit = limit
        self.edges = edges or []
        self.name = name
        self.metrics = metrics

        self._lock = threading.Lock()
        self._done = False
        self._ref_count = 1  # Start with 1 reference

        # Resource tracking
        self.resources = Resources(limit)

        # Increment reference count for parent scopes
        for edge in self.edges:
            edge._inc_ref()

    def _inc_ref(self) -> None:
        """Increment reference count."""
        with self._lock:
            if self._done:
                raise ResourceScopeClosed()
            self._ref_count += 1

    def _dec_ref(self) -> None:
        """Decrement reference count and cleanup if needed."""
        should_cleanup = False
        parent_edges = []

        with self._lock:
            self._ref_count -= 1
            if self._ref_count <= 0 and not self._done:
                should_cleanup = True
                self._done = True
                parent_edges = list(self.edges)  # Copy the list

        # Cleanup parent scopes outside of the lock to avoid deadlocks
        if should_cleanup:
            for edge in parent_edges:
                try:
                    edge._dec_ref()
                except Exception:
                    # Continue with other parent scopes even if one fails
                    pass

    def _cleanup(self) -> None:
        """Clean up resources and notify parent scopes."""
        # This method is now simplified since _dec_ref handles the cleanup
        pass

    def _check_closed(self) -> None:
        """Check if scope is closed."""
        if self._done:
            raise ResourceScopeClosed()

    def reserve_memory(self, size: int, priority: int = 1) -> None:
        """Reserve memory in this scope and all parent scopes."""
        with self._lock:
            self._check_closed()

            # Check this scope first
            self.resources.check_memory(size, priority)

            # Check all parent scopes
            for edge in self.edges:
                edge._check_memory_limits(size, priority)

            # If all checks pass, add memory to this scope
            self.resources.add_memory(size)

            # Also add memory to all parent scopes (hierarchical tracking)
            for edge in self.edges:
                edge._add_memory_hierarchical(size)

            # Record metrics
            if self.metrics:
                self.metrics.allow_memory(size)

    def _add_memory_hierarchical(self, size: int) -> None:
        """Add memory to this scope and propagate to parents."""
        with self._lock:
            self.resources.add_memory(size)

            # Recursively add to parent scopes
            for edge in self.edges:
                edge._add_memory_hierarchical(size)

    def _check_memory_limits(self, size: int, priority: int = 1) -> None:
        """Check memory limits without adding the memory."""
        with self._lock:
            self._check_closed()
            self.resources.check_memory(size, priority)

            # Recursively check parent scopes
            for edge in self.edges:
                edge._check_memory_limits(size, priority)

    def release_memory(self, size: int) -> None:
        """Release memory from this scope and all parent scopes."""
        with self._lock:
            # Release from this scope
            self.resources.remove_memory(size)

            # Also release from all parent scopes (hierarchical tracking)
            for edge in self.edges:
                edge._remove_memory_hierarchical(size)

            # Record metrics
            if self.metrics:
                self.metrics.release_memory(size)

    def _remove_memory_hierarchical(self, size: int) -> None:
        """Remove memory from this scope and propagate to parents."""
        with self._lock:
            self.resources.remove_memory(size)

            # Recursively remove from parent scopes
            for edge in self.edges:
                edge._remove_memory_hierarchical(size)

    def add_stream(self, direction: Direction) -> None:
        """Add a stream to this scope and all parent scopes."""
        with self._lock:
            self._check_closed()

            # Check this scope first
            self.resources.check_streams(direction)

            # Check all parent scopes
            for edge in self.edges:
                edge._check_stream_limits(direction)

            # If all checks pass, add stream to this scope
            self.resources.add_stream(direction)

            # Also add to all parent scopes
            for edge in self.edges:
                edge._add_stream_from_child(direction)

            # Record metrics
            if self.metrics:
                self.metrics.allow_stream("", direction.value)

    def _check_stream_limits(self, direction: Direction) -> None:
        """Check stream limits without adding the stream."""
        with self._lock:
            self._check_closed()
            self.resources.check_streams(direction)

            # Recursively check parent scopes
            for edge in self.edges:
                edge._check_stream_limits(direction)

    def _add_stream_from_child(self, direction: Direction) -> None:
        """Add a stream from a child scope to this scope's count (no checks)."""
        with self._lock:
            if not self._done:  # Only add if not already closed
                self.resources.add_stream(direction)

    def _check_conn_limits(self, direction: Direction, use_fd: bool = True) -> None:
        """Check connection limits without adding the connection."""
        with self._lock:
            self._check_closed()
            self.resources.check_conns(direction, use_fd)

            # Recursively check parent scopes
            for edge in self.edges:
                edge._check_conn_limits(direction, use_fd)

    def _add_conn_from_child(self, direction: Direction, use_fd: bool = True) -> None:
        """Add a connection from a child scope to this scope's count (no checks)."""
        with self._lock:
            if not self._done:  # Only add if not already closed
                self.resources.add_conn(direction, use_fd)

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Add a connection to this scope and all parent scopes."""
        with self._lock:
            self._check_closed()

            # Check this scope first
            self.resources.check_conns(direction, use_fd)

            # Check all parent scopes
            for edge in self.edges:
                edge._check_conn_limits(direction, use_fd)

            # If all checks pass, add connection to this scope
            self.resources.add_conn(direction, use_fd)

            # Also add to all parent scopes
            for edge in self.edges:
                edge._add_conn_from_child(direction, use_fd)

            # Record metrics
            if self.metrics:
                self.metrics.allow_conn(direction.value, use_fd)

    def remove_stream(self, direction: Direction) -> None:
        """Remove a stream from this scope only."""
        with self._lock:
            # Remove from this scope only
            self.resources.remove_stream(direction)

            # Record metrics
            if self.metrics:
                self.metrics.remove_stream(direction.value)

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Remove a connection from this scope only."""
        with self._lock:
            # Remove from this scope only
            self.resources.remove_conn(direction, use_fd)

            # Record metrics
            if self.metrics:
                self.metrics.remove_conn(direction.value, use_fd)

    def stat(self) -> ScopeStat:
        """Get current resource usage statistics."""
        with self._lock:
            return self.resources.stat()

    def done(self) -> None:
        """Release all resources and close the scope."""
        should_dec_ref = False

        with self._lock:
            if not self._done:
                should_dec_ref = True

        # Call _dec_ref outside of the lock to avoid deadlocks
        if should_dec_ref:
            self._dec_ref()


# Concrete scope implementations


class SystemScope(BaseResourceScope):
    """System-wide resource scope with global limits."""

    def __init__(self, limit: BaseLimit, metrics: Metrics | None = None):
        super().__init__(limit, edges=[], name="system", metrics=metrics)


class TransientScope(BaseResourceScope):
    """Transient scope for resources not yet fully established."""

    def __init__(
        self,
        limit: BaseLimit,
        system: SystemScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(limit, edges=[system], name="transient", metrics=metrics)


class PeerScope(BaseResourceScope):
    """Peer-specific resource scope."""

    def __init__(
        self,
        peer_id: ID,
        limit: BaseLimit,
        system: SystemScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(limit, edges=[system], name=f"peer:{peer_id}", metrics=metrics)
        self.peer_id = peer_id


class ProtocolScope(BaseResourceScope):
    """Protocol-specific resource scope."""

    def __init__(
        self,
        protocol: TProtocol,
        limit: BaseLimit,
        system: SystemScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(
            limit, edges=[system], name=f"protocol:{protocol}", metrics=metrics
        )
        self.protocol = protocol


class ServiceScope(BaseResourceScope):
    """Service-specific resource scope."""

    def __init__(
        self,
        service: str,
        limit: BaseLimit,
        system: SystemScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(
            limit, edges=[system], name=f"service:{service}", metrics=metrics
        )
        self.service = service


class ConnectionScope(BaseResourceScope):
    """Connection-specific resource scope."""

    def __init__(
        self,
        limit: BaseLimit,
        system: SystemScope,
        transient: TransientScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(
            limit, edges=[system, transient], name=f"conn-{id(self)}", metrics=metrics
        )
        self._conns_added: list[
            tuple[Direction, bool]
        ] = []  # Track connections for cleanup

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        """Add a connection and track it for cleanup."""
        super().add_conn(direction, use_fd)
        with self._lock:
            self._conns_added.append((direction, use_fd))

    def done(self) -> None:
        """Clean up connections from all parent scopes before closing."""
        # Get connections to cleanup
        conns_to_cleanup = []
        with self._lock:
            conns_to_cleanup = self._conns_added.copy()
            self._conns_added.clear()

        # Remove connections from all parent scopes (outside lock to avoid deadlock)
        for direction, use_fd in conns_to_cleanup:
            for edge in self.edges:
                edge.remove_conn(direction, use_fd)

        # Call parent done method
        super().done()


class StreamScope(BaseResourceScope):
    """Stream-specific resource scope."""

    def __init__(
        self,
        limit: BaseLimit,
        peer: PeerScope,
        system: SystemScope,
        transient: TransientScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(
            limit,
            edges=[peer, system, transient],
            name=f"stream-{id(self)}",
            metrics=metrics,
        )
        self.peer = peer
        self._protocol: TProtocol | None = None
        self._service: str | None = None
        self._streams_added: list[Direction] = []  # Track streams for cleanup

    def set_protocol(self, protocol: TProtocol) -> None:
        """Set the protocol for this stream and transfer from transient scope."""
        with self._lock:
            self._check_closed()
            self._protocol = protocol
            # TODO: Implement protocol scope transfer

    def set_service(self, service: str) -> None:
        """Set the service for this stream."""
        with self._lock:
            self._check_closed()
            self._service = service
            # TODO: Implement service scope transfer

    def add_stream(self, direction: Direction) -> None:
        """Add a stream and track it for cleanup."""
        super().add_stream(direction)
        with self._lock:
            self._streams_added.append(direction)

    def done(self) -> None:
        """Clean up streams from all parent scopes before closing."""
        # Get streams to cleanup
        streams_to_cleanup = []
        with self._lock:
            streams_to_cleanup = self._streams_added.copy()
            self._streams_added.clear()

        # Remove streams from all parent scopes (outside lock to avoid deadlock)
        for direction in streams_to_cleanup:
            for edge in self.edges:
                edge.remove_stream(direction)

        # Call parent done method
        super().done()
