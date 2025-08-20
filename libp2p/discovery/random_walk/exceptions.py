from libp2p.exceptions import BaseLibp2pError


class RoutingTableRefreshError(BaseLibp2pError):
    """Base exception for routing table refresh operations."""

    pass


class RandomWalkError(RoutingTableRefreshError):
    """Exception raised during random walk operations."""

    pass


class PeerValidationError(RoutingTableRefreshError):
    """Exception raised when peer validation fails."""

    pass
