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
PEER_REFRESH_INTERVAL = 60  # Interval to refresh peers in seconds
STALE_PEER_THRESHOLD = 3600  # Time in seconds after which a peer is considered stale
