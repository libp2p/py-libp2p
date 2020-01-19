from libp2p.exceptions import BaseLibp2pError


class PubsubRouterError(BaseLibp2pError):
    ...


class NoPubsubAttached(PubsubRouterError):
    ...
