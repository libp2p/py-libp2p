from libp2p.exceptions import (
    PubsubError,
)


class PubsubRouterError(PubsubError):
    """Exception raised by pubsub router operations."""
    pass


class NoPubsubAttached(PubsubRouterError):
    pass
