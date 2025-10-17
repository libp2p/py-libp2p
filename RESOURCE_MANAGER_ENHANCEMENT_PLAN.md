# 🚀 Resource Manager Enhancement Plan
## Python libp2p Resource Management Evolution

**Document Version:** 1.0  
**Date:** December 2024  
**Status:** Draft  

---

## 📋 Executive Summary

This document outlines a comprehensive plan to enhance the Python libp2p ResourceManager implementation to match and exceed the capabilities of the Rust libp2p resource management system. The plan is structured in 5 phases, prioritizing critical connection state tracking and memory management improvements.

---

## 🎯 Current State Analysis

### ✅ **Strengths of Current Python Implementation**
- **Hierarchical Scope System**: System → Transient → Peer/Protocol/Service → Connection → Stream
- **Advanced Allowlist System**: Supports peer, multiaddr, and peer-multiaddr combinations
- **Unified Resource Management**: Single ResourceManager coordinating all scopes
- **Memory-based Limits**: Basic process memory checking
- **Metrics Integration**: Comprehensive metrics collection
- **Thread Safety**: Proper locking mechanisms

### ❌ **Gaps Compared to Rust Implementation**
- **Connection State Tracking**: Missing pending/established connection tracking
- **Connection Lifecycle Hooks**: No integration with connection state transitions
- **Per-peer Connection Counting**: No connection limits per peer
- **Enhanced Memory Management**: Missing stale data refresh and caching
- **Detailed Error Reporting**: Limited error context and categorization
- **Protocol-level Rate Limiting**: No protocol-specific rate limiting

---

## 🏗️ Phase Implementation Plan

---

## **Phase 1: Connection State Tracking** 
*Priority: HIGH | Duration: 2-3 weeks*

### 🎯 **Objectives**
Implement comprehensive connection state tracking to match Rust's `libp2p-connection-limits` behavior.

### 📋 **Deliverables**

#### 1.1 Connection Tracker Implementation
```python
# libp2p/rcmgr/connection_tracker.py
@dataclass
class ConnectionTracker:
    """Track connection states like Rust implementation."""
    
    # Connection state sets
    pending_inbound: set[ConnectionId] = field(default_factory=set)
    pending_outbound: set[ConnectionId] = field(default_factory=set)
    established_inbound: set[ConnectionId] = field(default_factory=set)
    established_outbound: set[ConnectionId] = field(default_factory=set)
    established_per_peer: dict[ID, set[ConnectionId]] = field(default_factory=dict)
    
    # Bypass tracking
    bypass_peers: set[ID] = field(default_factory=set)
    
    def add_pending_inbound(self, connection_id: ConnectionId) -> None
    def add_pending_outbound(self, connection_id: ConnectionId) -> None
    def move_to_established_inbound(self, connection_id: ConnectionId, peer_id: ID) -> None
    def move_to_established_outbound(self, connection_id: ConnectionId, peer_id: ID) -> None
    def remove_connection(self, connection_id: ConnectionId, peer_id: ID) -> None
    def get_connection_count(self, kind: ConnectionKind) -> int
    def get_peer_connection_count(self, peer_id: ID) -> int
```

#### 1.2 Connection Limits Configuration
```python
# libp2p/rcmgr/connection_limits.py
@dataclass
class ConnectionLimits:
    """Configurable connection limits matching Rust implementation."""
    
    max_pending_inbound: int | None = None
    max_pending_outbound: int | None = None
    max_established_inbound: int | None = None
    max_established_outbound: int | None = None
    max_established_per_peer: int | None = None
    max_established_total: int | None = None
    
    def with_max_pending_inbound(self, limit: int | None) -> ConnectionLimits
    def with_max_pending_outbound(self, limit: int | None) -> ConnectionLimits
    def with_max_established_inbound(self, limit: int | None) -> ConnectionLimits
    def with_max_established_outbound(self, limit: int | None) -> ConnectionLimits
    def with_max_established_per_peer(self, limit: int | None) -> ConnectionLimits
    def with_max_established_total(self, limit: int | None) -> ConnectionLimits
```

