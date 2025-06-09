"""
Circuit Relay v2 implementation for libp2p.

This package implements the Circuit Relay v2 protocol as specified in:
https://github.com/libp2p/specs/blob/master/relay/circuit-v2.md

It also provides NAT traversal capabilities via Direct Connection Upgrade through Relay (DCUtR):
https://github.com/libp2p/specs/blob/master/relay/DCUtR.md
"""

from .dcutr import (
    DCUtRProtocol,
)
from .dcutr import PROTOCOL_ID as DCUTR_PROTOCOL_ID

from .nat import (
    ReachabilityChecker,
    is_private_ip,
)


__all__ = [
    "DCUtRProtocol",
    "DCUTR_PROTOCOL_ID",
    "ReachabilityChecker",
    "is_private_ip",
]
