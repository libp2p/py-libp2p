"""
Configuration constants for the rendezvous protocol implementation.

This module contains all protocol constants, limits, and configuration
values used throughout the rendezvous implementation.
"""

from libp2p.custom_types import TProtocol

# Protocol Configuration
RENDEZVOUS_PROTOCOL = TProtocol("/rendezvous/1.0.0")

# TTL (Time To Live) Configuration
MAX_TTL = 72 * 3600  # 72 hours in seconds
MIN_TTL = 120       # 2 minutes in seconds  
DEFAULT_TTL = 3600  # 1 hour in seconds

# Namespace Configuration
MAX_NAMESPACE_LENGTH = 256
DEFAULT_NAMESPACE = "rendezvous"

# Discovery Configuration
MAX_DISCOVER_LIMIT = 1000
DEFAULT_DISCOVER_LIMIT = 100

# Peer Information Limits
MAX_PEER_ADDRESS_LENGTH = 2048
MAX_REGISTRATIONS = 1000

# Network Configuration
DEFAULT_TIMEOUT = 30.0  # seconds
MAX_MESSAGE_SIZE = 4096  # bytes

# Cache Configuration
DEFAULT_CACHE_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 1000

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds
BACKOFF_MULTIPLIER = 2.0

# Pagination Configuration  
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

# Registration Cleanup
CLEANUP_INTERVAL = 60  # seconds
STALE_THRESHOLD = 300  # 5 minutes