#### 1.3 Connection Lifecycle Integration
```python
# libp2p/rcmgr/connection_lifecycle.py
class ConnectionLifecycleManager:
    """Handle connection lifecycle events with resource management."""
    
    def __init__(self, tracker: ConnectionTracker, limits: ConnectionLimits):
        self.tracker = tracker
        self.limits = limits
    
    async def handle_pending_inbound_connection(
        self, 
        connection_id: ConnectionId,
        local_addr: Multiaddr,
        remote_addr: Multiaddr
    ) -> None:
        """Check limits before accepting inbound connection."""
        
    async def handle_established_inbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID,
        local_addr: Multiaddr,
        remote_addr: Multiaddr
    ) -> None:
        """Track established inbound connection."""
        
    async def handle_pending_outbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID | None,
        addresses: list[Multiaddr],
        endpoint: Endpoint
    ) -> None:
        """Check limits before dialing outbound connection."""
        
    async def handle_established_outbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID,
        local_addr: Multiaddr,
        endpoint: Endpoint
    ) -> None:
        """Track established outbound connection."""
```

### 🔧 **Integration Points**
- **Swarm Integration**: Modify `Swarm.add_conn()` to use lifecycle manager
- **Transport Integration**: Hook into QUIC connection establishment
- **Resource Manager Integration**: Add connection tracking to ResourceManager

### 🧪 **Testing Strategy**
- Unit tests for ConnectionTracker
- Integration tests with Swarm
- Performance tests for connection state transitions
- Memory leak tests for connection cleanup

---

## **Phase 2: Enhanced Memory Management**
*Priority: HIGH | Duration: 1-2 weeks*

### 🎯 **Objectives**
Implement sophisticated memory-based connection limits matching Rust's `libp2p-memory-connection-limits`.

### 📋 **Deliverables**

#### 2.1 Memory Connection Limits
```python
# libp2p/rcmgr/memory_limits.py
class MemoryConnectionLimits:
    """Memory-based connection limits like Rust implementation."""
    
    def __init__(
        self, 
        max_bytes: int | None = None, 
        max_percentage: float | None = None
    ):
        self.max_allowed_bytes = max_bytes
        self.max_percentage = max_percentage
        self.process_memory_bytes = 0
        self.last_refreshed = time.time()
        self.max_stale_duration = 0.1  # 100ms like Rust
        
    def with_max_bytes(self, max_bytes: int) -> MemoryConnectionLimits
    def with_max_percentage(self, percentage: float) -> MemoryConnectionLimits
    def check_limit(self) -> None
    def refresh_memory_stats_if_needed(self) -> None
    def _get_current_memory_usage(self) -> int
```

#### 2.2 Memory Stats Caching
```python
# libp2p/rcmgr/memory_stats.py
class MemoryStatsCache:
    """Cache memory statistics to avoid frequent system calls."""
    
    def __init__(self, max_stale_duration: float = 0.1):
        self.max_stale_duration = max_stale_duration
        self.cached_memory_bytes = 0
        self.last_refresh = 0.0
        
    def get_memory_usage(self) -> int
    def refresh_if_needed(self) -> None
    def force_refresh(self) -> int
```

#### 2.3 Memory Limit Integration
```python
# libp2p/rcmgr/manager.py (enhancements)
class ResourceManager:
    def __init__(self, ...):
        # ... existing code ...
        self.memory_limits: MemoryConnectionLimits | None = None
        
    def set_memory_limits(
        self, 
        max_bytes: int | None = None, 
        max_percentage: float | None = None
    ) -> None:
        """Configure memory-based connection limits."""
        
    def _check_memory_limits(self) -> None:
        """Check memory limits before opening new scopes."""
```

### 🔧 **Integration Points**
- **Resource Manager**: Integrate memory limits into scope opening
- **Connection Lifecycle**: Check memory limits during connection establishment
- **Metrics**: Add memory usage metrics

### 🧪 **Testing Strategy**
- Memory usage simulation tests
- Stale data refresh tests
- Performance tests for memory checking
- Integration tests with connection limits

---

## **Phase 3: Connection Lifecycle Hooks**
*Priority: MEDIUM | Duration: 2-3 weeks*

### 🎯 **Objectives**
Implement comprehensive connection lifecycle event handling with proper resource management integration.

### 📋 **Deliverables**

