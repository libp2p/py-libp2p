"""
Shared constants and protocol parameters for the Kademlia DHT.
"""

from libp2p.custom_types import (
    TProtocol,
)

# Constants for the Kademlia algorithm
ALPHA = 3  # Concurrency parameter
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
MAX_PEERS_PER_SUBNET = 2
SUBNET_PREFIX_LEN_V4 = 24
SUBNET_PREFIX_LEN_V6 = 48
PEER_REFRESH_INTERVAL = 60  # Interval to refresh peers in seconds
STALE_PEER_THRESHOLD = 3600  # Time in seconds after which a peer is considered stale
