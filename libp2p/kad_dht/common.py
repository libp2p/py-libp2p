"""
Shared constants and protocol parameters for the Kademlia DHT.
"""

from datetime import datetime, timezone
import ipaddress
import logging

import cid
import multihash

from libp2p.custom_types import (
    TProtocol,
)

logger = logging.getLogger(__name__)

# Constants for the Kademlia algorithm
ALPHA = 10  # Concurrency parameter (per libp2p Kademlia spec)
BETA = 3  # Resiliency parameter: min closest peers to query before termination
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")
PROTOCOL_PREFIX = TProtocol("/ipfs")
QUERY_TIMEOUT = 10
MAX_RECORD_AGE = 48 * 60 * 60  # 48 hours in seconds (go-libp2p default)
MAX_RECORD_SIZE = 1024 * 1024  # 1MB max record size
MAX_PROVIDERS_PER_MSG = 20  # Max provider records per ADD_PROVIDER message
MAX_VALUE_STORE_SIZE = 50000  # Max entries in value store

TTL = DEFAULT_TTL = 24 * 60 * 60  # 24 hours in seconds

# Cap on varint-prefixed DHT RPC payloads. Reject larger claimed lengths before
# reading to avoid remote memory exhaustion (GHSA-xqvc-92cf-94j4).
MAX_DHT_MESSAGE_SIZE = 4 * 1024 * 1024  # 4 MiB

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


def is_reserved_or_private_addr(addr_str: str) -> bool:
    """Check if an address string is a reserved or private IP address."""
    try:
        parts = addr_str.split("/")
        ip_str = None
        for i, part in enumerate(parts):
            if part in ("ip4", "ip6") and i + 1 < len(parts):
                ip_str = parts[i + 1]
                break
        if ip_str is None:
            return True

        addr = ipaddress.ip_address(ip_str)
        return not addr.is_global
    except (ValueError, IndexError):
        return True


def is_cid_like_key(key: bytes) -> bool:
    """Check if a key looks like a valid CID or multihash using py-cid/multihash."""
    if not key or len(key) > 128:
        return False

    try:
        if cid.is_cid(key):
            return True
    except Exception:
        pass

    try:
        if multihash.is_valid(key):
            return True
    except Exception:
        pass

    # Accept arbitrary reasonable-length keys for backward compatibility
    return 4 <= len(key) <= 64


def format_time_rfc3339(dt: datetime | None = None) -> str:
    """
    Format a datetime as RFC3339Nano string.

    Per spec, timeReceived MUST be formatted according to RFC3339.
    go-libp2p uses time.RFC3339Nano which produces strings like:
    "2024-11-23T12:34:56.789012345Z"
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Format as RFC3339Nano (trailing Z for UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond * 1000:09d}Z"


def parse_time_received(time_str: str) -> float | None:
    """
    Parse a timeReceived string and return Unix timestamp.

    Supports both:
    - RFC3339 format from go-libp2p (e.g., "2024-11-23T12:34:56.789012345Z")
    - Unix epoch float format (legacy, e.g., "1700000000.123456")

    Returns None if parsing fails.
    """
    if not time_str:
        return None

    # Try RFC3339 first (spec-compliant)
    try:
        # Handle various RFC3339 formats
        s = time_str.rstrip("Z").rstrip("z")
        # Handle nanosecond precision by truncating to microseconds
        if "." in s:
            base, frac = s.split(".", 1)
            # Remove trailing timezone marker if present
            frac = frac.rstrip("Z").rstrip("z")
            # Truncate to 6 digits for Python (microseconds)
            frac = frac[:6].ljust(6, "0")
            s = f"{base}.{frac}"
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        pass

    # Try Unix epoch float (legacy format)
    try:
        return float(time_str)
    except (ValueError, TypeError):
        return None