#### 3.1 Lifecycle Event System
```python
# libp2p/rcmgr/lifecycle_events.py
@dataclass
class ConnectionLifecycleEvent:
    """Base class for connection lifecycle events."""
    connection_id: ConnectionId
    timestamp: float
    peer_id: ID | None = None

@dataclass
class PendingInboundConnectionEvent(ConnectionLifecycleEvent):
    local_addr: Multiaddr
    remote_addr: Multiaddr

@dataclass
class EstablishedInboundConnectionEvent(ConnectionLifecycleEvent):
    local_addr: Multiaddr
    remote_addr: Multiaddr

@dataclass
class PendingOutboundConnectionEvent(ConnectionLifecycleEvent):
    addresses: list[Multiaddr]
    endpoint: Endpoint

@dataclass
class EstablishedOutboundConnectionEvent(ConnectionLifecycleEvent):
    local_addr: Multiaddr
    endpoint: Endpoint

@dataclass
class ConnectionClosedEvent(ConnectionLifecycleEvent):
    reason: str
    duration: float
```

#### 3.2 Lifecycle Event Handler
```python
# libp2p/rcmgr/lifecycle_handler.py
class ConnectionLifecycleHandler:
    """Handle connection lifecycle events with resource management."""
    
    def __init__(
        self, 
        tracker: ConnectionTracker,
        limits: ConnectionLimits,
        memory_limits: MemoryConnectionLimits | None = None
    ):
        self.tracker = tracker
        self.limits = limits
        self.memory_limits = memory_limits
        self.event_handlers: dict[type, list[Callable]] = {}
        
    def register_handler(self, event_type: type, handler: Callable) -> None
    def handle_event(self, event: ConnectionLifecycleEvent) -> None
    def _handle_pending_inbound(self, event: PendingInboundConnectionEvent) -> None
    def _handle_established_inbound(self, event: EstablishedInboundConnectionEvent) -> None
    def _handle_pending_outbound(self, event: PendingOutboundConnectionEvent) -> None
    def _handle_established_outbound(self, event: EstablishedOutboundConnectionEvent) -> None
    def _handle_connection_closed(self, event: ConnectionClosedEvent) -> None
```

#### 3.3 Transport Integration
```python
# libp2p/transport/quic/connection.py (enhancements)
class QUICConnection:
    def __init__(self, ..., lifecycle_handler: ConnectionLifecycleHandler | None = None):
        # ... existing code ...
        self.lifecycle_handler = lifecycle_handler
        self.connection_id = self._generate_connection_id()
        
    async def start(self) -> None:
        # ... existing code ...
        if self.lifecycle_handler:
            await self.lifecycle_handler.handle_event(
                PendingOutboundConnectionEvent(
                    connection_id=self.connection_id,
                    timestamp=time.time(),
                    peer_id=self._remote_peer_id,
                    addresses=[self._maddr],
                    endpoint=Endpoint.DIALER
                )
            )
```

### 🔧 **Integration Points**
- **Swarm**: Integrate lifecycle events into connection management
- **Transports**: Hook lifecycle events into connection establishment
- **Resource Manager**: Use lifecycle events for resource tracking

### 🧪 **Testing Strategy**
- Event handler registration tests
- Lifecycle event flow tests
- Integration tests with transports
- Performance tests for event processing

---

## **Phase 4: Enhanced Error Reporting**
*Priority: MEDIUM | Duration: 1-2 weeks*

### 🎯 **Objectives**
Implement detailed error reporting and categorization matching Rust's error system.

### 📋 **Deliverables**

#### 4.1 Enhanced Error Types
```python
# libp2p/rcmgr/errors.py
@dataclass
class ConnectionLimitExceeded(ResourceLimitExceeded):
    """Detailed connection limit error."""
    limit: int
    current: int
    kind: ConnectionLimitKind
    connection_id: ConnectionId | None = None
    peer_id: ID | None = None
    
    def __str__(self) -> str:
        return f"Connection limit exceeded: {self.kind.value} (current: {self.current}, limit: {self.limit})"

@dataclass
class MemoryUsageLimitExceeded(ResourceLimitExceeded):
    """Memory usage limit error."""
    process_memory_bytes: int
    max_allowed_bytes: int
    percentage: float
    
    def __str__(self) -> str:
        return f"Memory usage limit exceeded: {self.process_memory_bytes} bytes > {self.max_allowed_bytes} bytes ({self.percentage:.1f}%)"

class ConnectionLimitKind(Enum):
    PENDING_INBOUND = "pending_inbound"
    PENDING_OUTBOUND = "pending_outbound"
    ESTABLISHED_INBOUND = "established_inbound"
    ESTABLISHED_OUTBOUND = "established_outbound"
    ESTABLISHED_PER_PEER = "established_per_peer"
    ESTABLISHED_TOTAL = "established_total"
```

