class QuicError(Exception):
    """Base class for all QUIC-related errors."""


class QuicStreamError(QuicError):
    """Errors related to QUIC streams."""


class QuicConnectionError(QuicError):
    """Errors related to QUIC connections."""


class QuicProtocolError(QuicError):
    """Errors related to QUIC protocol violations."""
