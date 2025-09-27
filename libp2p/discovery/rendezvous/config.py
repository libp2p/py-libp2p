"""
Configuration constants for the rendezvous protocol implementation.

This module contains all protocol constants, limits, and configuration
values used throughout the rendezvous implementation.
"""

from libp2p.custom_types import TProtocol

# Protocol Configuration
RENDEZVOUS_PROTOCOL = TProtocol("/rendezvous/1.0.0")

# TTL (Time To Live) Configuration
DEFAULT_TTL = 2 * 3600  # 2 hours
MAX_TTL = 72 * 3600  # 72 hours
MIN_TTL = 120  # 2 minutes

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
DEFAULT_TIMEOUT = 30.0

# Cache Configuration
DEFAULT_CACHE_TTL = 300
