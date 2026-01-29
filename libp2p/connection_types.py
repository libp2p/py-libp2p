"""
Connection type definitions for transport address standardization.

Provides enums for categorizing libp2p connections based on transport characteristics.
Enables determining connection properties (direct vs relayed) without parsing multiaddrs.

Usage:
    from libp2p.abc import ConnectionType
    # or
    from libp2p.connection_types import ConnectionType
"""

from enum import Enum


class ConnectionType(Enum):
    """
    Connection type classification.
    
    Attributes:
        DIRECT: Direct peer-to-peer connection
        RELAYED: Connection through circuit relay
        UNKNOWN: Type cannot be determined
    """

    DIRECT = "direct"
    RELAYED = "relayed"
    UNKNOWN = "unknown"
