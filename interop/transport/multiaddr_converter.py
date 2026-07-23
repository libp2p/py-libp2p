import sys
import multiaddr
from typing import Tuple, List, Optional

def get_ip_value(addr: multiaddr.Multiaddr) -> Optional[str]:
    """Extract IP value from multiaddr (IPv4 or IPv6)."""
    try:
        if addr.value_for_protocol("ip4"):
            return addr.value_for_protocol("ip4")
        elif addr.value_for_protocol("ip6"):
            return addr.value_for_protocol("ip6")
    except Exception:
        pass
    return None

def extract_p2p(addr: multiaddr.Multiaddr) -> Tuple[multiaddr.Multiaddr, Optional[str]]:
    """
    Extract p2p component from address and return address without p2p.
    """
    protocols = [p.name for p in addr.protocols()]
    p2p_value = None
    if "p2p" in protocols:
        p2p_value = addr.value_for_protocol("p2p")
        if p2p_value:
            addr = addr.decapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
    return addr, p2p_value

def filter_by_transport(addresses: List[multiaddr.Multiaddr], transport: str) -> List[multiaddr.Multiaddr]:
    """Filter addresses to match current transport type."""
    filtered = []
    for addr in addresses:
        protocols = [p.name for p in addr.protocols()]
        if transport == "ws" and ("ws" in protocols or "wss" in protocols):
            filtered.append(addr)
        elif transport == "wss" and "wss" in protocols:
            filtered.append(addr)
        elif transport == "quic-v1" and "quic-v1" in protocols:
            filtered.append(addr)
        elif transport == "webrtc-direct" and "webrtc-direct" in protocols:
            filtered.append(addr)
        elif transport == "tcp" and not any(
            p in protocols for p in ["ws", "wss", "quic-v1", "webrtc-direct"]
        ):
            filtered.append(addr)
    return filtered if filtered else addresses

def replace_loopback_ip(addresses: List[multiaddr.Multiaddr], ip: str) -> List[multiaddr.Multiaddr]:
    """Replace loopback IPs with the given IP."""
    results = []
    for addr in addresses:
        try:
            addr_str = str(addr)
            if "/ip4/127.0.0.1/" in addr_str:
                addr_str = addr_str.replace("/ip4/127.0.0.1/", f"/ip4/{ip}/")
                results.append(multiaddr.Multiaddr(addr_str))
            elif "/ip6/::1/" in addr_str:
                addr_str = addr_str.replace("/ip6/::1/", f"/ip6/{ip}/")
                results.append(multiaddr.Multiaddr(addr_str))
            else:
                results.append(addr)
        except Exception as e:
            print(f"Error replacing loopback IP in {addr}: {e}", file=sys.stderr)
            results.append(addr)
    return results
