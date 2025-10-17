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
    Dict,
)

import multiaddr
from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .allowlist import Allowlist, AllowlistConfig
from .connection_lifecycle import ConnectionLifecycleManager
from .connection_limits import ConnectionLimits, new_connection_limits_with_defaults
from .connection_tracker import ConnectionTracker
from .enhanced_errors import (
    ErrorCategory,
    ErrorCode,
    ErrorContext,
    ErrorSeverity,
    create_memory_limit_error,
)
from .error_context_builder import ErrorContextBuilder, ErrorContextCollector
from .exceptions import ResourceLimitExceeded, ResourceScopeClosed
from .lifecycle_events import ConnectionEventBus, ConnectionEventType
from .lifecycle_handler import ConnectionLifecycleHandler
from .limits import BaseLimit, Direction, FixedLimiter
from .memory_limits import (
    MemoryConnectionLimits,
    new_memory_connection_limits_with_defaults,
)
from .memory_stats import MemoryStatsCache
from .metrics import Metrics
from .protocol_rate_limiter import ProtocolRateLimiter, create_protocol_rate_limiter
from .rate_limiter import (
    RateLimiter,
    create_global_rate_limiter,
    create_per_peer_rate_limiter,
)
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
        connection_limits: ConnectionLimits | None = None,
        enable_connection_tracking: bool = True,
        memory_limits: MemoryConnectionLimits | None = None,
        enable_memory_limits: bool = True,
        enable_lifecycle_events: bool = True,
        enable_enhanced_errors: bool = True,
        enable_rate_limiting: bool = True,
    ) -> None:
        # Use the provided limiter; if None, fall back to a sensible default
        if limiter is not None:
            self.limiter = FixedLimiter(
                system=BaseLimit(streams=1000, memory=512 * 1024 * 1024),
                peer_default=BaseLimit(streams=10, memory=16 * 1024 * 1024),
            )
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

        # Connection tracking (Phase 1)
        self._connection_limits = (
            connection_limits or new_connection_limits_with_defaults()
        )
        self._connection_tracker: ConnectionTracker | None = None
        self._connection_lifecycle_manager: ConnectionLifecycleManager | None = None

        if enable_connection_tracking:
            self._connection_tracker = ConnectionTracker(self._connection_limits)
            self._connection_lifecycle_manager = ConnectionLifecycleManager(
                self._connection_tracker, self._connection_limits
            )

        # Memory limits (Phase 2)
        self._memory_limits = (
            memory_limits or new_memory_connection_limits_with_defaults()
        )
        self._memory_stats_cache: MemoryStatsCache | None = None

        if enable_memory_limits:
            self._memory_stats_cache = MemoryStatsCache()
            # Use the memory stats cache from memory limits if available
            if self._memory_limits.memory_stats_cache is None:
                self._memory_limits.memory_stats_cache = self._memory_stats_cache

        # Lifecycle events (Phase 3)
        self._event_bus: ConnectionEventBus | None = None
        self._lifecycle_handler: ConnectionLifecycleHandler | None = None

        if enable_lifecycle_events:
            self._event_bus = ConnectionEventBus()
            if self._connection_lifecycle_manager and self._connection_tracker:
                self._lifecycle_handler = ConnectionLifecycleHandler(
                    connection_tracker=self._connection_tracker,
                    connection_lifecycle_manager=self._connection_lifecycle_manager,
                    memory_limits=self._memory_limits,
                    event_bus=self._event_bus,
                )

        # Enhanced errors (Phase 4)
        self._error_collector: ErrorContextCollector | None = None

        if enable_enhanced_errors:
            self._error_collector = ErrorContextCollector()

        # Rate limiting (Phase 5)
        self._global_rate_limiter: RateLimiter | None = None
        self._per_peer_rate_limiter: RateLimiter | None = None
        self._protocol_rate_limiters: Dict[str, ProtocolRateLimiter] = {}

        if enable_rate_limiting:
            # Create global rate limiter
            self._global_rate_limiter = create_global_rate_limiter(
                refill_rate=100.0,  # 100 requests per second
                capacity=1000.0,   # 1000 burst capacity
                initial_tokens=100.0,  # Start with some tokens
            )

            # Create per-peer rate limiter
            self._per_peer_rate_limiter = create_per_peer_rate_limiter(
                refill_rate=10.0,   # 10 requests per second per peer
                capacity=100.0,    # 100 burst capacity per peer
                initial_tokens=10.0,  # Start with some tokens per peer
                max_peers=1000,    # Track up to 1000 peers
            )

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
        """
        Check if process memory usage exceeds configured limits.

        This method checks both the legacy memory limit and the new memory limits.

        Returns:
            bool: True if memory limits are exceeded, False otherwise

        """
        # Check legacy memory limit
        if self._max_process_memory_bytes is not None:
            current = self._current_process_memory_bytes()
            if current > self._max_process_memory_bytes:
                # Enhanced error reporting (Phase 4)
                if self._error_collector:
                    try:
                        error = create_memory_limit_error(
                            limit_type="process_bytes",
                            limit_value=self._max_process_memory_bytes,
                            current_value=current,
                            message=(
                                f"Process memory limit exceeded: "
                                f"{current} > {self._max_process_memory_bytes}"
                            ),
                        )
                        self._error_collector.add_error(error.error_context)
                    except Exception:
                        # Don't fail on error reporting
                        pass
                return True

        # Check new memory limits (Phase 2)
        if self._memory_limits is not None:
            try:
                self._memory_limits.check_memory_limits()
            except ResourceLimitExceeded as e:
                # Enhanced error reporting (Phase 4)
                if self._error_collector:
                    try:
                        # Create enhanced error context
                        builder = ErrorContextBuilder()
                        builder.with_error_code(ErrorCode.MEMORY_LIMIT_EXCEEDED)
                        builder.with_error_category(ErrorCategory.MEMORY_LIMIT)
                        builder.with_severity(ErrorSeverity.CRITICAL)
                        builder.with_message(str(e))
                        builder.with_original_exception(e)
                        builder.with_stack_trace()

                        error_context = builder.build_context()
                        self._error_collector.add_error(error_context)
                    except Exception:
                        # Don't fail on error reporting
                        pass
                return True
            except Exception:
                # Don't fail on monitoring errors, allow resource allocation
                pass

        return False

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

    # Connection lifecycle management (Phase 1)

    def get_connection_lifecycle_manager(self) -> ConnectionLifecycleManager | None:
        """Get the connection lifecycle manager."""
        return self._connection_lifecycle_manager

    def get_connection_tracker(self) -> ConnectionTracker | None:
        """Get the connection tracker."""
        return self._connection_tracker

    def get_connection_limits(self) -> ConnectionLimits:
        """Get the connection limits configuration."""
        return self._connection_limits

    def set_connection_limits(self, limits: ConnectionLimits) -> None:
        """Update connection limits configuration."""
        with self._lock:
            self._connection_limits = limits
            if self._connection_tracker:
                self._connection_tracker.limits = limits
            if self._connection_lifecycle_manager:
                self._connection_lifecycle_manager.limits = limits

    def add_bypass_peer(self, peer_id: ID) -> None:
        """Add a peer to the connection bypass list."""
        if self._connection_tracker:
            self._connection_tracker.add_bypass_peer(peer_id)

    def remove_bypass_peer(self, peer_id: ID) -> None:
        """Remove a peer from the connection bypass list."""
        if self._connection_tracker:
            self._connection_tracker.remove_bypass_peer(peer_id)

    def is_peer_bypassed(self, peer_id: ID) -> bool:
        """Check if a peer is bypassed for connection limits."""
        if self._connection_tracker:
            return self._connection_tracker.is_bypassed(peer_id)
        return False

    def get_connection_stats(self) -> dict[str, Any]:
        """Get connection tracking statistics."""
        if self._connection_tracker:
            return self._connection_tracker.get_stats()
        return {}

    # Memory management (Phase 2)

    def get_memory_limits(self) -> MemoryConnectionLimits:
        """Get the memory limits configuration."""
        return self._memory_limits

    def set_memory_limits(self, limits: MemoryConnectionLimits) -> None:
        """Update memory limits configuration."""
        with self._lock:
            self._memory_limits = limits
            if self._memory_stats_cache:
                self._memory_limits.memory_stats_cache = self._memory_stats_cache

    def get_memory_stats_cache(self) -> MemoryStatsCache | None:
        """Get the memory statistics cache."""
        return self._memory_stats_cache

    def get_memory_summary(self, force_refresh: bool = False) -> dict[str, Any]:
        """Get comprehensive memory summary."""
        if self._memory_limits:
            return self._memory_limits.get_memory_summary(force_refresh)
        return {}

    def check_memory_limits(self, force_refresh: bool = False) -> None:
        """
        Check if current memory usage exceeds configured limits.

        Args:
            force_refresh: Force refresh of memory statistics

        Raises:
            ResourceLimitExceeded: If memory limits are exceeded

        """
        if self._memory_limits:
            self._memory_limits.check_memory_limits(force_refresh)

    # Lifecycle events (Phase 3)

    def get_event_bus(self) -> ConnectionEventBus | None:
        """Get the connection event bus."""
        return self._event_bus

    def get_lifecycle_handler(self) -> ConnectionLifecycleHandler | None:
        """Get the connection lifecycle handler."""
        return self._lifecycle_handler

    async def publish_connection_established(
        self,
        connection_id: str,
        peer_id: ID,
        direction: str,
        local_addr: multiaddr.Multiaddr | None = None,
        remote_addr: multiaddr.Multiaddr | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a connection established event.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID
            direction: Connection direction ("inbound" or "outbound")
            local_addr: Local address
            remote_addr: Remote address
            metadata: Additional event metadata

        """
        if self._lifecycle_handler:
            await self._lifecycle_handler.publish_connection_established(
                connection_id, peer_id, direction, local_addr, remote_addr, metadata
            )

    async def publish_connection_closed(
        self,
        connection_id: str,
        peer_id: ID | None = None,
        reason: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a connection closed event.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID if known
            reason: Reason for connection closure
            metadata: Additional event metadata

        """
        if self._lifecycle_handler:
            await self._lifecycle_handler.publish_connection_closed(
                connection_id, peer_id, reason, metadata
            )

    async def publish_resource_limit_exceeded(
        self,
        limit_type: str,
        limit_value: int | float,
        current_value: int | float,
        connection_id: str | None = None,
        peer_id: ID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a resource limit exceeded event.

        Args:
            limit_type: Type of limit exceeded
            limit_value: Limit value
            current_value: Current value
            connection_id: Connection identifier if applicable
            peer_id: Peer ID if applicable
            metadata: Additional event metadata

        """
        if self._lifecycle_handler:
            await self._lifecycle_handler.publish_resource_limit_exceeded(
                limit_type, limit_value, current_value, connection_id, peer_id, metadata
            )

    async def publish_stream_event(
        self,
        event_type: ConnectionEventType,
        connection_id: str,
        peer_id: ID,
        stream_id: str | None = None,
        protocol: str | None = None,
        direction: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a stream lifecycle event.

        Args:
            event_type: Type of stream event
            connection_id: Connection identifier
            peer_id: Peer ID
            stream_id: Stream identifier
            protocol: Stream protocol
            direction: Stream direction
            metadata: Additional event metadata

        """
        if self._lifecycle_handler:
            await self._lifecycle_handler.publish_stream_event(
                event_type, connection_id, peer_id, stream_id, protocol, direction,
                metadata
            )

    async def publish_peer_event(
        self,
        action: str,
        peer_id: ID,
        connection_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a peer-related event.

        Args:
            action: Peer action ("connected", "disconnected", "bypassed", "unbypassed")
            peer_id: Peer ID
            connection_id: Connection identifier if applicable
            metadata: Additional event metadata

        """
        if self._lifecycle_handler:
            await self._lifecycle_handler.publish_peer_event(
                action, peer_id, connection_id, metadata
            )

    def get_lifecycle_stats(self) -> dict[str, Any]:
        """Get lifecycle event statistics."""
        if self._lifecycle_handler:
            return self._lifecycle_handler.get_stats()
        return {}

    # Enhanced errors (Phase 4)

    def get_error_collector(self) -> ErrorContextCollector | None:
        """Get the error context collector."""
        return self._error_collector

    def get_error_statistics(self) -> dict[str, Any]:
        """Get error statistics."""
        if self._error_collector:
            return self._error_collector.get_error_statistics()
        return {}

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary for monitoring."""
        if self._error_collector:
            return self._error_collector.get_error_summary()
        return {}

    def get_errors(
        self,
        error_code: ErrorCode | None = None,
        severity: ErrorSeverity | None = None,
        category: ErrorCategory | None = None,
        limit: int | None = None,
    ) -> list[ErrorContext]:
        """
        Get errors matching the specified criteria.

        Args:
            error_code: Filter by error code
            severity: Filter by severity
            category: Filter by category
            limit: Maximum number of errors to return

        Returns:
            List of matching error contexts

        """
        if self._error_collector:
            return self._error_collector.get_errors(
                error_code, severity, category, limit
            )
        return []

    def clear_errors(self) -> None:
        """Clear all collected errors."""
        if self._error_collector:
            self._error_collector.clear_errors()

    def create_error_context_builder(self) -> ErrorContextBuilder:
        """Create a new error context builder."""
        return ErrorContextBuilder()

    # Rate limiting (Phase 5)

    def get_global_rate_limiter(self) -> RateLimiter | None:
        """Get the global rate limiter."""
        return self._global_rate_limiter

    def get_per_peer_rate_limiter(self) -> RateLimiter | None:
        """Get the per-peer rate limiter."""
        return self._per_peer_rate_limiter

    def get_protocol_rate_limiter(
        self, protocol_name: str
    ) -> ProtocolRateLimiter | None:
        """Get the protocol rate limiter for a specific protocol."""
        return self._protocol_rate_limiters.get(protocol_name)

    def create_protocol_rate_limiter(
        self,
        protocol_name: str,
        protocol_version: str | None = None,
        refill_rate: float = 10.0,
        capacity: float = 100.0,
        initial_tokens: float = 0.0,
        allow_burst: bool = True,
        burst_multiplier: float = 1.0,
        max_concurrent_requests: int = 10,
        request_timeout_seconds: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> ProtocolRateLimiter:
        """
        Create a protocol rate limiter.

        Args:
            protocol_name: Name of the protocol
            protocol_version: Version of the protocol (optional)
            refill_rate: Tokens per second
            capacity: Maximum tokens in bucket
            initial_tokens: Initial tokens in bucket
            allow_burst: Allow burst up to capacity
            burst_multiplier: Burst capacity multiplier
            max_concurrent_requests: Maximum concurrent requests
            request_timeout_seconds: Request timeout in seconds
            backoff_factor: Backoff factor for retries

        Returns:
            ProtocolRateLimiter: Created protocol rate limiter

        """
        rate_limiter = create_protocol_rate_limiter(
            protocol_name=protocol_name,
            protocol_version=protocol_version,
            refill_rate=refill_rate,
            capacity=capacity,
            initial_tokens=initial_tokens,
            allow_burst=allow_burst,
            burst_multiplier=burst_multiplier,
            max_concurrent_requests=max_concurrent_requests,
            request_timeout_seconds=request_timeout_seconds,
            backoff_factor=backoff_factor,
        )

        # Store the rate limiter
        self._protocol_rate_limiters[protocol_name] = rate_limiter

        return rate_limiter

    def try_allow_request(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol_name: str | None = None,
        current_time: float | None = None,
    ) -> bool:
        """
        Try to allow a request based on rate limiting.

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol_name: Protocol name (optional)
            current_time: Current timestamp (optional)

        Returns:
            True if request is allowed, False otherwise

        """
        if current_time is None:
            current_time = time.time()

        # Check global rate limiting
        if self._global_rate_limiter:
            if not self._global_rate_limiter.try_allow(
                tokens, None, None, None, None, current_time
            ):
                return False

        # Check per-peer rate limiting
        if self._per_peer_rate_limiter and peer_id:
            if not self._per_peer_rate_limiter.try_allow(
                tokens, peer_id, None, None, None, current_time
            ):
                return False

        # Check protocol rate limiting
        if protocol_name and protocol_name in self._protocol_rate_limiters:
            protocol_limiter = self._protocol_rate_limiters[protocol_name]
            if not protocol_limiter.try_allow_request(
                tokens, peer_id, connection_id, current_time
            ):
                return False

        return True

    def allow_request(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol_name: str | None = None,
        current_time: float | None = None,
    ) -> None:
        """
        Allow a request based on rate limiting (raises exception if denied).

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol_name: Protocol name (optional)
            current_time: Current timestamp (optional)

        Raises:
            ValueError: If request is denied by rate limiting

        """
        if not self.try_allow_request(
            tokens, peer_id, connection_id, protocol_name, current_time
        ):
            raise ValueError("Request denied by rate limiting")

    def finish_protocol_request(
        self,
        protocol_name: str,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        current_time: float | None = None,
    ) -> None:
        """
        Finish a protocol request.

        Args:
            protocol_name: Name of the protocol
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            current_time: Current timestamp (optional)

        """
        if protocol_name in self._protocol_rate_limiters:
            protocol_limiter = self._protocol_rate_limiters[protocol_name]
            protocol_limiter.finish_request(peer_id, connection_id, current_time)

    def get_rate_limiting_stats(self) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        stats: Dict[str, Any] = {
            "global_rate_limiter": None,
            "per_peer_rate_limiter": None,
            "protocol_rate_limiters": {},
        }

        if self._global_rate_limiter:
            stats["global_rate_limiter"] = (
                self._global_rate_limiter.get_stats().to_dict()
            )

        if self._per_peer_rate_limiter:
            stats["per_peer_rate_limiter"] = (
                self._per_peer_rate_limiter.get_stats().to_dict()
            )

        for protocol_name, protocol_limiter in self._protocol_rate_limiters.items():
            if "protocol_rate_limiters" in stats:
                stats["protocol_rate_limiters"][protocol_name] = (
                    protocol_limiter.get_stats().to_dict()
                )

        return stats

    def reset_rate_limiting(self) -> None:
        """Reset all rate limiters to initial state."""
        if self._global_rate_limiter:
            self._global_rate_limiter.reset()

        if self._per_peer_rate_limiter:
            self._per_peer_rate_limiter.reset()

        for protocol_limiter in self._protocol_rate_limiters.values():
            protocol_limiter.reset()

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
    connection_limits: ConnectionLimits | None = None,
    enable_connection_tracking: bool = True,
    memory_limits: MemoryConnectionLimits | None = None,
    enable_memory_limits: bool = True,
    enable_lifecycle_events: bool = True,
    enable_enhanced_errors: bool = True,
    enable_rate_limiting: bool = True,
) -> ResourceManager:
    """
    Create a new resource manager with the given configuration.

    Args:
        limiter: Resource limiter defining limits for all scopes
        allowlist_config: Optional allowlist configuration
        enable_metrics: Whether to enable metrics collection
        connection_limits: Connection limits configuration
        enable_connection_tracking: Whether to enable connection tracking
        memory_limits: Memory limits configuration
        enable_memory_limits: Whether to enable memory limits
        enable_lifecycle_events: Whether to enable lifecycle events
        enable_enhanced_errors: Whether to enable enhanced error reporting
        enable_rate_limiting: Whether to enable rate limiting
    Returns:
        ResourceManager: Configured resource manager

    """
    allowlist = (
        Allowlist(allowlist_config) if allowlist_config is not None else Allowlist()
    )
    metrics = Metrics() if enable_metrics else None
    return ResourceManager(
        limiter, allowlist, metrics, allowlist_config, enable_metrics,
        connection_limits, enable_connection_tracking,
        memory_limits, enable_memory_limits, enable_lifecycle_events,
        enable_enhanced_errors, enable_rate_limiting
    )
