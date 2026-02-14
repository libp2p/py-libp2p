"""
Transport and connection capability checks.

These helpers allow the core (swarm, host) to branch on transport/connection
*capabilities* (e.g. "provides secure connection", "provides muxed connection")
instead of concrete types like QUICTransport/QUICConnection. That keeps the
core decoupled from specific implementations and supports:

- Neither: raw connection → run security then muxer (e.g. TCP).
- Secure only: ISecureConn from dial → run muxer only.
- Muxed only: IMuxedConn from dial (muxed but not secure) → use as-is.
- Both: IMuxedConn from dial (secure and muxed) → skip upgrade (e.g. QUIC).
"""

from __future__ import annotations

from typing import Any

from libp2p.abc import IMuxedConn, ITransport

# can skip security and/or muxer upgrade when not needed.
PROVIDES_SECURE_ATTRIBUTE = "provides_secure_connection"
PROVIDES_MUXED_ATTRIBUTE = "provides_muxed_connection"


def transport_provides_secure_connection(transport: ITransport) -> bool:
    """
    Return True if this transport's dial() returns at least a secure connection
    (ISecureConn or IMuxedConn that is secure). Swarm will skip security
    upgrade when True.
    """
    return bool(getattr(transport, PROVIDES_SECURE_ATTRIBUTE, False))


def transport_provides_muxed_connection(transport: ITransport) -> bool:
    """
    Return True if this transport's dial() returns a muxed connection
    (IMuxedConn). Swarm will skip muxer upgrade when True. Connection may
    be secure or not (see provides_secure_connection).
    """
    return bool(getattr(transport, PROVIDES_MUXED_ATTRIBUTE, False))


def transport_provides_secure_muxed(transport: ITransport) -> bool:
    """
    Return True if this transport provides both secure and muxed connection.
    Convenience for "skip full upgrade" (backward compatible).
    """
    return transport_provides_secure_connection(
        transport
    ) and transport_provides_muxed_connection(transport)


def muxed_conn_has_resource_scope(muxed_conn: IMuxedConn) -> bool:
    """
    Return True if this muxed connection supports set_resource_scope(scope)
    for resource manager integration (e.g. connection-level cleanup).
    """
    return hasattr(muxed_conn, "set_resource_scope") and callable(
        getattr(muxed_conn, "set_resource_scope", None)
    )


def muxed_conn_has_establishment_wait(muxed_conn: IMuxedConn) -> bool:
    """
    Return True if this connection has is_established and _connected_event,
    so the swarm should wait for establishment before considering it ready.
    """
    has_established = hasattr(muxed_conn, "is_established")
    has_event = hasattr(muxed_conn, "_connected_event")
    return bool(has_established and has_event)


def muxed_conn_has_negotiation_semaphore(muxed_conn: IMuxedConn) -> bool:
    """
    Return True if this connection exposes a negotiation semaphore for
    throttling concurrent protocol negotiations (e.g. server-side).
    """
    return (
        hasattr(muxed_conn, "_negotiation_semaphore")
        and getattr(muxed_conn, "_negotiation_semaphore", None) is not None
    )


def muxed_conn_get_establishment_waiter(muxed_conn: IMuxedConn) -> Any | None:
    """
    Return the _connected_event to wait on for establishment, or None.
    Caller should only wait if muxed_conn_has_establishment_wait() is True.
    """
    return getattr(muxed_conn, "_connected_event", None)


def muxed_conn_is_established(muxed_conn: IMuxedConn) -> bool:
    """
    Return whether the connection is established (handshake completed).
    If the connection doesn't support this, returns True (no wait needed).
    """
    established = getattr(muxed_conn, "is_established", None)
    if established is None:
        return True
    if callable(established):
        return bool(established())
    return bool(established)
