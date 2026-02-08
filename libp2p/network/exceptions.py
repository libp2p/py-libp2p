from libp2p.exceptions import (
    NetworkError,
)


class SwarmException(NetworkError):
    """Exception raised by swarm operations."""
    pass
