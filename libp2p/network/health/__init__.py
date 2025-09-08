"""
Connection Health Monitoring for Python libp2p.

This module provides enhanced connection health monitoring capabilities,
including health metrics tracking, proactive monitoring, and health-aware
load balancing.
"""

from .data_structures import (
    ConnectionHealth,
    create_default_connection_health,
)
from .monitor import ConnectionHealthMonitor

__all__ = [
    "ConnectionHealth",
    "create_default_connection_health",
    "ConnectionHealthMonitor",
]
