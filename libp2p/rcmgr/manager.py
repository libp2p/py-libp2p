"""
Main Resource Manager implementation.

This module provides the core ResourceManager class that coordinates
resource usage across all scopes and integrates with the libp2p stack.
"""

from collections.abc import Callable
import threading
import time
from typing import Any

from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .allowlist import Allowlist, AllowlistConfig
from .exceptions import ResourceLimitExceeded, ResourceScopeClosed
from .limits import Direction, FixedLimiter
from .metrics import Metrics
from .scope import (
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
        enable_metrics: bool = False,
    ):
        self.limiter = limiter

        # Handle allowlist configuration
        if allowlist is not None:
            self.allowlist = allowlist
        elif allowlist_config is not None:
            self.allowlist = Allowlist(allowlist_config)
        else:
            self.allowlist = Allowlist()

        # Handle metrics configuration
        if metrics is not None:
            self.metrics = metrics
        elif enable_metrics:
            self.metrics = Metrics()
        else:
            self.metrics = Metrics()  # Always have metrics, but may not be enabled

        # Thread safety
        self._lock = threading.RLock()
        self._closed = False

        # Scope storage
        self._peer_scopes: dict[ID, PeerScope] = {}
        self._protocol_scopes: dict[TProtocol, ProtocolScope] = {}
        self._service_scopes: dict[str, ServiceScope] = {}

        # Sticky scopes (don't garbage collect)
        self._sticky_peers: set[ID] = set()
        self._sticky_protocols: set[TProtocol] = set()
        self._sticky_services: set[str] = set()

        # Create system and transient scopes
        system_limit = limiter.get_system_limits()
        transient_limit = limiter.get_transient_limits()

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
    ) -> ConnectionScope:
        """
        Open a new connection scope.

        Args:
            direction: Direction of the connection (inbound/outbound)
            use_fd: Whether this connection uses a file descriptor
            endpoint: Remote endpoint (optional)

        Returns:
            ConnectionScope: New connection scope

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        with self._lock:
            self._check_closed()

            # Check allowlist
            if endpoint and self.allowlist.allowed(endpoint):
                # Use allowlisted limits (not implemented yet)
                pass

            # Get connection limits
            conn_limit = self.limiter.get_conn_limits()

            # Create connection scope
            conn_scope = ConnectionScope(
                conn_limit, self.system, self.transient, self.metrics
            )

            # Add the connection to the scope
            try:
                conn_scope.add_conn(direction, use_fd)
            except ResourceLimitExceeded:
                conn_scope.done()
                if self.metrics:
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
            StreamScope: New stream scope

        Raises:
            ResourceLimitExceeded: If stream would exceed limits

        """
        with self._lock:
            self._check_closed()

            # Get or create peer scope
            peer_scope = self._get_peer_scope(peer_id)

            # Get stream limits
            stream_limit = self.limiter.get_stream_limits(peer_id)

            # Create stream scope
            stream_scope = StreamScope(
                stream_limit, peer_scope, self.system, self.transient, self.metrics
            )

            # Add the stream to the scope
            try:
                stream_scope.add_stream(direction)
            except ResourceLimitExceeded:
                stream_scope.done()
                if self.metrics:
                    self.metrics.block_stream(str(peer_id), direction.value)
                raise

            return stream_scope

    def _get_peer_scope(self, peer_id: ID) -> PeerScope:
        """Get or create a peer scope."""
        if peer_id in self._peer_scopes:
            scope = self._peer_scopes[peer_id]
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                # Scope was closed, remove it and create a new one
                del self._peer_scopes[peer_id]

        # Create new peer scope
        peer_limit = self.limiter.get_peer_limits(peer_id)
        scope = PeerScope(peer_id, peer_limit, self.system, self.metrics)
        self._peer_scopes[peer_id] = scope

        return scope

    def _get_protocol_scope(self, protocol: TProtocol) -> ProtocolScope:
        """Get or create a protocol scope."""
        if protocol in self._protocol_scopes:
            scope = self._protocol_scopes[protocol]
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                # Scope was closed, remove it and create a new one
                del self._protocol_scopes[protocol]

        # Create new protocol scope
        protocol_limit = self.limiter.get_protocol_limits(protocol)
        scope = ProtocolScope(protocol, protocol_limit, self.system, self.metrics)
        self._protocol_scopes[protocol] = scope

        return scope

    def _get_service_scope(self, service: str) -> ServiceScope:
        """Get or create a service scope."""
        if service in self._service_scopes:
            scope = self._service_scopes[service]
            try:
                scope._inc_ref()
                return scope
            except ResourceScopeClosed:
                # Scope was closed, remove it and create a new one
                del self._service_scopes[service]

        # Create new service scope
        service_limit = self.limiter.get_service_limits(service)
        scope = ServiceScope(service, service_limit, self.system, self.metrics)
        self._service_scopes[service] = scope

        return scope

    # View methods for inspecting scopes

    def view_system(self, func: Callable[[SystemScope], Any]) -> Any:
        """View the system scope."""
        with self._lock:
            self._check_closed()
            return func(self.system)

    def view_transient(self, func: Callable[[TransientScope], Any]) -> Any:
        """View the transient scope."""
        with self._lock:
            self._check_closed()
            return func(self.transient)

    def view_peer(self, peer_id: ID, func: Callable[[PeerScope], Any]) -> Any:
        """View a peer scope."""
        with self._lock:
            self._check_closed()
            scope = self._get_peer_scope(peer_id)
            try:
                return func(scope)
            finally:
                scope._dec_ref()

    def view_protocol(
        self, protocol: TProtocol, func: Callable[[ProtocolScope], Any]
    ) -> Any:
        """View a protocol scope."""
        with self._lock:
            self._check_closed()
            scope = self._get_protocol_scope(protocol)
            try:
                return func(scope)
            finally:
                scope._dec_ref()

    def view_service(self, service: str, func: Callable[[ServiceScope], Any]) -> Any:
        """View a service scope."""
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
        """List all active peer IDs."""
        with self._lock:
            return list(self._peer_scopes.keys())

    def list_protocols(self) -> list[TProtocol]:
        """List all active protocols."""
        with self._lock:
            return list(self._protocol_scopes.keys())

    def list_services(self) -> list[str]:
        """List all active services."""
        with self._lock:
            return list(self._service_scopes.keys())

    def get_allowlist(self) -> Allowlist:
        """Get the current allowlist."""
        return self.allowlist

    def get_metrics(self) -> Metrics:
        """Get the current metrics."""
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
            for peer_id, scope in self._peer_scopes.items():
                if peer_id not in self._sticky_peers and scope._ref_count <= 0:
                    to_remove.append(peer_id)

            for peer_id in to_remove:
                del self._peer_scopes[peer_id]

            # GC protocol scopes
            to_remove = []
            for protocol, scope in self._protocol_scopes.items():
                if protocol not in self._sticky_protocols and scope._ref_count <= 0:
                    to_remove.append(protocol)

            for protocol in to_remove:
                del self._protocol_scopes[protocol]

            # GC service scopes
            to_remove = []
            for service, scope in self._service_scopes.items():
                if service not in self._sticky_services and scope._ref_count <= 0:
                    to_remove.append(service)

            for service in to_remove:
                del self._service_scopes[service]

    def close(self) -> None:
        """Close the resource manager and clean up all resources."""
        # Collect all scopes to close before acquiring the main lock
        scopes_to_close = []

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
    allowlist = Allowlist(allowlist_config) if allowlist_config else Allowlist()
    metrics = Metrics() if enable_metrics else None

    return ResourceManager(limiter, allowlist, metrics)
