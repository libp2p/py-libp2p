"""
Test Bug 3: No verification that DNS-resolved addresses match the expected peer ID.
According to the libp2p spec, dnsaddr TXT records can contain multiple multiaddrs,
each potentially having DIFFERENT peer IDs. go-libp2p's ResolveDNSAddr verifies
that resolved addresses match the expected peer ID, but py-libp2p does not.
"""
from unittest.mock import MagicMock, AsyncMock, patch
from multiaddr import Multiaddr
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery, resolver
from libp2p.peer.id import ID

# Simulate a dnsaddr address that, when resolved, returns addresses with
# DIFFERENT peer IDs than the original

BOOTSTRAP_PEER_ID = "QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
DIFFERENT_PEER_ID = "QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb"

# The resolved addresses have a DIFFERENT peer ID
resolved_addrs = [
    Multiaddr(f"/ip4/1.2.3.4/tcp/4001/p2p/{DIFFERENT_PEER_ID}"),
    Multiaddr(f"/ip4/5.6.7.8/tcp/4001/p2p/{BOOTPRINT_PEER_ID}"),
]

swarm = MagicMock()
swarm.get_peer_id.return_value = None
swarm.connections = {}
swarm.peerstore = MagicMock()
swarm.dial_peer = AsyncMock()

bootstrap_addrs = [
    f"/dns4/test.example.com/tcp/4001/p2p/{BOOTPRINT_PEER_ID}",
]

async def mock_resolve(maddr):
    return resolved_addrs

with patch.object(resolver, "resolve", side_effect=mock_resolve):
    discovery = BootstrapDiscovery(swarm, bootstrap_addrs, dns_max_retries=1)
    import trio
    trio.run(discovery.start)

# Check what peer ID was used in peerstore
print("=== Verifying DNS peer ID mismatch bug ===")
print(f"Expected peer ID: {BOOTPRINT_PEER_ID}")
print(f"Resolved addresses contain peer ID: {DIFFERENT_PEER_ID}")
print()

# Check what was added to peerstore
calls = swarm.peerstore.add_addrs.call_args_list
for call in calls:
    peer_id = call[0][0]
    addrs = call[0][1]
    print(f"peerstore.add_addrs called with peer_id={peer_id}, addrs={[str(a) for a in addrs]}")
    # Check if the DIFFERENT_PEER_ID addresses were added under BOOTPRINT_PEER_ID
    mismatched = any(
        f"/p2p/{DIFFERENT_PEER_ID}" in str(addr)
        for addr in addrs
    )
    if mismatched:
        print(f"  BUG CONFIRMED: Address with peer_id={DIFFERENT_PEER_ID} was added under peer_id={peer_id}")
        print(f"  go-libp2p would have filtered this out - py-libp2p does not!")
