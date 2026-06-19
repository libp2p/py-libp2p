class IPFSLiteError(Exception):
    """Base exception for all py-ipfs-lite errors."""
    pass

class BlockNotFoundError(IPFSLiteError):
    """Raised when a block/CID cannot be found in the local store or network."""
    pass

class PinNotFoundError(IPFSLiteError):
    """Raised when attempting to operate on a pin that does not exist."""
    pass

class PeerNotStartedError(IPFSLiteError):
    """Raised when attempting to use a Peer that has not been started."""
    pass

class RoutingError(IPFSLiteError):
    """Raised when a routing operation (e.g., DHT publish/resolve) fails."""
    pass
