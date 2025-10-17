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

    def reserve_memory(self, size: int, priority: int = 1) -> None: ...

    def release_memory(self, size: int) -> None: ...

    def add_stream(self, direction: Direction) -> None: ...

    def remove_stream(self, direction: Direction) -> None: ...

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None: ...

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None: ...

    def stat(self) -> ScopeStat: ...

    def done(self) -> None: ...


@dataclass
class Resources:
    """Tracks current resource usage within a scope."""

    limit: BaseLimit

    def __init__(self, limit: BaseLimit):
        self.limit = limit
        self.memory: int = 0
        self.streams_inbound: int = 0
        self.streams_outbound: int = 0
        self.conns_inbound: int = 0
        self.conns_outbound: int = 0
        self.num_fd: int = 0

    def check_memory(self, size: int, priority: int = 1) -> None:
        new_memory = self.memory + size
        limit = self.limit.get_memory_limit()
        threshold = limit * (128 + priority) // 256
        if new_memory > threshold:
            raise MemoryLimitExceeded(
                current=self.memory, attempted=size, limit=limit, priority=priority
            )

    def add_memory(self, size: int) -> None:
        self.memory += size

    def remove_memory(self, size: int) -> None:
        self.memory = max(0, self.memory - size)

    def check_streams(self, direction: Direction) -> None:
        current = (
            self.streams_inbound
            if direction == Direction.INBOUND
            else self.streams_outbound
        )
        limit = self.limit.get_stream_limit(direction)
        total_limit = self.limit.get_stream_total_limit()
        total_streams = self.streams_inbound + self.streams_outbound

        if total_streams + 1 > total_limit:
            raise StreamOrConnLimitExceeded(
                current=total_streams,
                attempted=1,
                limit=total_limit,
                resource_type="streams_total",
            )

        if current + 1 > limit:
            raise StreamOrConnLimitExceeded(
                current=current,
                attempted=1,
                limit=limit,
                resource_type=f"streams_{direction.value}",
            )

    def add_stream(self, direction: Direction) -> None:
        if direction == Direction.INBOUND:
            self.streams_inbound += 1
        else:
            self.streams_outbound += 1

    def remove_stream(self, direction: Direction) -> None:
        if direction == Direction.INBOUND:
            self.streams_inbound = max(0, self.streams_inbound - 1)
        else:
            self.streams_outbound = max(0, self.streams_outbound - 1)

    def check_conns(self, direction: Direction, use_fd: bool = True) -> None:
        current = (
            self.conns_inbound
            if direction == Direction.INBOUND
            else self.conns_outbound
        )
        limit = self.limit.get_conn_limit(direction)
        total_limit = self.limit.get_conn_total_limit()
        total_conns = self.conns_inbound + self.conns_outbound

        if use_fd:
            fd_limit = self.limit.get_fd_limit()
            if self.num_fd + 1 > fd_limit:
                raise StreamOrConnLimitExceeded(
                    current=self.num_fd, attempted=1, limit=fd_limit, resource_type="fd"
                )

        if current + 1 > limit:
            raise StreamOrConnLimitExceeded(
                current=current,
                attempted=1,
                limit=limit,
                resource_type=f"conns_{direction.value}",
            )

        if total_conns + 1 > total_limit:
            raise StreamOrConnLimitExceeded(
                current=total_conns,
                attempted=1,
                limit=total_limit,
                resource_type="conns_total",
            )

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        if direction == Direction.INBOUND:
            self.conns_inbound += 1
        else:
            self.conns_outbound += 1

        if use_fd:
            self.num_fd += 1

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None:
        if direction == Direction.INBOUND:
            self.conns_inbound = max(0, self.conns_inbound - 1)
        else:
            self.conns_outbound = max(0, self.conns_outbound - 1)

        if use_fd:
            self.num_fd = max(0, self.num_fd - 1)

    def stat(self) -> ScopeStat:
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
        self._ref_count = 1

        self.resources = Resources(limit)

        for edge in self.edges:
            edge._inc_ref()

    def _inc_ref(self) -> None:
        with self._lock:
            if self._done:
                raise ResourceScopeClosed()
            self._ref_count += 1

    def _dec_ref(self) -> None:
        should_cleanup = False
        parent_edges = []

        with self._lock:
            self._ref_count -= 1
            if self._ref_count <= 0 and not self._done:
                should_cleanup = True
                self._done = True
                parent_edges = list(self.edges)

        if should_cleanup:
            for edge in parent_edges:
                try:
                    edge._dec_ref()
                except Exception:
                    pass

    def _cleanup(self) -> None:
        pass

    def _check_closed(self) -> None:
        if self._done:
            raise ResourceScopeClosed()

    def reserve_memory(self, size: int, priority: int = 1) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_memory(size, priority)
            for edge in self.edges:
                edge._check_memory_limits(size, priority)
            self.resources.add_memory(size)
            for edge in self.edges:
                edge._add_memory_hierarchical(size)
            if self.metrics is not None:
                self.metrics.allow_memory(size)

    def _add_memory_hierarchical(self, size: int) -> None:
        with self._lock:
            self.resources.add_memory(size)
            for edge in self.edges:
                edge._add_memory_hierarchical(size)

    def _check_memory_limits(self, size: int, priority: int = 1) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_memory(size, priority)
            for edge in self.edges:
                edge._check_memory_limits(size, priority)

    def release_memory(self, size: int) -> None:
        with self._lock:
            self.resources.remove_memory(size)
            for edge in self.edges:
                edge._remove_memory_hierarchical(size)
            if self.metrics is not None:
                self.metrics.release_memory(size)

    def _remove_memory_hierarchical(self, size: int) -> None:
        with self._lock:
            self.resources.remove_memory(size)
            for edge in self.edges:
                edge._remove_memory_hierarchical(size)

    def add_stream(self, direction: Direction) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_streams(direction)
            for edge in self.edges:
                edge._check_stream_limits(direction)
            self.resources.add_stream(direction)
            for edge in self.edges:
                edge._add_stream_from_child(direction)
            if self.metrics is not None:
                self.metrics.allow_stream("", direction.value)

    def _check_stream_limits(self, direction: Direction) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_streams(direction)
            for edge in self.edges:
                edge._check_stream_limits(direction)

    def _add_stream_from_child(self, direction: Direction) -> None:
        with self._lock:
            if not self._done:
                self.resources.add_stream(direction)

    def _check_conn_limits(self, direction: Direction, use_fd: bool = True) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_conns(direction, use_fd)
            for edge in self.edges:
                edge._check_conn_limits(direction, use_fd)

    def _add_conn_from_child(self, direction: Direction, use_fd: bool = True) -> None:
        with self._lock:
            if not self._done:
                self.resources.add_conn(direction, use_fd)

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        with self._lock:
            self._check_closed()
            self.resources.check_conns(direction, use_fd)
            for edge in self.edges:
                edge._check_conn_limits(direction, use_fd)
            self.resources.add_conn(direction, use_fd)
            for edge in self.edges:
                edge._add_conn_from_child(direction, use_fd)
            if self.metrics is not None:
                self.metrics.allow_conn(direction.value, use_fd)

    def remove_stream(self, direction: Direction) -> None:
        with self._lock:
            self.resources.remove_stream(direction)
            if self.metrics is not None:
                self.metrics.remove_stream(direction.value)

    def remove_conn(self, direction: Direction, use_fd: bool = True) -> None:
        with self._lock:
            self.resources.remove_conn(direction, use_fd)
            if self.metrics is not None:
                self.metrics.remove_conn(direction.value, use_fd)

    def stat(self) -> ScopeStat:
        with self._lock:
            return self.resources.stat()

    def done(self) -> None:
        should_dec_ref = False
        with self._lock:
            if not self._done:
                should_dec_ref = True
        if should_dec_ref:
            self._dec_ref()


