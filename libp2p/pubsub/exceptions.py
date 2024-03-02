from libp2p.exceptions import (
    BaseLibp2pError,
)


class PubsubRouterError(BaseLibp2pError):
    pass


class NoPubsubAttached(PubsubRouterError):
    pass
