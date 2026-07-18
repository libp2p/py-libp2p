from libp2p.io.exceptions import (
    IOException,
)


class StreamError(IOException):
    pass


class StreamEOF(StreamError, EOFError):
    pass


class StreamReset(StreamError):
    pass


class StreamClosed(StreamError):
    pass
