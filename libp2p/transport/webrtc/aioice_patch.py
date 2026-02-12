"""
Runtime patches for aioice to better support py-libp2p test environments.

aiortc/aioice deliberately skip loopback interfaces when gathering host
candidates. For our integration tests both peers run on 127.0.0.1, so the
absence of loopback candidates causes ICE to fail even though both sides are
reachable. We monkeypatch aioice.get_host_addresses to include loopback
addresses while leaving the original behaviour untouched for other
interfaces. This mirrors what browsers do when running on localhost.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

try:
    from aioice import ice as _aioice_ice  # type: ignore
except ImportError:  # pragma: no cover - aioice is an optional dependency
    _aioice_ice = None  # type: ignore

logger = logging.getLogger("libp2p.transport.webrtc")


def _patch_loopback_candidates() -> None:
    if _aioice_ice is None:  # type: ignore
        return

    if getattr(_aioice_ice, "_libp2p_loopback_patch", False):
        return

    original_get_host_addresses: Callable[[bool, bool], list[str]] = (
        _aioice_ice.get_host_addresses
    )

    def patched_get_host_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
        addresses = original_get_host_addresses(use_ipv4, use_ipv6)
        if use_ipv4 and "127.0.0.1" not in addresses:
            addresses.append("127.0.0.1")
        if use_ipv6 and "::1" not in addresses:
            addresses.append("::1")
        return addresses

    _aioice_ice.get_host_addresses = patched_get_host_addresses
    _aioice_ice._libp2p_loopback_patch = True  # type: ignore
    logger.debug("aioice loopback candidate patch installed")


_patch_loopback_candidates()
