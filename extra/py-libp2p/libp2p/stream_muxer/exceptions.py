from libp2p.exceptions import (
    BaseLibp2pError,
)


class MuxedConnError(BaseLibp2pError):
    pass


class MuxedConnUnavailable(MuxedConnError):
    pass


class MuxedStreamError(BaseLibp2pError):
    pass


class MuxedStreamReset(MuxedStreamError):
    pass


class MuxedStreamEOF(MuxedStreamError, EOFError):
    pass


class MuxedStreamClosed(MuxedStreamError):
    pass
