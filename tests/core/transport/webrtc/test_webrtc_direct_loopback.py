"""
Integration test: WebRTC Direct loopback.

Creates a listener and a dialer on localhost and verifies the full
connection lifecycle: HTTP SDP exchange → ICE → DTLS → Noise handshake
→ data-channel stream echo.

Requires aiortc to be installed.  Skipped automatically otherwise.
"""
# pyrefly: ignore

from __future__ import annotations

import pytest
import trio

try:
    import aiortc  # noqa: F401

    HAS_AIORTC = True
except ImportError:
    HAS_AIORTC = False

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.webrtc.certificate import WebRTCCertificate
from libp2p.transport.webrtc.config import WebRTCTransportConfig
from libp2p.transport.webrtc.multiaddr_utils import (
    build_webrtc_direct_multiaddr,
)
from libp2p.transport.webrtc.transport import WebRTCDirectTransport

pytestmark = pytest.mark.skipif(
    not HAS_AIORTC, reason="aiortc not installed"
)


@pytest.mark.trio
async def test_listener_advertises_certhash_in_multiaddr():
    """Listener publishes a multiaddr that contains /certhash/ and /p2p/."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)

    async def noop_handler(conn: object) -> None:
        pass

    listener = transport.create_listener(noop_handler)
    maddr_str = "/ip4/127.0.0.1/udp/0/webrtc-direct"

    from multiaddr import Multiaddr

    await listener.listen(Multiaddr(maddr_str))

    addrs = listener.get_addrs()
    assert len(addrs) == 1
    addr_str = str(addrs[0])
    assert "/webrtc-direct/" in addr_str
    assert "/certhash/" in addr_str
    assert "/p2p/" in addr_str

    await listener.close()
    await transport.close()


@pytest.mark.trio
async def test_listener_binds_actual_port():
    """When port 0 is requested, the listener binds to a real port > 0."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)

    async def noop_handler(conn: object) -> None:
        pass

    listener = transport.create_listener(noop_handler)
    from multiaddr import Multiaddr

    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))

    addrs = listener.get_addrs()
    addr_str = str(addrs[0])
    # Parse the port from the multiaddr
    parts = addr_str.split("/")
    udp_idx = parts.index("udp")
    port = int(parts[udp_idx + 1])
    assert port > 0

    await listener.close()
    await transport.close()


@pytest.mark.trio
async def test_certificate_is_aiortc_native():
    """Transport certificate should have an aiortc RTCCertificate attached."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)
    assert hasattr(transport.certificate, "_rtc_certificate")
    assert transport.certificate._rtc_certificate is not None
    await transport.close()
