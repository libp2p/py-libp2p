from libp2p.exceptions import BaseLibp2pError


class MplexError(BaseLibp2pError):
    pass


class MplexStreamReset(MplexError):
    pass


class MplexStreamEOF(MplexError, EOFError):
    pass


class MplexShutdown(MplexError):
    pass
