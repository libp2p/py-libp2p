"""
Shared constants and protocol parameters for the Kademlia DHT.
"""

from libp2p.custom_types import (
    TProtocol,
)

# Constants for the Kademlia algorithm
ALPHA = 10  # Concurrency parameter (per libp2p Kademlia spec)
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")
PROTOCOL_PREFIX = TProtocol("/ipfs")
QUERY_TIMEOUT = 10

TTL = DEFAULT_TTL = 24 * 60 * 60  # 24 hours in seconds

# Default parameters
BUCKET_SIZE = 20  # k in the Kademlia paper
MAXIMUM_BUCKETS = 256  # Maximum number of buckets (for 256-bit keys)

# IP/subnet diversity limits for k-buckets (issue #1383). Guards against eclipse
# attacks that grind cheap peer IDs from a single subnet: within one bucket, at
# most MAX_PEERS_PER_SUBNET peers may share the same globally-routable subnet.
# Only globally-routable addresses are grouped; loopback / private / CGNAT /
# link-local / DNS-named / relayed peers are exempt. Set MAX_PEERS_PER_SUBNET to
# 0 (or negative) to disable the check entirely.
#
# Divergence from go-libp2p (go-libp2p-kbucket/peerdiversity): go groups IPv4 by
# /16 (legacy Class A by /8) and IPv6 by ASN; we use a fixed /24 (IPv4) and /48
# (IPv6). /24 matches realistic attacker economics — a rented cloud block is
# typically a /24, not a /16 — and avoids bundling an ASN dataset. go also
# enforces a table-wide cap (maxForTable=3) in addition to the per-group cap;
# that table-wide cap is tracked as a follow-up and not implemented here.
MAX_PEERS_PER_SUBNET = 2
SUBNET_PREFIX_LEN_V4 = 24
SUBNET_PREFIX_LEN_V6 = 48
PEER_REFRESH_INTERVAL = 60  # Interval to refresh peers in seconds
STALE_PEER_THRESHOLD = 3600  # Time in seconds after which a peer is considered stale
