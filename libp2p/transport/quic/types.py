"""
QUIC-specific type aliases.

These live here (rather than in ``libp2p/custom_types.py``) so that the
core package does not need to import any QUIC internals.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from libp2p.transport.quic.stream import QUICStream

if TYPE_CHECKING:
    from libp2p.transport.quic.connection import QUICConnection
else:
    QUICConnection = cast(type, object)

TQUICStreamHandlerFn = Callable[[QUICStream], Awaitable[None]]
TQUICConnHandlerFn = Callable[[QUICConnection], Awaitable[None]]
