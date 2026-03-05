"""
Transport and connection capabilities for capability-based dispatch.

Transports and connections may declare optional capability attributes so that
the core (swarm, host) can treat them uniformly without isinstance checks:

- provides_secure: bool — this transport/connection already provides security
  (e.g. QUIC with built-in TLS). When True, the upgrader should not add a
  security layer.
- provides_muxed: bool — this transport/connection already provides multiplexing
  (e.g. QUIC with native streams). When True, the upgrader should not add a
  muxer layer, and the "raw" connection is already an IMuxedConn.

Default is False for both when the attribute is absent, so existing transports
(TCP, WebSocket, etc.) are unchanged.
"""

from typing import Any


def transport_provides_secure_and_muxed(transport: Any) -> bool:
    """
    Return True if the transport produces connections that are already
    secure and muxed (e.g. QUIC). Used to skip security/muxer upgrade.
    """
    return bool(
        getattr(transport, "provides_secure", False)
        and getattr(transport, "provides_muxed", False)
    )


def connection_provides_muxed(muxed_conn: Any) -> bool:
    """
    Return True if the muxed connection was provided directly by the transport
    (already muxed), e.g. QUIC. Used for host/swarm logic that differs for
    native-muxed vs upgraded connections.
    """
    return bool(getattr(muxed_conn, "provides_muxed", False))


def connection_needs_establishment_wait(muxed_conn: Any) -> bool:
    """
    Return True if the muxed connection has an establishment phase and
    _connected_event to wait on (e.g. QUIC). If True, caller should
    await muxed_conn._connected_event.wait() when not yet established.
    """
    event = getattr(muxed_conn, "_connected_event", None)
    if event is None:
        return False
    established = getattr(muxed_conn, "is_established", True)
    # is_established may be a property
    if callable(established):
        established = established()
    return not established