class SystemScope(BaseResourceScope):
    def __init__(self, limit: BaseLimit, metrics: Metrics | None = None):
        super().__init__(limit, edges=[], name="system", metrics=metrics)


class TransientScope(BaseResourceScope):
    def __init__(
        self,
        limit: BaseLimit,
        system: SystemScope,
        metrics: Metrics | None = None,
    ):
        super().__init__(limit, edges=[system], name="transient", metrics=metrics)


class PeerScope(BaseResourceScope):
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
        self._conns_added: list[tuple[Direction, bool]] = []

    def add_conn(self, direction: Direction, use_fd: bool = True) -> None:
        super().add_conn(direction, use_fd)
        with self._lock:
            self._conns_added.append((direction, use_fd))

    def done(self) -> None:
        conns_to_cleanup = []
        with self._lock:
            conns_to_cleanup = self._conns_added.copy()
            self._conns_added.clear()
        for direction, use_fd in conns_to_cleanup:
            for edge in self.edges:
                edge.remove_conn(direction, use_fd)
        super().done()


class StreamScope(BaseResourceScope):
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
        self._streams_added: list[Direction] = []

    def set_protocol(self, protocol: TProtocol) -> None:
        with self._lock:
            self._check_closed()
            if self._protocol is not None:
                return
            transient = next(
                edge for edge in self.edges if isinstance(edge, TransientScope)
            )
            system = next(edge for edge in self.edges if isinstance(edge, SystemScope))
            stats = self.stat()
            protocol_scope = ProtocolScope(protocol, self.limit, system, self.metrics)
        try:
            if stats.memory > 0:
                protocol_scope.reserve_memory(stats.memory)
                transient.release_memory(stats.memory)
            for direction in (Direction.INBOUND, Direction.OUTBOUND):
                stream_count = (
                    stats.num_streams_inbound
                    if direction == Direction.INBOUND
                    else stats.num_streams_outbound
                )
                if stream_count > 0:
                    protocol_scope.add_stream(direction)
                    transient.remove_stream(direction)
            with self._lock:
                self.edges.append(protocol_scope)
                self._protocol = protocol
        except Exception:
            protocol_scope.done()
            raise

    def set_service(self, service: str) -> None:
        with self._lock:
            self._check_closed()
            if self._service is not None:
                return
            transient = next(
                edge for edge in self.edges if isinstance(edge, TransientScope)
            )
            system = next(edge for edge in self.edges if isinstance(edge, SystemScope))
            stats = self.stat()
            service_scope = ServiceScope(service, self.limit, system, self.metrics)
        try:
            if stats.memory > 0:
                service_scope.reserve_memory(stats.memory)
                transient.release_memory(stats.memory)
            for direction in (Direction.INBOUND, Direction.OUTBOUND):
                stream_count = (
                    stats.num_streams_inbound
                    if direction == Direction.INBOUND
                    else stats.num_streams_outbound
                )
                if stream_count > 0:
                    service_scope.add_stream(direction)
                    transient.remove_stream(direction)
            with self._lock:
                self.edges.append(service_scope)
                self._service = service
        except Exception:
            service_scope.done()
            raise

    def add_stream(self, direction: Direction) -> None:
        super().add_stream(direction)
        with self._lock:
            self._streams_added.append(direction)

    def done(self) -> None:
        streams_to_cleanup = []
        with self._lock:
            streams_to_cleanup = self._streams_added.copy()
            self._streams_added.clear()
        for direction in streams_to_cleanup:
            for edge in self.edges:
                edge.remove_stream(direction)
        super().done()
