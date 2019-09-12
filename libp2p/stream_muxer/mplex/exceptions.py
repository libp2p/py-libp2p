from libp2p.stream_muxer.exceptions import (
    MuxedConnClosed,
    MuxedConnError,
    MuxedConnShuttingDown,
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)


class MplexError(MuxedConnError):
    pass


class MplexShuttingDown(MuxedConnShuttingDown):
    pass


class MplexClosed(MuxedConnClosed):
    pass


class MplexStreamReset(MuxedStreamReset):
    pass


class MplexStreamEOF(MuxedStreamEOF):
    pass


class MplexStreamClosed(MuxedStreamClosed):
    pass
