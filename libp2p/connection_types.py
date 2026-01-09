from enum import Enum


class ConnectionType(Enum):
    """
    Enumeration of connection types.

    Represents the type of connection (direct, relayed, etc.)
    """

    DIRECT = "direct"  # Direct peer-to-peer connection
    RELAYED = "relayed"  # Connection through circuit relay
    UNKNOWN = "unknown"  # Cannot determine
