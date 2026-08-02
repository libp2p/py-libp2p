"""
Test Bug 2: Uses ID.from_base58 instead of ID.from_string.
ID.from_base58 only does base58 decoding without multihash validation.
ID.from_string (used in info_from_p2p_addr) validates both multibase and base58.
This means the bootstrap code accepts peer IDs that would be rejected by the
standard peer ID parsing path.
"""
from unittest.mock import MagicMock, AsyncMock, patch
from multiaddr import Multiaddr
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery, resolver
from libp2p.peer.id import ID

# Test: ID.from_base58 vs ID.from_string
# Valid base58-encoded peer ID
valid_peer_id_str = "QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"

# Test from_base58
pid_from_b58 = ID.from_base58(valid_peer_id_str)
print(f"ID.from_base58: {pid_from_b58}")

# Test from_string
pid_from_str = ID.from_string(valid_peer_id_str)
print(f"ID.from_string: {pid_from_str}")

print(f"Both work for valid IDs: {pid_from_b58 == pid_from_str}")

# Test: What happens with from_base58 on a string that's valid base58
# but NOT a valid multihash?
# "QmInvalidPeerIDThatIsWayTooLongForARealPeerId" is not valid base58
# But let's try something that IS valid base58 but NOT a valid multihash
# A peer ID must be a valid multihash (identity or sha2-256)
# from_base58 just decodes base58, no validation of the multihash format
# from_string tries from_multibase first, then falls back to from_base58

# Let's test with a short string that decodes from base58 but isn't a valid multihash
try:
    # "hello" is valid base58 but not a valid peer ID
    decoded = ID.from_base58("hello")
    print(f"\nfrom_base58('hello') succeeded: {decoded}")
    print("This is BUG: from_base58 accepts invalid peer IDs!")
except Exception as e:
    print(f"\nfrom_base58('hello') failed: {e}")

try:
    decoded = ID.from_string("hello")
    print(f"from_string('hello') succeeded: {decoded}")
except Exception as e:
    print(f"from_string('hello') failed: {type(e).__name__}: {e}")
    print("This shows from_string properly validates peer IDs!")
