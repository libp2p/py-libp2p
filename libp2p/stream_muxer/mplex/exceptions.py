from libp2p.stream_muxer.exceptions import (
    MuxedConnError,
    MuxedConnShutdown,
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)


class MplexError(MuxedConnError):
    pass


class MplexShutdown(MuxedConnShutdown):
    pass


class MplexStreamReset(MuxedStreamReset):
    pass


class MplexStreamEOF(MuxedStreamEOF):
    pass


class MplexStreamClosed(MuxedStreamClosed):
    pass
