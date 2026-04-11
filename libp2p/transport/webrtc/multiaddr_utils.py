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

import logging
import threading

from multiaddr import Multiaddr
from multiaddr import protocols as _mp

from .constants import (
    CERTHASH_PROTOCOL_CODE,
    WEBRTC_DIRECT_PROTOCOL_CODE,
    WEBRTC_PROTOCOL_CODE,
)
from .exceptions import WebRTCMultiaddrError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Register WebRTC protocol codes with py-multiaddr.
#
# py-multiaddr 0.0.11 ships with the old p2p-webrtc-direct (0x0114) but NOT
# the current spec protocols.  We register them at import time so that
# Multiaddr("/ip4/.../udp/.../webrtc-direct") construction works.
#
# certhash (0x01D2) takes a string value but py-multiaddr's binary codec
# system doesn't handle it correctly, so we parse certhash from the string
# representation instead of relying on protocols().
# ---------------------------------------------------------------------------
_PROTOCOLS_TO_REGISTER = [
    _mp.Protocol(code=WEBRTC_DIRECT_PROTOCOL_CODE, name="webrtc-direct", codec=None),
    _mp.Protocol(code=WEBRTC_PROTOCOL_CODE, name="webrtc", codec=None),
    _mp.Protocol(code=CERTHASH_PROTOCOL_CODE, name="certhash", codec="utf8"),
]

_registered = False
_registration_lock = threading.Lock()


def _ensure_protocols_registered() -> None:
    """Register WebRTC multiaddr protocols (idempotent, thread-safe)."""
    global _registered
    if _registered:
        return
    with _registration_lock:
        if _registered:  # double-checked locking
            return
        was_locked = _mp.REGISTRY.locked
        if was_locked:
            _mp.REGISTRY._locked = False
        try:
            for proto in _PROTOCOLS_TO_REGISTER:
                try:
                    _mp.REGISTRY.add(proto)
                except Exception:
                    pass  # Already registered or conflict — skip
        finally:
            if was_locked:
                _mp.REGISTRY._locked = True
        _registered = True
        logger.debug("Registered WebRTC multiaddr protocols")


# Register on import
_ensure_protocols_registered()

# Protocol name strings
_WEBRTC_DIRECT_NAME = "webrtc-direct"
_WEBRTC_NAME = "webrtc"
_CERTHASH_NAME = "certhash"

# All known multiaddr protocol names.  Used by _parse_multiaddr_string to
# distinguish protocol names from protocol values.  If the next path segment
# is in this set it starts a new protocol; otherwise it is the current
# protocol's value (e.g. "127.0.0.1" for ip4, "uEi..." for certhash).
_KNOWN_PROTOCOL_NAMES = frozenset({
    "ip4", "ip6", "tcp", "udp",
    _WEBRTC_DIRECT_NAME, _WEBRTC_NAME, _CERTHASH_NAME,
    "p2p", "p2p-circuit", "quic", "quic-v1", "tls", "noise", "http", "https",
    "ws", "wss", "dns", "dns4", "dns6", "dnsaddr",
})


def _parse_multiaddr_string(maddr_str: str) -> list[tuple[str, str]]:
    """
    Parse a multiaddr string into ``(protocol_name, value)`` pairs.

    Handles certhash and other value-bearing protocols correctly by treating
    the string as a sequence of ``/protocol[/value]`` segments where known
    protocol names delimit the segments.
    """
    parts = maddr_str.split("/")
    result: list[tuple[str, str]] = []
    i = 1  # skip leading empty string
    while i < len(parts):
        proto = parts[i]
        # Next element is a value if it's NOT a known protocol name
        if i + 1 < len(parts) and parts[i + 1] not in _KNOWN_PROTOCOL_NAMES:
            result.append((proto, parts[i + 1]))
            i += 2
        else:
            result.append((proto, ""))
            i += 1
    return result


def is_webrtc_direct_multiaddr(maddr: Multiaddr) -> bool:
    """
    Check whether *maddr* is a valid WebRTC Direct address.

    :param maddr: Multiaddr to test.
    :returns: True if the address contains ``/webrtc-direct``.
    """
    try:
        parts = _parse_multiaddr_string(str(maddr))
        names = [p for p, _ in parts]
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
        parts = _parse_multiaddr_string(str(maddr))
        names = [p for p, _ in parts]
        if _WEBRTC_NAME not in names:
            return False
        idx = names.index(_WEBRTC_NAME)
        return idx > 0 and names[idx - 1] == "p2p-circuit"
    except Exception:
        return False


def parse_webrtc_direct_multiaddr(
    maddr: Multiaddr,
) -> tuple[str, int, str | None, str | None]:
    """
    Extract components from a ``/webrtc-direct`` multiaddr.

    :param maddr: A WebRTC Direct multiaddr.
    :returns: Tuple of ``(host, port, certhash_multibase_or_none, peer_id_str_or_none)``.
    :raises WebRTCMultiaddrError: If the multiaddr is malformed.
    """
    if not is_webrtc_direct_multiaddr(maddr):
        raise WebRTCMultiaddrError(f"Not a valid /webrtc-direct multiaddr: {maddr}")

    try:
        parts_dict = dict(_parse_multiaddr_string(str(maddr)))

        host = parts_dict.get("ip4") or parts_dict.get("ip6")
        if not host:
            raise WebRTCMultiaddrError(f"No IP address in multiaddr: {maddr}")

        port_str = parts_dict.get("udp")
        if not port_str:
            raise WebRTCMultiaddrError(f"No UDP port in multiaddr: {maddr}")
        port = int(port_str)

        certhash = parts_dict.get(_CERTHASH_NAME) or None
        peer_id = parts_dict.get("p2p") or None

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
    addr = f"/{ip_proto}/{host}/udp/{port}/{_WEBRTC_DIRECT_NAME}/{_CERTHASH_NAME}/{certhash_multibase}"
    if peer_id:
        addr += f"/p2p/{peer_id}"
    return Multiaddr(addr)
