"""
Connection Health Monitoring for Python libp2p.

This module provides enhanced connection health monitoring capabilities,
including health metrics tracking, proactive monitoring, and health-aware
load balancing.

For usage, import classes directly:
    from libp2p.network.health.data_structures import ConnectionHealth
    from libp2p.network.health.monitor import ConnectionHealthMonitor
"""

from .data_structures import create_default_connection_health

__all__ = [
    "create_default_connection_health",
]
