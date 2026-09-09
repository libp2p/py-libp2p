"""
Detect expected connection / muxer shutdown errors.

Remote peer hangup or local teardown should not surface as fatal service
errors (ExceptionGroup from the Swarm manager). Active stream I/O still
raises these types to callers; only background tasks / host.run close
paths should absorb them via this predicate.
"""

from __future__ import annotations

import logging
import sys
from typing import Final

from libp2p.io.exceptions import ConnectionClosedError
from libp2p.network.connection.exceptions import RawConnError
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)

logger = logging.getLogger("libp2p.connection_shutdown")

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

# Extra phrases used by TLS/stream stacks during peer hangup.
_EXPECTED_PHRASES: Final[tuple[str, ...]] = (
    "connection closed",
    "connection is closed",
    "tls connection is closed",
    "stream reset",
    "connection reset",
    "broken pipe",
    "stream eof",
    "end of file",
    "stream is closed",
    "stream buffer closed",
    "closed resource",
    "broken resource",
    "failed to read the header correctly",
    "failed to read the message body correctly",
    "failed to write message to the underlying connection",
)

_EXPECTED_TYPES: Final[tuple[type[BaseException], ...]] = (
    MuxedConnUnavailable,
    MuxedStreamEOF,
    MuxedStreamClosed,
    MuxedStreamReset,
    ConnectionClosedError,
)


def is_expected_connection_shutdown(exc: BaseException | None) -> bool:
    """
    Return True if *exc* represents a normal peer/local connection teardown.

    Recurses into ExceptionGroup / __cause__ / __context__. Unexpected
    members of a group make the whole group unexpected.
    """
    if exc is None:
        return False

    if isinstance(exc, ExceptionGroup):
        nested = exc.exceptions
        if not nested:
            return False
        return all(is_expected_connection_shutdown(inner) for inner in nested)

    if any(isinstance(exc, expected) for expected in _EXPECTED_TYPES):
        return True

    # Empty RawConnError is used as a normal EOF signal in yamux/mplex paths.
    if isinstance(exc, RawConnError):
        msg = str(exc).strip().lower()
        return (not msg) or any(p in msg for p in _EXPECTED_PHRASES)

    msg = str(exc).lower()
    if any(p in msg for p in _EXPECTED_PHRASES):
        return True

    if exc.__cause__ is not None and is_expected_connection_shutdown(exc.__cause__):
        return True
    if (
        exc.__context__ is not None
        and exc.__context__ is not exc.__cause__
        and is_expected_connection_shutdown(exc.__context__)
    ):
        return True

    return False


def log_expected_connection_shutdown(
    *,
    component: str,
    peer_id: object | None = None,
    direction: str = "unknown",
    exc: BaseException | None = None,
) -> None:
    """DEBUG one line describing an absorbed connection shutdown."""
    logger.debug(
        "%s: expected connection shutdown (direction=%s peer=%s): %s: %s",
        component,
        direction,
        peer_id,
        type(exc).__name__ if exc is not None else "none",
        exc,
    )
