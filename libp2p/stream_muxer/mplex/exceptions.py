from libp2p.exceptions import BaseLibp2pError


class MplexError(BaseLibp2pError):
    pass


class MplexShutdown(MplexError):
    pass


class StreamNotFound(MplexError):
    pass