#### 4.2 Error Context Builder
```python
# libp2p/rcmgr/error_context.py
class ErrorContextBuilder:
    """Build detailed error context for debugging."""
    
    def __init__(self, tracker: ConnectionTracker, limits: ConnectionLimits):
        self.tracker = tracker
        self.limits = limits
        
    def build_connection_limit_error(
        self, 
        kind: ConnectionLimitKind,
        connection_id: ConnectionId | None = None,
        peer_id: ID | None = None
    ) -> ConnectionLimitExceeded:
        """Build detailed connection limit error."""
        
    def build_memory_limit_error(self) -> MemoryUsageLimitExceeded:
        """Build detailed memory limit error."""
        
    def get_connection_stats(self) -> dict[str, int]:
        """Get current connection statistics."""
        
    def get_memory_stats(self) -> dict[str, int]:
        """Get current memory statistics."""
```

#### 4.3 Error Reporting Integration
```python
# libp2p/rcmgr/manager.py (enhancements)
class ResourceManager:
    def __init__(self, ...):
        # ... existing code ...
        self.error_context_builder = ErrorContextBuilder(self.tracker, self.limits)
        
    def _handle_connection_limit_error(
        self, 
        kind: ConnectionLimitKind,
        connection_id: ConnectionId | None = None,
        peer_id: ID | None = None
    ) -> None:
        """Handle connection limit errors with detailed reporting."""
        
    def _handle_memory_limit_error(self) -> None:
        """Handle memory limit errors with detailed reporting."""
```

### 🔧 **Integration Points**
- **Resource Manager**: Integrate error context into all limit checks
- **Connection Lifecycle**: Add error context to lifecycle events
- **Metrics**: Add error reporting to metrics collection

### 🧪 **Testing Strategy**
- Error context building tests
- Error message formatting tests
- Integration tests with error handling
- Performance tests for error reporting

---

## **Phase 5: Protocol-Level Rate Limiting**
*Priority: LOW | Duration: 2-3 weeks*

### 🎯 **Objectives**
Implement protocol-specific rate limiting capabilities for advanced resource management.

### 📋 **Deliverables**

#### 5.1 Token Bucket Rate Limiter
```python
# libp2p/rcmgr/rate_limiter.py
class TokenBucket:
    """Token bucket rate limiter implementation."""
    
    def __init__(
        self, 
        capacity: int, 
        refill_rate: float, 
        initial_tokens: int | None = None
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = initial_tokens or capacity
        self.last_refill = time.time()
        
    def try_consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket."""
        
    def get_available_tokens(self) -> int:
        """Get current available tokens."""
        
    def refill(self) -> None:
        """Refill tokens based on elapsed time."""

class RateLimiter:
    """Rate limiter for specific resources."""
    
    def __init__(self, limits: RateLimits):
        self.limits = limits
        self.buckets: dict[str, TokenBucket] = {}
        
    def check_rate_limit(self, resource: str, tokens: int = 1) -> bool:
        """Check if rate limit allows the operation."""
        
    def get_rate_limit_status(self, resource: str) -> dict[str, Any]:
        """Get current rate limit status."""
```

#### 5.2 Protocol Rate Limiter
```python
# libp2p/rcmgr/protocol_rate_limiter.py
class ProtocolRateLimiter:
    """Rate limiting for specific protocols."""
    
    def __init__(self, protocol: TProtocol, limits: RateLimits):
        self.protocol = protocol
        self.limits = limits
        self.rate_limiter = RateLimiter(limits)
        self.peer_buckets: dict[ID, TokenBucket] = {}
        
    def check_peer_rate_limit(self, peer_id: ID, operation: str) -> bool:
        """Check rate limit for specific peer and operation."""
        
    def get_protocol_stats(self) -> dict[str, Any]:
        """Get protocol-specific statistics."""
```

