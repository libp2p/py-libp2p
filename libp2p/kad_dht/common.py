"""
Shared constants and protocol parameters for the Kademlia DHT.
"""

from datetime import datetime, timezone
import ipaddress

from libp2p.custom_types import (
    TProtocol,
)

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

# Default parameters
BUCKET_SIZE = 20  # k in the Kademlia paper
MAXIMUM_BUCKETS = 256  # Maximum number of buckets (for 256-bit keys)
PEER_REFRESH_INTERVAL = 60  # Interval to refresh peers in seconds
STALE_PEER_THRESHOLD = 3600  # Time in seconds after which a peer is considered stale

# Reserved IP ranges per RFC 6890 / IANA
_RESERVED_PREFIXES = [
    ipaddress.ip_network("0.0.0.0/8"),  # "This" network
    ipaddress.ip_network("10.0.0.0/8"),  # Private
    ipaddress.ip_network("100.64.0.0/10"),  # Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-Local
    ipaddress.ip_network("172.16.0.0/12"),  # Private
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # Documentation (TEST-NET-1)
    ipaddress.ip_network("192.88.99.0/24"),  # 6to4 Relay Anycast
    ipaddress.ip_network("192.168.0.0/16"),  # Private
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # Documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),  # Documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
]


def is_reserved_or_private_addr(addr_str: str) -> bool:
    """Check if an address string is a reserved or private IP address."""
    try:
        # Extract IP from multiaddr string (e.g., "/ip4/127.0.0.1/tcp/4001")
        parts = addr_str.split("/")
        ip_str = None
        for i, part in enumerate(parts):
            if part in ("ip4", "ip6") and i + 1 < len(parts):
                ip_str = parts[i + 1]
                break
        if ip_str is None:
            return True  # Can't parse = reject

        addr = ipaddress.ip_address(ip_str)

        # Check IPv6 loopback (::1) and unspecified (::)
        if addr.is_loopback or addr.is_unspecified:
            return True

        # Check IPv6 link-local and ULA
        if isinstance(addr, ipaddress.IPv6Address):
            if addr.is_link_local:
                return True  # fe80::/10
            # fc00::/7 (Unique Local Addresses)
            if int(addr) & 0xFE00_0000_0000_0000 == 0xFC00_0000_0000_0000:
                return True

        # Check against reserved prefixes
        for prefix in _RESERVED_PREFIXES:
            if addr in prefix:
                return True

        return False
    except (ValueError, IndexError):
        return True  # Can't parse = reject


def is_cid_like_key(key: bytes) -> bool:
    """
    Check if a key looks like a valid CID or multihash.

    Per spec, ADD_PROVIDER and GET_PROVIDERS keys SHOULD be CIDs.
    A CID v1 has the structure: <version><codec><multihash>
    - version: 0x01 for CIDv1
    - codec: varint (typically 0x55 for raw, 0x71 for dag-pb, etc.)
    - multihash: <hash-function-code><digest-length><digest>

    We accept:
    - Valid CIDv1 keys
    - Raw multihash keys (common in DHT implementations)
    - Reasonable-length byte sequences (for backward compatibility)

    Only reject obviously invalid keys (empty, too short, or extremely long).
    """
    if not key:
        return False

    # Per spec, key length must be > 0 and <= 80
    if len(key) > 80:
        return False

    # CIDv1 starts with 0x01
    if key[0] == 0x01:
        return len(key) >= 5

    # CIDv0 (base58btc-encoded multihash) is typically 46 bytes starting with Qm
    if len(key) == 46 and key[0:2] == b"Qm":
        return True

    # Raw multihash: starts with hash function code varint
    # Common codes: sha2-256=0x12, sha2-512=0x13, sha3-256=0x16, etc.
    # These are typically 2 bytes for the code + 1 byte for length + 32 bytes
    if len(key) >= 4:
        # Check if first byte looks like a multihash function code
        first_byte = key[0]
        # Common hash function codes (varint encoded)
        valid_hash_codes = {
            0x12,  # sha2-256
            0x13,  # sha2-512
            0x16,  # sha3-256
            0x17,  # sha3-512
            0x22,  # blake2b-256
        }
        if first_byte in valid_hash_codes:
            return True

    # For backward compatibility, accept any reasonable-length key
    # (the DHT should work with arbitrary keys for testing/custom use)
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
