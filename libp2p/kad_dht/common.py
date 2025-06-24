"""
Shared constants and protocol parameters for the Kademlia DHT.
"""

from libp2p.custom_types import (
    TProtocol,
)

# Constants for the Kademlia algorithm
ALPHA = 3  # Concurrency parameter
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")
QUERY_TIMEOUT = 10

TTL = DEFAULT_TTL = 24 * 60 * 60  # 24 hours in seconds