#### 5.3 Rate Limiting Integration
```python
# libp2p/rcmgr/manager.py (enhancements)
class ResourceManager:
    def __init__(self, ...):
        # ... existing code ...
        self.protocol_rate_limiters: dict[TProtocol, ProtocolRateLimiter] = {}
        
    def add_protocol_rate_limiter(
        self, 
        protocol: TProtocol, 
        limits: RateLimits
    ) -> None:
        """Add rate limiter for specific protocol."""
        
    def check_protocol_rate_limit(
        self, 
        protocol: TProtocol, 
        peer_id: ID, 
        operation: str
    ) -> bool:
        """Check rate limit for protocol operation."""
```

### 🔧 **Integration Points**
- **Protocol Handlers**: Integrate rate limiting into protocol implementations
- **Stream Management**: Add rate limiting to stream operations
- **Metrics**: Add rate limiting metrics

### 🧪 **Testing Strategy**
- Token bucket algorithm tests
- Rate limiting integration tests
- Performance tests for rate limiting
- Protocol-specific rate limiting tests

---

## 🎯 **Success Metrics**

### **Phase 1: Connection State Tracking**
- ✅ All connection states properly tracked
- ✅ Connection limits enforced per state
- ✅ Per-peer connection counting working
- ✅ Connection cleanup on close

### **Phase 2: Enhanced Memory Management**
- ✅ Memory limits enforced before connection establishment
- ✅ Stale data refresh mechanism working
- ✅ Memory stats caching implemented
- ✅ Configurable refresh intervals

### **Phase 3: Connection Lifecycle Hooks**
- ✅ All lifecycle events properly handled
- ✅ Resource management integrated with lifecycle
- ✅ Event handlers working correctly
- ✅ Transport integration complete

### **Phase 4: Enhanced Error Reporting**
- ✅ Detailed error context provided
- ✅ Error categorization working
- ✅ Error reporting to metrics
- ✅ Debug information available

### **Phase 5: Protocol-Level Rate Limiting**
- ✅ Token bucket rate limiting implemented
- ✅ Protocol-specific rate limiting working
- ✅ Rate limiting metrics collected
- ✅ Integration with existing scope system

---

## 🚀 **Implementation Timeline**

| Phase | Duration | Start Date | End Date | Dependencies |
|-------|----------|------------|----------|--------------|
| Phase 1 | 2-3 weeks | Week 1 | Week 3 | None |
| Phase 2 | 1-2 weeks | Week 4 | Week 5 | Phase 1 |
| Phase 3 | 2-3 weeks | Week 6 | Week 8 | Phase 1, 2 |
| Phase 4 | 1-2 weeks | Week 9 | Week 10 | Phase 1, 2, 3 |
| Phase 5 | 2-3 weeks | Week 11 | Week 13 | Phase 1, 2, 3, 4 |

**Total Duration:** 13 weeks (3.25 months)

---

## 🔧 **Technical Considerations**

### **Backward Compatibility**
- All new features are additive
- Existing ResourceManager API remains unchanged
- New features are opt-in via configuration

### **Performance Impact**
- Connection state tracking adds minimal overhead
- Memory management uses efficient caching
- Rate limiting is designed for high throughput

### **Testing Strategy**
- Comprehensive unit tests for each component
- Integration tests with existing system
- Performance benchmarks for new features
- Memory leak detection and prevention

### **Documentation**
- API documentation for all new features
- Integration guides for each phase
- Performance tuning recommendations
- Troubleshooting guides

---

## 📚 **References**

- [Rust libp2p Connection Limits](https://github.com/libp2p/rust-libp2p/tree/master/misc/connection-limits)
- [Rust libp2p Memory Connection Limits](https://github.com/libp2p/rust-libp2p/tree/master/misc/memory-connection-limits)
- [Go libp2p Resource Manager](https://github.com/libp2p/go-libp2p/tree/master/p2p/host/resource-manager)
- [Python libp2p Resource Manager](https://github.com/libp2p/py-libp2p/tree/master/libp2p/rcmgr)

---

## 📝 **Appendices**

### **Appendix A: Code Examples**
Detailed code examples for each phase implementation.

### **Appendix B: Testing Scenarios**
Comprehensive testing scenarios for each phase.

### **Appendix C: Performance Benchmarks**
Expected performance characteristics and benchmarks.

### **Appendix D: Migration Guide**
Guide for migrating from current implementation to enhanced version.

---

*This document is a living document and will be updated as implementation progresses.*
