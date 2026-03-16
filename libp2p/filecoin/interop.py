from __future__ import annotations

from typing import Any

from multiaddr import Multiaddr

TRANSPORT_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("/webtransport", "webtransport"),
    ("/quic-v1", "quic-v1"),
    ("/wss", "wss"),
    ("/ws", "ws"),
    ("/tcp/", "tcp"),
    ("/udp/", "udp"),
)


def transport_family_for_addrs(addrs: list[Multiaddr]) -> str:
    for addr in addrs:
        addr_text = str(addr)
        for marker, family in TRANSPORT_FAMILY_PATTERNS:
            if marker in addr_text:
                return family
    return "unknown"


def _normalize_muxer_protocol(
    transport_family: str,
    muxer_protocol: str | None,
) -> str | None:
    if muxer_protocol is None and transport_family == "quic-v1":
        return "n/a"
    return muxer_protocol


def extract_connection_metadata(host: Any, peer_id: Any) -> dict[str, Any] | None:
    try:
        network = host.get_network()
        connections = network.get_connections(peer_id)
    except Exception:
        return None

    if not connections:
        return None

    connection_count = len(connections)
    for conn in connections:
        if getattr(conn, "is_closed", False):
            continue

        if hasattr(conn, "get_interop_metadata"):
            metadata = conn.get_interop_metadata()
            if metadata is not None:
                return {
                    **metadata,
                    "connection_count": connection_count,
                }

        try:
            addrs = conn.get_transport_addresses()
            transport_family = transport_family_for_addrs(addrs)
            connection_type = conn.get_connection_type()
            security_protocol = getattr(conn, "negotiated_security_protocol", None)
            muxer_protocol = getattr(conn, "negotiated_muxer_protocol", None)
        except Exception:
            continue

        return {
            "transport_family": transport_family,
            "transport_addresses": [str(addr) for addr in addrs],
            "connection_type": getattr(connection_type, "value", str(connection_type)),
            "security_protocol": security_protocol,
            "muxer_protocol": _normalize_muxer_protocol(
                transport_family,
                muxer_protocol,
            ),
            "connection_count": connection_count,
        }

    return None


def classify_probe_result(
    *,
    connected: bool,
    metadata_captured: bool,
    checks_satisfied: bool,
) -> str:
    if not connected:
        return "fail"
    if metadata_captured and checks_satisfied:
        return "pass"
    return "partial"
