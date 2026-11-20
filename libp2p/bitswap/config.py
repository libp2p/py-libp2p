"""
Bitswap configuration constants and defaults.
"""

from libp2p.custom_types import TProtocol

# Protocol IDs for different Bitswap versions
BITSWAP_PROTOCOL_V100 = TProtocol("/ipfs/bitswap/1.0.0")
BITSWAP_PROTOCOL_V110 = TProtocol("/ipfs/bitswap/1.1.0")
BITSWAP_PROTOCOL_V120 = TProtocol("/ipfs/bitswap/1.2.0")
BITSWAP_PROTOCOL_V130 = TProtocol("/ipfs/bitswap/1.3.0")

# All supported protocols (ordered from newest to oldest for negotiation)
BITSWAP_PROTOCOLS = [
    BITSWAP_PROTOCOL_V120,
    BITSWAP_PROTOCOL_V110,
    BITSWAP_PROTOCOL_V100,
]

# Default priority for wantlist entries
DEFAULT_PRIORITY = 1

# Maximum message size (4MiB as per spec)
MAX_MESSAGE_SIZE = 4 * 1024 * 1024

# Maximum block size (512 KB)
# Spec requires support for blocks up to 2 MiB; we use 512 KiB as a safe limit
# that balances memory usage with spec compliance.
MAX_BLOCK_SIZE = 512 * 1024

# Default timeout for operations (in seconds)
DEFAULT_TIMEOUT = 90

# Maximum number of concurrent block requests
MAX_CONCURRENT_REQUESTS = 100

# Default wantlist size
DEFAULT_WANTLIST_SIZE = 256

# Per-peer queue bounds. A peer that stops reading, or that was never
# reachable in the first place, must not be able to grow these without limit.
MAX_PENDING_WANTS_PER_PEER = 1024
MAX_PENDING_BLOCKS_PER_PEER = 256
MAX_PENDING_BLOCK_BYTES_PER_PEER = 8 * 1024 * 1024

# Maximum inbound wantlist entries retained for a single connected peer.
# Entries are removed by cancel messages, a full wantlist, or disconnect;
# this cap protects against a peer that never cancels anything.
MAX_PEER_WANTLIST_ENTRIES = 4096

# CID version defaults
DEFAULT_CID_VERSION = 0  # CIDv0 for v1.0.0 compatibility
