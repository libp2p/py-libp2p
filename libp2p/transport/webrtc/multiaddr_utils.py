"""
WebRTC multiaddr utilities.

Parse and construct ``/webrtc-direct`` and ``/webrtc`` multiaddrs.

WebRTC Direct format::

    /ip4/<ip>/udp/<port>/webrtc-direct/certhash/<multibase-multihash>/p2p/<peer-id>

WebRTC (relay-based) format::

    <relay-multiaddr>/p2p-circuit/webrtc/p2p/<peer-id>

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

from multiaddr import Multiaddr
from multiaddr.exceptions import ProtocolLookupError

from .exceptions import WebRTCMultiaddrError

_WEBRTC_DIRECT_NAME = "webrtc-direct"
_WEBRTC_NAME = "webrtc"
_CERTHASH_NAME = "certhash"


def _protocol_names(maddr: Multiaddr) -> list[str]:
    return [protocol.name for protocol in maddr.protocols()]


def is_webrtc_direct_multiaddr(maddr: Multiaddr) -> bool:
    """
    Check whether *maddr* is a valid WebRTC Direct address.

    :param maddr: Multiaddr to test.
    :returns: True if the address contains ``/webrtc-direct``.
    """
    try:
        names = _protocol_names(maddr)
        if _WEBRTC_DIRECT_NAME not in names:
            return False
        idx = names.index(_WEBRTC_DIRECT_NAME)
        return idx >= 2 and names[idx - 1] == "udp" and names[idx - 2] in ("ip4", "ip6")
    except Exception:
        return False


def is_webrtc_multiaddr(maddr: Multiaddr) -> bool:
    """
    Check whether *maddr* is a relay-based WebRTC address.

    A valid address contains ``/p2p-circuit/webrtc/``.
    """
    try:
        names = _protocol_names(maddr)
        if _WEBRTC_NAME not in names:
            return False
        idx = names.index(_WEBRTC_NAME)
        return idx > 0 and names[idx - 1] == "p2p-circuit"
    except Exception:
        return False


def _value_for_protocol(maddr: Multiaddr, protocol: str) -> str | None:
    try:
        return maddr.value_for_protocol(protocol)
    except ProtocolLookupError:
        return None


def parse_webrtc_direct_multiaddr(
    maddr: Multiaddr,
) -> tuple[str, int, str | None, str | None]:
    """
    Extract components from a ``/webrtc-direct`` multiaddr.

    :param maddr: A WebRTC Direct multiaddr.
    :returns: Tuple of ``(host, port, certhash_multibase, peer_id_str)``,
        where the last two may be ``None`` if absent in the multiaddr.
    :raises WebRTCMultiaddrError: If the multiaddr is malformed.
    """
    if not is_webrtc_direct_multiaddr(maddr):
        raise WebRTCMultiaddrError(f"Not a valid /webrtc-direct multiaddr: {maddr}")

    try:
        host = _value_for_protocol(maddr, "ip4") or _value_for_protocol(maddr, "ip6")
        if not host:
            raise WebRTCMultiaddrError(f"No IP address in multiaddr: {maddr}")

        port_str = _value_for_protocol(maddr, "udp")
        if not port_str:
            raise WebRTCMultiaddrError(f"No UDP port in multiaddr: {maddr}")
        port = int(port_str)

        certhash = _value_for_protocol(maddr, _CERTHASH_NAME)
        peer_id = _value_for_protocol(maddr, "p2p")

        return (host, port, certhash, peer_id)

    except WebRTCMultiaddrError:
        raise
    except Exception as e:
        raise WebRTCMultiaddrError(
            f"Failed to parse /webrtc-direct multiaddr {maddr}: {e}"
        ) from e


def build_webrtc_direct_multiaddr(
    host: str,
    port: int,
    certhash_multibase: str,
    peer_id: str | None = None,
) -> Multiaddr:
    """
    Construct a ``/webrtc-direct`` multiaddr.

    :param host: IPv4 or IPv6 address string.
    :param port: UDP port number.
    :param certhash_multibase: Multibase-encoded certificate hash (e.g. ``uEi...``).
    :param peer_id: Optional base58 peer ID.
    :returns: A :class:`Multiaddr`.
    :raises WebRTCMultiaddrError: If inputs are invalid.
    """
    if not host:
        raise WebRTCMultiaddrError("host must be a non-empty IP address string")
    if not (1 <= port <= 65535):
        raise WebRTCMultiaddrError(f"Invalid UDP port: {port}")
    if not certhash_multibase.startswith("u"):
        raise WebRTCMultiaddrError(
            f"certhash_multibase must be base64url-encoded (start with 'u'), "
            f"got: {certhash_multibase!r}"
        )
    ip_proto = "ip6" if ":" in host else "ip4"
    addr = (
        f"/{ip_proto}/{host}/udp/{port}/{_WEBRTC_DIRECT_NAME}"
        f"/{_CERTHASH_NAME}/{certhash_multibase}"
    )
    if peer_id:
        addr += f"/p2p/{peer_id}"
    return Multiaddr(addr)
