from libp2p.exceptions import (
    BaseLibp2pError,
)


class SwarmException(BaseLibp2pError):
    pass


class SwarmDialAllFailedError(SwarmException):
    """Raised when all addresses for a peer have been tried and none succeeded."""

    def __init__(
        self,
        message: str,
        peer_id: object = None,
        num_addrs_tried: int = 0,
    ) -> None:
        super().__init__(message)
        self.peer_id = peer_id
        self.num_addrs_tried = num_addrs_tried


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(
        self, message: str, consumed_points: int, remaining_points: int = 0
    ) -> None:
        """
        Initialize rate limit error.

        Parameters
        ----------
        message : str
            Error message
        consumed_points : int
            Number of points consumed
        remaining_points : int
            Number of points remaining

        """
        super().__init__(message)
        self.consumed_points = consumed_points
        self.remaining_points = remaining_points
