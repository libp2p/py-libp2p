"""
Protocol handler requirement declarations (Phase 2).

Decorators that let protocol handlers and connection layers express what
they need at runtime — without changing how existing code works.

``@requires_connection`` — declares that a protocol handler needs a
connection satisfying one or more interfaces (e.g. ``ISecureConn``).

``@after_connection`` — declares that a connection layer (e.g. a muxer)
should be stacked *after* another layer (e.g. security) in the upgrade
pipeline.

``get_required_connections`` / ``get_after_connections`` — introspect the
metadata attached by those decorators.

Examples
--------
::

    from libp2p.requirements import requires_connection, after_connection
    from libp2p.abc import ISecureConn, IMuxedConn

    @requires_connection(ISecureConn)
    async def my_protocol_handler(stream):
        '''Only run me on a secured connection.'''
        ...

    @after_connection(ISecureConn)
    class Yamux(IMuxedConn):
        '''Yamux should be stacked AFTER a security layer.'''
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F")


# ---------------------------------------------------------------------------
# @requires_connection — protocol handler decorator
# ---------------------------------------------------------------------------

def requires_connection(*interfaces: type) -> Any:
    """Mark a protocol handler as requiring certain connection interfaces.

    Parameters
    ----------
    *interfaces:
        One or more ABC / Protocol types that the underlying connection
        must satisfy (e.g. ``ISecureConn``, ``IMuxedConn``).

    Returns
    -------
    decorator
        Wraps the handler function, attaching ``_required_connections``.

    Example
    -------
    ::

        @requires_connection(ISecureConn)
        async def echo_handler(stream):
            ...
    """

    def decorator(fn: F) -> F:
        fn._required_connections = interfaces  # type: ignore[attr-defined]
        return fn

    return decorator


def get_required_connections(fn: Any) -> Sequence[type]:
    """Return the connection interfaces required by *fn*, or ``()``."""
    return getattr(fn, "_required_connections", ())


# ---------------------------------------------------------------------------
# @after_connection — connection-layer ordering decorator
# ---------------------------------------------------------------------------

def after_connection(*interfaces: type) -> Any:
    """Declare that a connection layer must be applied *after* certain
    other layers are present in the stack.

    This is ordering metadata only — it does **not** mean the listed
    interfaces *must* be present (use ``@requires_connection`` for that).

    Parameters
    ----------
    *interfaces:
        One or more ABC / Protocol types that must appear earlier in the
        connection upgrade pipeline.

    Example
    -------
    ::

        @after_connection(ISecureConn)
        class Yamux(IMuxedConn):
            ...
    """

    def decorator(cls: F) -> F:
        cls._after_connections = interfaces  # type: ignore[attr-defined]
        return cls

    return decorator


def get_after_connections(cls: Any) -> Sequence[type]:
    """Return the interfaces that *cls* must come after, or ``()``."""
    return getattr(cls, "_after_connections", ())


# ---------------------------------------------------------------------------
# Runtime enforcement helper
# ---------------------------------------------------------------------------

def check_connection_requirements(
    handler: Any,
    connection: Any,
    *,
    raise_on_failure: bool = False,
) -> bool:
    """Verify that *connection* satisfies the requirements declared on *handler*.

    Parameters
    ----------
    handler:
        A callable (possibly decorated with ``@requires_connection``).
    connection:
        The underlying connection object to check.
    raise_on_failure:
        If ``True``, raise ``ConnectionRequirementError`` instead of
        returning ``False``.

    Returns
    -------
    bool
        ``True`` if all requirements are met (or none were declared).
    """
    required = get_required_connections(handler)
    if not required:
        return True

    for iface in required:
        if not isinstance(connection, iface):
            msg = (
                f"Handler {getattr(handler, '__name__', handler)} requires "
                f"{iface.__name__}, but the connection {type(connection).__name__} "
                f"does not satisfy it."
            )
            if raise_on_failure:
                raise ConnectionRequirementError(msg)
            logger.warning(msg)
            return False
    return True


class ConnectionRequirementError(Exception):
    """Raised when a protocol handler's connection requirements are not met."""
