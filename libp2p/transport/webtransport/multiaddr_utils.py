"""
WebTransport multiaddr utilities.

Format::

    /ip4|ip6/<ip>/udp/<port>/quic-v1/webtransport/certhash/<mh>[/certhash/<mh>...]/p2p/<id>

Spec: https://github.com/libp2p/specs/blob/master/webtransport/README.md
"""

from __future__ import annotations

from multiaddr import Multiaddr
from multiaddr.exceptions import ProtocolLookupError

from .exceptions import WebTransportMultiaddrError

_WEBTRANSPORT_NAME = "webtransport"
_CERTHASH_NAME = "certhash"
_QUIC_V1_NAME = "quic-v1"
_QUIC_NAME = "quic"


def _protocol_names(maddr: Multiaddr) -> list[str]:
    return [protocol.name for protocol in maddr.protocols()]


def is_webtransport_multiaddr(maddr: Multiaddr) -> bool:
    """True if *maddr* contains ``/webtransport`` over UDP + QUIC."""
    try:
        names = _protocol_names(maddr)
        if _WEBTRANSPORT_NAME not in names:
            return False
        idx = names.index(_WEBTRANSPORT_NAME)
        if idx < 2:
            return False
        # Expect .../udp/<port>/quic[-v1]/webtransport
        if names[idx - 1] not in (_QUIC_V1_NAME, _QUIC_NAME):
            return False
        if names[idx - 2] != "udp":
            return False
        return names[0] in ("ip4", "ip6") or "ip4" in names or "ip6" in names
    except Exception:
        return False


def _value_for_protocol(maddr: Multiaddr, protocol: str) -> str | None:
    try:
        return maddr.value_for_protocol(protocol)
    except ProtocolLookupError:
        return None


def extract_certhashes(maddr: Multiaddr) -> list[str]:
    """Return all multibase ``certhash`` values from *maddr* (order preserved)."""
    result: list[str] = []
    for proto, value in maddr.items():
        if proto.name == _CERTHASH_NAME and value is not None:
            result.append(str(value))
    return result


def parse_webtransport_multiaddr(
    maddr: Multiaddr,
) -> tuple[str, int, list[str], str | None]:
    """
    Extract ``(host, port, certhash_multibases, peer_id_str)``.

    :raises WebTransportMultiaddrError: If the multiaddr is malformed.
    """
    if not is_webtransport_multiaddr(maddr):
        raise WebTransportMultiaddrError(
            f"Not a valid /webtransport multiaddr: {maddr}"
        )
    try:
        host = _value_for_protocol(maddr, "ip4") or _value_for_protocol(maddr, "ip6")
        if not host:
            raise WebTransportMultiaddrError(f"No IP address in multiaddr: {maddr}")
        port_str = _value_for_protocol(maddr, "udp")
        if not port_str:
            raise WebTransportMultiaddrError(f"No UDP port in multiaddr: {maddr}")
        port = int(port_str)
        certhashes = extract_certhashes(maddr)
        peer_id = _value_for_protocol(maddr, "p2p")
        return (host, port, certhashes, peer_id)
    except WebTransportMultiaddrError:
        raise
    except Exception as e:
        raise WebTransportMultiaddrError(
            f"Failed to parse /webtransport multiaddr {maddr}: {e}"
        ) from e


def build_webtransport_multiaddr(
    host: str,
    port: int,
    certhash_multibases: list[str],
    peer_id: str | None = None,
    quic_protocol: str = _QUIC_V1_NAME,
) -> Multiaddr:
    """Construct a WebTransport multiaddr with one or more certhashes."""
    if not host:
        raise WebTransportMultiaddrError("host must be a non-empty IP address string")
    if not (0 <= port <= 65535):
        raise WebTransportMultiaddrError(f"Invalid UDP port: {port}")
    if quic_protocol not in (_QUIC_V1_NAME, _QUIC_NAME):
        raise WebTransportMultiaddrError(f"Unsupported QUIC protocol: {quic_protocol}")
    for mh in certhash_multibases:
        if not mh.startswith("u"):
            raise WebTransportMultiaddrError(
                f"certhash must be base64url-encoded (start with 'u'), got: {mh!r}"
            )
    ip_proto = "ip6" if ":" in host else "ip4"
    addr = f"/{ip_proto}/{host}/udp/{port}/{quic_protocol}/{_WEBTRANSPORT_NAME}"
    for mh in certhash_multibases:
        addr += f"/{_CERTHASH_NAME}/{mh}"
    if peer_id:
        addr += f"/p2p/{peer_id}"
    return Multiaddr(addr)
