from multiaddr import (
    Multiaddr,
)
import logging

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)

def parse_webrtc_multiaddr(multiaddr_str: str) -> Multiaddr:
    """
    Parse, validate, and extract components from a WebRTC multiaddr.

    Expected format:
    /ip4|dns4|dns6/<address>/tcp/<port>/p2p/<peer_id>/p2p-circuit/webrtc
    """
    try:
        addr = Multiaddr(multiaddr_str)
        protocols = [p.name for p in addr.protocols()]

        if "webrtc" not in protocols:
            raise ValueError("Missing /webrtc protocol in multiaddr")

        if "p2p" not in protocols:
            raise ValueError("Missing /p2p protocol (peer ID required)")

        # Extracting peer ID and address components
        components = addr.items()
        peer_id = None
        ip_or_dns = None
        port = None

        for proto, value in components:
            if proto in ("ip4", "ip6", "dns4", "dns6"):
                ip_or_dns = value
            elif proto == "tcp":
                port = value
            elif proto == "p2p":
                peer_id = value

        if not all([ip_or_dns, port, peer_id]):
            raise ValueError("Incomplete multiaddr: Must include IP/DNS, TCP port, and Peer ID")

        return {
            "multiaddr": addr,
            "peer_id": peer_id,
            "ip_or_dns": ip_or_dns,
            "port": port
        }

    except Exception as e:
        logger.error(f"[parse_webrtc_multiaddr] Failed to parse multiaddr: {e}")
        return None
