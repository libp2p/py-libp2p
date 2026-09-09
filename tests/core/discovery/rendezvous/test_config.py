"""
Tests for rendezvous configuration and constants.
"""

from libp2p.discovery.rendezvous.config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_DISCOVER_LIMIT,
    DEFAULT_NAMESPACE,
    DEFAULT_TIMEOUT,
    DEFAULT_TTL,
    MAX_DISCOVER_LIMIT,
    MAX_NAMESPACE_LENGTH,
    MAX_PEER_ADDRESS_LENGTH,
    MAX_REGISTRATIONS,
    MAX_TTL,
    MIN_TTL,
    RENDEZVOUS_PROTOCOL,
)


class TestConfig:
    """Test cases for rendezvous configuration constants."""

    def test_protocol_constant(self):
        """Test protocol constant is correct."""
        assert RENDEZVOUS_PROTOCOL == "/rendezvous/1.0.0"
        assert isinstance(RENDEZVOUS_PROTOCOL, str)

    def test_ttl_constants(self):
        """Test TTL constants are sensible."""
        assert MIN_TTL == 120  # 2 minutes
        assert DEFAULT_TTL == 2 * 3600  # 2 hours
        assert MAX_TTL == 72 * 3600  # 72 hours

        # Verify ordering
        assert MIN_TTL < DEFAULT_TTL < MAX_TTL

    def test_namespace_constants(self):
        """Test namespace constants."""
        assert MAX_NAMESPACE_LENGTH == 256
        assert DEFAULT_NAMESPACE == "rendezvous"
        assert len(DEFAULT_NAMESPACE) <= MAX_NAMESPACE_LENGTH

    def test_discovery_constants(self):
        """Test discovery constants."""
        assert DEFAULT_DISCOVER_LIMIT == 100
        assert MAX_DISCOVER_LIMIT == 1000

        # Verify ordering
        assert DEFAULT_DISCOVER_LIMIT <= MAX_DISCOVER_LIMIT

    def test_peer_info_constants(self):
        """Test peer information constants."""
        assert MAX_PEER_ADDRESS_LENGTH == 2048
        assert MAX_REGISTRATIONS == 1000

        # These should be positive
        assert MAX_PEER_ADDRESS_LENGTH > 0
        assert MAX_REGISTRATIONS > 0

    def test_network_constants(self):
        """Test network configuration constants."""
        assert DEFAULT_TIMEOUT == 30.0
        assert isinstance(DEFAULT_TIMEOUT, float)
        assert DEFAULT_TIMEOUT > 0

    def test_cache_constants(self):
        """Test cache configuration constants."""
        assert DEFAULT_CACHE_TTL == 300
        assert isinstance(DEFAULT_CACHE_TTL, int)
        assert DEFAULT_CACHE_TTL > 0

    def test_constants_types(self):
        """Test that constants have expected types."""
        # Protocol should be string
        assert isinstance(RENDEZVOUS_PROTOCOL, str)

        # TTL values should be integers
        assert isinstance(MIN_TTL, int)
        assert isinstance(DEFAULT_TTL, int)
        assert isinstance(MAX_TTL, int)

        # Namespace values
        assert isinstance(MAX_NAMESPACE_LENGTH, int)
        assert isinstance(DEFAULT_NAMESPACE, str)

        # Discovery values should be integers
        assert isinstance(DEFAULT_DISCOVER_LIMIT, int)
        assert isinstance(MAX_DISCOVER_LIMIT, int)

        # Other constants
        assert isinstance(MAX_PEER_ADDRESS_LENGTH, int)
        assert isinstance(MAX_REGISTRATIONS, int)
        assert isinstance(DEFAULT_TIMEOUT, float)
        assert isinstance(DEFAULT_CACHE_TTL, int)

    def test_constants_reasonable_values(self):
        """Test that constants have reasonable values."""
        # TTL values should be positive
        assert MIN_TTL > 0
        assert DEFAULT_TTL > 0
        assert MAX_TTL > 0

        # Namespace length should be reasonable
        assert MAX_NAMESPACE_LENGTH > 10
        assert MAX_NAMESPACE_LENGTH < 10000

        # Discovery limits should be reasonable
        assert DEFAULT_DISCOVER_LIMIT > 0
        assert DEFAULT_DISCOVER_LIMIT <= MAX_DISCOVER_LIMIT
        assert MAX_DISCOVER_LIMIT < 100000  # Not too high

        # Peer info limits should be reasonable
        assert MAX_PEER_ADDRESS_LENGTH > 100  # Large enough for addresses
        assert MAX_REGISTRATIONS > 10  # Allow reasonable number of registrations

        # Network timeout should be reasonable
        assert DEFAULT_TIMEOUT >= 1.0  # At least 1 second
        assert DEFAULT_TIMEOUT <= 300.0  # Not more than 5 minutes

        # Cache TTL should be reasonable
        assert DEFAULT_CACHE_TTL >= 60  # At least 1 minute
        assert DEFAULT_CACHE_TTL <= 3600  # Not more than 1 hour
