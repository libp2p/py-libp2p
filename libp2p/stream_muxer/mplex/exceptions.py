from libp2p.stream_muxer.exceptions import (
    MuxedConnError,
    MuxedConnUnavailable,
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)


class MplexError(MuxedConnError):
    pass


class MplexUnavailable(MuxedConnUnavailable):
    pass


class MplexStreamReset(MuxedStreamReset):
    pass


class MplexStreamEOF(MuxedStreamEOF):
    pass


class MplexStreamClosed(MuxedStreamClosed):
    pass
