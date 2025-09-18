"""
Resource Manager implementation for py-libp2p.

This module provides the main resource manager that coordinates resource 
allocation and limits across the entire libp2p system.
"""
import asyncio
import time
from typing import Dict, Optional, Set

from libp2p.abc import Direction
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .exceptions import ResourceLimitExceeded
from .limits import Limiter, FixedLimiter
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
    Main resource manager implementation.
    
    The resource manager tracks and limits resource usage across different
    scopes in the libp2p system. It provides a hierarchical structure where
    resources are accounted for at multiple levels.
    """
    
    def __init__(
        self,
        limiter: Optional[Limiter] = None,
        metrics: Optional[Metrics] = None,
    ):
        self.limiter = limiter or FixedLimiter()
        self.metrics = metrics or Metrics()
        
        # Core scopes
        self.system_scope = SystemScope(
            self.limiter.get_system_limits(),
            self.metrics,
        )
        self.transient_scope = TransientScope(
            self.limiter.get_transient_limits(),
            self.system_scope,
            self.metrics,
        )
        
        # Scope registries
        self._lock = asyncio.Lock()
        self._services: Dict[str, ServiceScope] = {}
        self._protocols: Dict[TProtocol, ProtocolScope] = {}
        self._peers: Dict[ID, PeerScope] = {}
        
        # Sticky scopes (don't garbage collect)
        self._sticky_protocols: Set[TProtocol] = set()
        self._sticky_peers: Set[ID] = set()
        
        # ID counters
        self._connection_id = 0
        self._stream_id = 0
        
        # Background cleanup
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the resource manager."""
        self._running = True
        
        # Increment reference counts for core scopes
        self.system_scope.inc_ref()
        self.transient_scope.inc_ref()
        
        # Start background cleanup
        self._cleanup_task = asyncio.create_task(self._background_cleanup())
    
    async def stop(self) -> None:
        """Stop the resource manager."""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clean up all scopes
        async with self._lock:
            for service_scope in self._services.values():
                await service_scope.done()
            for protocol_scope in self._protocols.values():
                await protocol_scope.done()
            for peer_scope in self._peers.values():
                await peer_scope.done()
            
            self._services.clear()
            self._protocols.clear()
            self._peers.clear()
        
        # Clean up core scopes
        await self.transient_scope.done()
        await self.system_scope.done()
    
    def _next_connection_id(self) -> int:
        """Get next connection ID."""
        self._connection_id += 1
        return self._connection_id
    
    def _next_stream_id(self) -> int:
        """Get next stream ID."""
        self._stream_id += 1
        return self._stream_id
    
    async def get_service_scope(self, service: str) -> ServiceScope:
        """Get or create a service scope."""
        async with self._lock:
            if service not in self._services:
                scope = ServiceScope(
                    service,
                    self.limiter.get_service_limits(service),
                    self.system_scope,
                    self.metrics,
                )
                self._services[service] = scope
            
            scope = self._services[service]
            scope.inc_ref()
            return scope
    
    async def get_protocol_scope(self, protocol: TProtocol) -> ProtocolScope:
        """Get or create a protocol scope."""
        async with self._lock:
            if protocol not in self._protocols:
                scope = ProtocolScope(
                    protocol,
                    self.limiter.get_protocol_limits(protocol),
                    self.system_scope,
                    self.metrics,
                )
                self._protocols[protocol] = scope
            
            scope = self._protocols[protocol]
            scope.inc_ref()
            return scope
    
    async def get_peer_scope(self, peer_id: ID) -> PeerScope:
        """Get or create a peer scope."""
        async with self._lock:
            if peer_id not in self._peers:
                scope = PeerScope(
                    peer_id,
                    self.limiter.get_peer_limits(peer_id),
                    self.system_scope,
                    self.metrics,
                )
                self._peers[peer_id] = scope
            
            scope = self._peers[peer_id]
            scope.inc_ref()
            return scope
    
    def set_sticky_protocol(self, protocol: TProtocol) -> None:
        """Mark a protocol as sticky (won't be garbage collected)."""
        self._sticky_protocols.add(protocol)
    
    def set_sticky_peer(self, peer_id: ID) -> None:
        """Mark a peer as sticky (won't be garbage collected)."""
        self._sticky_peers.add(peer_id)
    
    async def open_connection(
        self,
        direction: Direction,
        use_fd: bool = True,
    ) -> ConnectionScope:
        """
        Open a new connection scope.
        
        Args:
            direction: The direction of the connection (inbound/outbound)
            use_fd: Whether this connection uses a file descriptor
            
        Returns:
            ConnectionScope: The connection scope
            
        Raises:
            ResourceLimitExceeded: If resource limits are exceeded
        """
        connection_id = self._next_connection_id()
        connection_scope = ConnectionScope(
            connection_id,
            direction,
            self.limiter.get_conn_limits(),
            self.system_scope,
            self.transient_scope,
            self.metrics,
        )
        
        # Reserve connection resources
        await connection_scope.add_conn(direction, use_fd)
        
        return connection_scope
    
    async def open_stream(
        self,
        peer_id: ID,
        direction: Direction,
    ) -> StreamScope:
        """
        Open a new stream scope.
        
        Args:
            peer_id: The peer ID for the stream
            direction: The direction of the stream (inbound/outbound)
            
        Returns:
            StreamScope: The stream scope
            
        Raises:
            ResourceLimitExceeded: If resource limits are exceeded
        """
        stream_id = self._next_stream_id()
        peer_scope = await self.get_peer_scope(peer_id)
        
        try:
            stream_scope = StreamScope(
                stream_id,
                direction,
                self.limiter.get_stream_limits(peer_id),
                peer_scope,
                self.system_scope,
                self.transient_scope,
                self.metrics,
            )
            
            # Reserve stream resources
            await stream_scope.add_stream(direction)
            
            return stream_scope
        finally:
            peer_scope.dec_ref()
    
    async def view_system(self, func) -> None:
        """View system scope with a function."""
        await func(self.system_scope)
    
    async def view_transient(self, func) -> None:
        """View transient scope with a function."""
        await func(self.transient_scope)
    
    async def view_service(self, service: str, func) -> None:
        """View service scope with a function."""
        scope = await self.get_service_scope(service)
        try:
            await func(scope)
        finally:
            scope.dec_ref()
    
    async def view_protocol(self, protocol: TProtocol, func) -> None:
        """View protocol scope with a function."""
        scope = await self.get_protocol_scope(protocol)
        try:
            await func(scope)
        finally:
            scope.dec_ref()
    
    async def view_peer(self, peer_id: ID, func) -> None:
        """View peer scope with a function."""
        scope = await self.get_peer_scope(peer_id)
        try:
            await func(scope)
        finally:
            scope.dec_ref()
    
    async def _background_cleanup(self) -> None:
        """Background task to clean up unused scopes."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Cleanup every minute
                await self._garbage_collect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                print(f"Error in background cleanup: {e}")
    
    async def _garbage_collect(self) -> None:
        """Garbage collect unused scopes."""
        async with self._lock:
            # Collect unused protocols
            to_remove = []
            for protocol, scope in self._protocols.items():
                if protocol not in self._sticky_protocols and scope.is_unused():
                    to_remove.append(protocol)
            
            for protocol in to_remove:
                scope = self._protocols.pop(protocol)
                await scope.done()
            
            # Collect unused peers
            dead_peers = []
            to_remove = []
            for peer_id, scope in self._peers.items():
                if peer_id not in self._sticky_peers and scope.is_unused():
                    to_remove.append(peer_id)
                    dead_peers.append(peer_id)
            
            for peer_id in to_remove:
                scope = self._peers.pop(peer_id)
                await scope.done()
            
            # Clean up dead peers from service and protocol scopes
            for service_scope in self._services.values():
                for peer_id in dead_peers:
                    if peer_id in service_scope.peers:
                        peer_scope = service_scope.peers.pop(peer_id)
                        await peer_scope.done()
            
            for protocol_scope in self._protocols.values():
                for peer_id in dead_peers:
                    if peer_id in protocol_scope.peers:
                        peer_scope = protocol_scope.peers.pop(peer_id)
                        await peer_scope.done()


class NoopResourceManager:
    """
    No-op resource manager that doesn't enforce any limits.
    
    Useful for testing or when resource management is not needed.
    """
    
    async def start(self) -> None:
        """Start the no-op resource manager."""
        pass
    
    async def stop(self) -> None:
        """Stop the no-op resource manager."""
        pass
    
    async def open_connection(
        self,
        direction: Direction,
        use_fd: bool = True,
    ) -> "NoopConnectionScope":
        """Open a no-op connection scope."""
        return NoopConnectionScope()
    
    async def open_stream(
        self,
        peer_id: ID,
        direction: Direction,
    ) -> "NoopStreamScope":
        """Open a no-op stream scope."""
        return NoopStreamScope()


class NoopConnectionScope:
    """No-op connection scope."""
    
    async def set_peer(self, peer_scope) -> None:
        """No-op set peer."""
        pass
    
    async def done(self) -> None:
        """No-op done."""
        pass


class NoopStreamScope:
    """No-op stream scope."""
    
    async def set_protocol(self, protocol_scope) -> None:
        """No-op set protocol."""
        pass
    
    async def set_service(self, service_scope) -> None:
        """No-op set service."""
        pass
    
    async def done(self) -> None:
        """No-op done."""
        pass