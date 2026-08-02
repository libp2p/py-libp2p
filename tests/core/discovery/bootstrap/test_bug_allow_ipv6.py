"""
Test Bug 1: allow_ipv6 parameter is accepted but NEVER USED.
The _is_supported_addr method checks for transport protocols (tcp, quic, etc.)
but never checks whether IPv6 addresses should be filtered when allow_ipv6=False.
"""
from unittest.mock import MagicMock, AsyncMock
from multiaddr import Multiaddr
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery

# Test with allow_ipv6=False - IPv6 addresses should be filtered out
# but they're NOT because _is_supported_addr doesn't check ip4 vs ip6
swarm = MagicMock()
swarm.get_peer_id.return_value = None
swarm.connections = {}
swarm.peerstore = MagicMock()
swarm.dial_peer = AsyncMock()

discovery = BootstrapDiscovery(swarm, [], allow_ipv6=False)

# IPv6 address with TCP
ipv6_addr = Multiaddr("/ip6/2604:a880:1:20::203:d001/tcp/4001")
# IPv4 address with TCP
ipv4_addr = Multiaddr("/ip4/192.168.1.1/tcp/4001")

result_v6 = discovery._is_supported_addr(ipv6_addr)
result_v4 = discovery._is_supported_addr(ipv4_addr)

print(f"allow_ipv6=False")
print(f"  IPv4 addr supported: {result_v4} (expected: True)")
print(f"  IPv6 addr supported: {result_v6} (expected: False - this is BUG!)")
print(f"  BUG CONFIRMED: IPv6 address accepted despite allow_ipv6=False" if result_v6 else "  No bug")

# Test with allow_ipv6=True
discovery_v6 = BootstrapDiscovery(swarm, [], allow_ipv6=True)
result_v6_enabled = discovery_v6._is_supported_addr(ipv6_addr)

print(f"\nallow_ipv6=True")
print(f"  IPv6 addr supported: {result_v6_enabled} (expected: True)")
