"""
Bitswap configuration constants and defaults.
"""

# Protocol IDs for different Bitswap versions
BITSWAP_PROTOCOL_V100 = "/ipfs/bitswap/1.0.0"
BITSWAP_PROTOCOL_V110 = "/ipfs/bitswap/1.1.0"
BITSWAP_PROTOCOL_V120 = "/ipfs/bitswap/1.2.0"

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

# Maximum block size (2MiB as per spec)
MAX_BLOCK_SIZE = 2 * 1024 * 1024

# Default timeout for operations (in seconds)
DEFAULT_TIMEOUT = 30

# Maximum number of concurrent block requests
MAX_CONCURRENT_REQUESTS = 100

# Default wantlist size
DEFAULT_WANTLIST_SIZE = 256

# CID version defaults
DEFAULT_CID_VERSION = 0  # CIDv0 for v1.0.0 compatibility
