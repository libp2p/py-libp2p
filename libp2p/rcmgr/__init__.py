"""
Resource Manager for py-libp2p.

This package provides resource management capabilities to prevent
resource exhaustion attacks by limiting resource usage across
different scopes in the libp2p stack.

Key components:
- ResourceManager: Main resource manager class
- Resource Scopes: Hierarchical resource tracking
- Limits: Configurable resource limits
- Allowlist: Bypass limits for trusted peers/addresses
- Metrics: Resource usage tracking and observability
"""

from .exceptions import (
    ResourceLimitExceeded,
    MemoryLimitExceeded,
    StreamOrConnLimitExceeded,
    ResourceScopeClosed,
)
from .limits import (
    BaseLimit,
    Direction,
    FixedLimiter,
    ScopeStat,
)
from .manager import ResourceManager, new_resource_manager
from .metrics import Metrics, ResourceMetrics
from .scope import (
    BaseResourceScope,
    SystemScope,
    TransientScope,
    PeerScope,
    ProtocolScope,
    ServiceScope,
    ConnectionScope,
    StreamScope,
)

__all__ = [
    # Main classes
    "ResourceManager",
    "new_resource_manager",
    # Scopes
    "BaseResourceScope",
    "SystemScope",
    "TransientScope",
    "PeerScope",
    "ProtocolScope",
    "ServiceScope",
    "ConnectionScope",
    "StreamScope",
    # Limits
    "BaseLimit",
    "Direction",
    "FixedLimiter",
    "ScopeStat",
    # Allowlist
    "Allowlist",
    "AllowlistConfig",
    "new_allowlist",
    "new_allowlist_with_config",
    # Metrics
    "Metrics",
    "ResourceMetrics",
    # Exceptions
    "ResourceLimitExceeded",
    "MemoryLimitExceeded",
    "StreamOrConnLimitExceeded",
    "ResourceScopeClosed",
]
