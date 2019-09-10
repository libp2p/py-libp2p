from libp2p.exceptions import BaseLibp2pError


class StreamError(BaseLibp2pError):
    pass


class StreamEOF(StreamError, EOFError):
    pass


class StreamReset(StreamError):
    pass


class StreamClosed(StreamError):
    pass
