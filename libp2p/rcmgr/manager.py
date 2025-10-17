"""
Main Resource Manager implementation.

This module provides the core ResourceManager class that coordinates
resource usage across all scopes and integrates with the libp2p stack.
"""

from __future__ import annotations

from collections.abc import Callable as TypingCallable
import resource
import threading
import time
from typing import (
    Any,
)

from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .allowlist import Allowlist, AllowlistConfig
from .exceptions import ResourceLimitExceeded, ResourceScopeClosed
from .limits import BaseLimit, Direction, FixedLimiter
from .metrics import Metrics
from .scope import (
    BaseResourceScope,
    ConnectionScope,
    PeerScope,
    ProtocolScope,
    ServiceScope,
    StreamScope,
    SystemScope,
    TransientScope,
)


class ResourceManager:
    """
    Main resource manager that coordinates resource usage across all scopes.
    This is the primary interface for resource management in py-libp2p.
    It creates and manages different types of resource scopes and ensures
    that resource limits are enforced throughout the system.
    """

    def __init__(
        self,
        limiter: FixedLimiter,
        allowlist: Allowlist | None = None,
        metrics: Metrics | None = None,
        allowlist_config: AllowlistConfig | None = None,
        enable_metrics: bool = True,
    ) -> None:
        # Use the provided limiter; if None, fall back to a sensible default
        if limiter is not None:
            self.limiter = limiter
        else:
            self.limiter = FixedLimiter(
                system=BaseLimit(streams=1000, memory=512 * 1024 * 1024),
                peer_default=BaseLimit(streams=10, memory=16 * 1024 * 1024),
            )

        # Allowlist setup: prefer provided allowlist, otherwise construct from
        # allowlist_config or use an empty Allowlist.
        if allowlist is not None:
            self.allowlist = allowlist
        elif allowlist_config is not None:
            self.allowlist = Allowlist(allowlist_config)
        else:
            self.allowlist = Allowlist()

        # Handle metrics configuration
        self.metrics: Metrics | None
        if enable_metrics:
            self.metrics = Metrics()
        else:
            self.metrics = None

        # Thread safety
        self._lock = threading.RLock()
        self._closed: bool = False

        # Optional process memory guard (bytes). If set, deny new scopes when exceeded.
        self._max_process_memory_bytes: int | None = None

        # Scope storage
        self._peer_scopes: dict[ID, PeerScope] = {}
        self._protocol_scopes: dict[TProtocol, ProtocolScope] = {}
        self._service_scopes: dict[str, ServiceScope] = {}

        # Sticky scopes (don't garbage collect)
        self._sticky_peers: set[ID] = set()
        self._sticky_protocols: set[TProtocol] = set()
        self._sticky_services: set[str] = set()

        # Create system and transient scopes
        system_limit = self.limiter.get_system_limits()
        transient_limit = self.limiter.get_transient_limits()

        self.system = SystemScope(system_limit, self.metrics)
        self.transient = TransientScope(transient_limit, self.system, self.metrics)

        # Start background garbage collection
        self._gc_thread = threading.Thread(target=self._background_gc, daemon=True)
        self._gc_thread.start()

    def _check_closed(self) -> None:
        """Check if the resource manager is closed."""
        if self._closed:
            raise RuntimeError("Resource manager is closed")

    # Core interface methods

    def open_connection(
        self,
        direction: Direction,
        use_fd: bool = True,
        endpoint: Multiaddr | None = None,
        peer_id: ID | None = None,
    ) -> ConnectionScope:
        """
        Open a new connection scope.

        Args:
            direction: Direction of the connection (inbound/outbound)
            use_fd: Whether this connection uses a file descriptor
            endpoint: Remote endpoint (optional)
            peer_id: Remote peer id if known (for allowlist checks)

        Returns:
            :class:`libp2p.rcmgr.scope.ConnectionScope`: New connection scope

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        with self._lock:
            self._check_closed()

            # Enforce optional process memory guard
            if self._process_memory_exceeded():
                raise ResourceLimitExceeded(
                    message="Process memory limit exceeded; denying new connection"
                )

            # Select connection limits; allowlisted peer+endpoint
            # or endpoint get relaxed limits
            if endpoint is not None and (
                (
                    peer_id is not None
                    and self.allowlist.allowed_peer_and_multiaddr(peer_id, endpoint)
                )
                or self.allowlist.allowed(endpoint)
            ):
                conn_limit = self.limiter.get_allowlist_conn_limits()
            else:
                conn_limit = self.limiter.get_conn_limits()
            conn_scope = ConnectionScope(
                conn_limit, self.system, self.transient, self.metrics
            )
            try:
                conn_scope.add_conn(direction, use_fd)
            except ResourceLimitExceeded:
                conn_scope.done()
                if self.metrics is not None:
                    self.metrics.block_conn(direction.value, use_fd)
                raise
            return conn_scope

    def open_stream(self, peer_id: ID, direction: Direction) -> StreamScope:
        """
        Open a new stream scope.

        Args:
            peer_id: Peer ID for the stream
            direction: Direction of the stream (inbound/outbound)

        Returns:
            :class:`libp2p.rcmgr.scope.StreamScope`: New stream scope

        Raises:
            ResourceLimitExceeded: If stream would exceed limits

        """
        with self._lock:
            self._check_closed()
            # Enforce optional process memory guard
            if self._process_memory_exceeded():
                raise ResourceLimitExceeded(
                    message="Process memory limit exceeded; denying new stream"
                )

            peer_scope = self._get_peer_scope(peer_id)
            # Allowlisted peers get relaxed limits (reuse allowlist connection limits
            # which default to very high values for streams as well).
            if self.allowlist.allowed_peer(peer_id):
                stream_limit = self.limiter.get_allowlist_conn_limits()
            else:
                stream_limit = self.limiter.get_stream_limits(peer_id)
            stream_scope = StreamScope(
                stream_limit, peer_scope, self.system, self.transient, self.metrics
            )
            try:
                stream_scope.add_stream(direction)
            except ResourceLimitExceeded:
                stream_scope.done()
                if self.metrics is not None:
                    self.metrics.block_stream(str(peer_id), direction.value)
                raise
            return stream_scope

    def set_max_process_memory_bytes(self, max_bytes: int | None) -> None:
        """Configure an optional process memory cap for opening new scopes."""
        with self._lock:
            self._max_process_memory_bytes = max_bytes

    def _current_process_memory_bytes(self) -> int:
        """Best-effort current process RSS in bytes (Unix)."""
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss = getattr(usage, "ru_maxrss", 0)
            # ru_maxrss unit varies: on Linux it's kilobytes, on macOS bytes.
            # Heuristic: treat small values as kilobytes.
            if rss < 1 << 20:  # very small, likely kilobytes
                return int(rss) * 1024
            return int(rss)
        except Exception:
            return 0

    def _process_memory_exceeded(self) -> bool:
        if self._max_process_memory_bytes is None:
            return False
        current = self._current_process_memory_bytes()
        return current > self._max_process_memory_bytes

    def _get_peer_scope(self, peer_id: ID) -> PeerScope:
        """Get or create a peer scope."""
        scope = self._peer_scopes.get(peer_id)
        if scope is not None:
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                del self._peer_scopes[peer_id]
        peer_limit = self.limiter.get_peer_limits(peer_id)
        scope = PeerScope(peer_id, peer_limit, self.system, self.metrics)
        self._peer_scopes[peer_id] = scope
        return scope

    def _get_protocol_scope(self, protocol: TProtocol) -> ProtocolScope:
        """Get or create a protocol scope."""
        scope = self._protocol_scopes.get(protocol)
        if scope is not None:
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                del self._protocol_scopes[protocol]
        protocol_limit = self.limiter.get_protocol_limits(protocol)
        scope = ProtocolScope(protocol, protocol_limit, self.system, self.metrics)
        self._protocol_scopes[protocol] = scope
        return scope

    def _get_service_scope(self, service: str) -> ServiceScope:
        """Get or create a service scope."""
        scope = self._service_scopes.get(service)
        if scope is not None:
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                del self._service_scopes[service]
        service_limit = self.limiter.get_service_limits(service)
        scope = ServiceScope(service, service_limit, self.system, self.metrics)
        self._service_scopes[service] = scope
        return scope

    # View methods for inspecting scopes

    def view_system(self, func: TypingCallable[[SystemScope], Any]) -> Any:
        with self._lock:
            self._check_closed()
            return func(self.system)

    def view_transient(self, func: TypingCallable[[TransientScope], Any]) -> Any:
        with self._lock:
            self._check_closed()
            return func(self.transient)

    def view_peer(self, peer_id: ID, func: TypingCallable[[PeerScope], Any]) -> Any:
        with self._lock:
            self._check_closed()
            scope = self._get_peer_scope(peer_id)
            try:
                return func(scope)
            finally:
                scope._dec_ref()

    def view_protocol(
        self, protocol: TProtocol, func: TypingCallable[[ProtocolScope], Any]
    ) -> Any:
        with self._lock:
            self._check_closed()
            scope = self._get_protocol_scope(protocol)
            try:
                return func(scope)
            finally:
                scope._dec_ref()

    def view_service(
        self, service: str, func: TypingCallable[[ServiceScope], Any]
    ) -> Any:
        with self._lock:
            self._check_closed()
            scope = self._get_service_scope(service)
            try:
                return func(scope)
            finally:
                scope._dec_ref()

    # Management methods

    def set_sticky_peer(self, peer_id: ID) -> None:
        """Mark a peer scope as sticky (won't be garbage collected)."""
        with self._lock:
            self._sticky_peers.add(peer_id)

    def set_sticky_protocol(self, protocol: TProtocol) -> None:
        """Mark a protocol scope as sticky (won't be garbage collected)."""
        with self._lock:
            self._sticky_protocols.add(protocol)

    def set_sticky_service(self, service: str) -> None:
        """Mark a service scope as sticky (won't be garbage collected)."""
        with self._lock:
            self._sticky_services.add(service)

    def list_peers(self) -> list[ID]:
        with self._lock:
            return list(self._peer_scopes.keys())

    def list_protocols(self) -> list[TProtocol]:
        with self._lock:
            return list(self._protocol_scopes.keys())

    def list_services(self) -> list[str]:
        with self._lock:
            return list(self._service_scopes.keys())

    def get_allowlist(self) -> Allowlist:
        return self.allowlist

    def get_metrics(self) -> Metrics | None:
        return self.metrics

    # Garbage collection

    def _background_gc(self) -> None:
        """Background garbage collection of unused scopes."""
        while not self._closed:
            try:
                time.sleep(60)  # Run every minute
                self._gc_scopes()
            except Exception:
                # Ignore exceptions in background thread
                pass

    def _gc_scopes(self) -> None:
        """Garbage collect unused scopes."""
        with self._lock:
            if self._closed:
                return

            # GC peer scopes
            to_remove = []
            for peer_id, peer_scope in self._peer_scopes.items():
                if peer_id not in self._sticky_peers and peer_scope._ref_count <= 0:
                    to_remove.append(peer_id)

            for peer_id in to_remove:
                del self._peer_scopes[peer_id]

            # GC protocol scopes
            protocols_to_remove = []
            for protocol, protocol_scope in self._protocol_scopes.items():
                if (
                    protocol not in self._sticky_protocols
                    and protocol_scope._ref_count <= 0
                ):
                    protocols_to_remove.append(protocol)

            for protocol in protocols_to_remove:
                del self._protocol_scopes[protocol]

            # GC service scopes
            services_to_remove = []
            for service, service_scope in self._service_scopes.items():
                if (
                    service not in self._sticky_services
                    and service_scope._ref_count <= 0
                ):
                    services_to_remove.append(service)

            for service in services_to_remove:
                del self._service_scopes[service]

    def close(self) -> None:
        """Close the resource manager and clean up all resources."""
        # Collect all scopes to close before acquiring the main lock
        scopes_to_close: list[BaseResourceScope] = []

        with self._lock:
            if self._closed:
                return

            self._closed = True

            # Collect scopes without calling done() while holding the lock
            scopes_to_close.extend([self.system, self.transient])
            scopes_to_close.extend(list(self._peer_scopes.values()))
            scopes_to_close.extend(list(self._protocol_scopes.values()))
            scopes_to_close.extend(list(self._service_scopes.values()))

        # Close all scopes outside of the main lock to avoid deadlocks
        for scope in scopes_to_close:
            try:
                scope.done()
            except Exception:
                # Continue closing other scopes even if one fails
                pass

        # Clear all scope storage
        self._peer_scopes.clear()
        self._protocol_scopes.clear()
        self._service_scopes.clear()


def new_resource_manager(
    limiter: FixedLimiter,
    allowlist_config: AllowlistConfig | None = None,
    enable_metrics: bool = True,
) -> ResourceManager:
    """
    Create a new resource manager with the given configuration.

    Args:
        limiter: Resource limiter defining limits for all scopes
        allowlist_config: Optional allowlist configuration
        enable_metrics: Whether to enable metrics collection
    Returns:
        ResourceManager: Configured resource manager

    """
    allowlist = (
        Allowlist(allowlist_config) if allowlist_config is not None else Allowlist()
    )
    metrics = Metrics() if enable_metrics else None
    return ResourceManager(
        limiter, allowlist, metrics, allowlist_config, enable_metrics
    )
