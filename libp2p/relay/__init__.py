"""
Relay functionality for libp2p.

This package implements relay functionality for libp2p, including:
- Circuit Relay v2 protocol
- DCUtR (Direct Connection Upgrade through Relay) for NAT traversal

This package includes implementations of circuit relay protocols
for enabling connectivity between peers behind NATs or firewalls.
It also provides NAT traversal capabilities via Direct Connection Upgrade through Relay (DCUtR).
"""

from libp2p.relay.circuit_v2 import (

    DCUtRProtocol,
    DCUTR_PROTOCOL_ID,
    ReachabilityChecker,
    is_private_ip,
)

__all__ = [
    "DCUtRProtocol",
    "DCUTR_PROTOCOL_ID",
    "ReachabilityChecker",
    "is_private_ip",
]
