"""
Unit tests for connection management components.

Tests for dial queue, reconnection queue, rate limiter, connection gate,
address manager, and DNS resolver.
"""

import pytest
from multiaddr import Multiaddr

from libp2p.network.address_manager import AddressManager, default_address_sorter
from libp2p.network.config import ConnectionConfig
from libp2p.network.connection_gate import ConnectionGate
from libp2p.network.connection_state import ConnectionState, ConnectionStatus
from libp2p.network.dns_resolver import DNSResolver
from libp2p.network.rate_limiter import ConnectionRateLimiter


class TestConnectionState:
    """Test connection state management."""

    def test_connection_status_enum(self):
        """Test ConnectionStatus enum values."""
        assert ConnectionStatus.PENDING.value == "pending"
        assert ConnectionStatus.OPEN.value == "open"
        assert ConnectionStatus.CLOSING.value == "closing"
        assert ConnectionStatus.CLOSED.value == "closed"

    def test_connection_state_defaults(self):
        """Test ConnectionState default values."""
        state = ConnectionState()
        assert state.status == ConnectionStatus.PENDING
        assert state.timeline.open > 0

    def test_connection_state_set_status(self):
        """Test setting connection status."""
        state = ConnectionState()
        state.set_status(ConnectionStatus.OPEN)
        assert state.status == ConnectionStatus.OPEN

        state.set_status(ConnectionStatus.CLOSED)
        assert state.status == ConnectionStatus.CLOSED
        assert state.timeline.close is not None

    def test_connection_state_to_dict(self):
        """Test converting connection state to dictionary."""
        state = ConnectionState()
        state.set_status(ConnectionStatus.OPEN)
        state_dict = state.to_dict()

        assert state_dict["status"] == "open"
        assert "timeline" in state_dict
        assert "open" in state_dict["timeline"]


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_rate_limiter_initialization(self):
        """Test rate limiter initialization."""
        limiter = ConnectionRateLimiter(points=5, duration=1.0)
        assert limiter._limiter.points == 5
        assert limiter._limiter.duration == 1.0

    def test_rate_limiter_check_and_consume(self):
        """Test rate limit checking and consumption."""
        limiter = ConnectionRateLimiter(points=2, duration=1.0)

        # First two should succeed
        assert limiter.check_and_consume("192.168.1.1") is True
        assert limiter.check_and_consume("192.168.1.1") is True

        # Third should fail (exceeds limit)
        assert limiter.check_and_consume("192.168.1.1") is False

    def test_rate_limiter_reset(self):
        """Test resetting rate limiter."""
        limiter = ConnectionRateLimiter(points=1, duration=1.0)

        # Consume limit
        assert limiter.check_and_consume("192.168.1.1") is True
        assert limiter.check_and_consume("192.168.1.1") is False

        # Reset and try again
        limiter.reset("192.168.1.1")
        assert limiter.check_and_consume("192.168.1.1") is True

    def test_rate_limiter_per_host(self):
        """Test rate limiting per host."""
        limiter = ConnectionRateLimiter(points=1, duration=1.0)

        # Different hosts should be independent
        assert limiter.check_and_consume("192.168.1.1") is True
        assert limiter.check_and_consume("192.168.1.2") is True
        assert limiter.check_and_consume("192.168.1.1") is False
        assert limiter.check_and_consume("192.168.1.2") is False


class TestConnectionGate:
    """Test connection gate (IP allow/deny lists)."""

    def test_connection_gate_deny_list(self):
        """Test deny list functionality."""
        gate = ConnectionGate(
            allow_list=None, deny_list=["192.168.1.1"], allow_private_addresses=True
        )

        denied_addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        allowed_addr = Multiaddr("/ip4/192.168.1.2/tcp/1234")

        assert gate.is_allowed(denied_addr) is False
        assert gate.is_allowed(allowed_addr) is True

    def test_connection_gate_allow_list(self):
        """Test allow list functionality."""
        gate = ConnectionGate(
            allow_list=["192.168.1.1"], deny_list=None, allow_private_addresses=True
        )

        allowed_addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        denied_addr = Multiaddr("/ip4/192.168.1.2/tcp/1234")

        assert gate.is_allowed(allowed_addr) is True
        assert gate.is_allowed(denied_addr) is False

    def test_connection_gate_cidr_blocks(self):
        """Test CIDR block support."""
        gate = ConnectionGate(
            allow_list=["192.168.1.0/24"], deny_list=None, allow_private_addresses=True
        )

        addr1 = Multiaddr("/ip4/192.168.1.10/tcp/1234")
        addr2 = Multiaddr("/ip4/192.168.2.10/tcp/1234")

        assert gate.is_allowed(addr1) is True
        assert gate.is_allowed(addr2) is False

    def test_connection_gate_deny_takes_precedence(self):
        """Test that deny list takes precedence over allow list."""
        gate = ConnectionGate(
            allow_list=["192.168.1.1"],
            deny_list=["192.168.1.1"],
            allow_private_addresses=True,
        )

        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        assert gate.is_allowed(addr) is False  # Deny takes precedence

    def test_connection_gate_dynamic_updates(self):
        """Test dynamic allow/deny list updates."""
        gate = ConnectionGate(allow_list=None, deny_list=None)

        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        assert gate.is_allowed(addr) is True  # No restrictions

        gate.add_to_deny_list("192.168.1.1")
        assert gate.is_allowed(addr) is False

        gate.remove_from_deny_list("192.168.1.1")
        assert gate.is_allowed(addr) is True


class TestAddressManager:
    """Test address manager functionality."""

    def test_address_manager_default_sorter(self):
        """Test default address sorting."""
        manager = AddressManager()
        addrs = [
            Multiaddr("/ip4/127.0.0.1/tcp/1234"),  # Loopback
            Multiaddr("/ip4/192.168.1.1/tcp/1234"),  # Private
            Multiaddr("/ip4/8.8.8.8/tcp/1234"),  # Public
        ]

        sorted_addrs = manager.sort_addresses(addrs)
        # Public addresses should come first
        assert sorted_addrs[0] == Multiaddr("/ip4/8.8.8.8/tcp/1234")

    def test_address_manager_prepare_addresses(self):
        """Test address preparation (filter, sort, limit)."""
        manager = AddressManager()
        addrs = [
            Multiaddr("/ip4/127.0.0.1/tcp/1234"),
            Multiaddr("/ip4/192.168.1.1/tcp/1234"),
            Multiaddr("/ip4/8.8.8.8/tcp/1234"),
        ]

        prepared = manager.prepare_addresses(addrs, max_addresses=2)
        assert len(prepared) == 2
        # Should be sorted (public first)
        assert prepared[0] == Multiaddr("/ip4/8.8.8.8/tcp/1234")

    def test_address_manager_custom_sorter(self):
        """Test custom address sorter."""

        def reverse_sorter(addresses):
            return list(reversed(addresses))

        manager = AddressManager(address_sorter=reverse_sorter)
        addrs = [
            Multiaddr("/ip4/192.168.1.1/tcp/1234"),
            Multiaddr("/ip4/8.8.8.8/tcp/1234"),
        ]

        sorted_addrs = manager.sort_addresses(addrs)
        assert sorted_addrs[0] == Multiaddr("/ip4/8.8.8.8/tcp/1234")

    def test_default_address_sorter_function(self):
        """Test default_address_sorter standalone function."""
        addrs = [
            Multiaddr("/ip4/127.0.0.1/tcp/1234"),
            Multiaddr("/ip4/8.8.8.8/tcp/1234"),
        ]

        sorted_addrs = default_address_sorter(addrs)
        # Public addresses should come before loopback
        assert sorted_addrs[0] == Multiaddr("/ip4/8.8.8.8/tcp/1234")


class TestDNSResolver:
    """Test DNS resolver functionality."""

    @pytest.mark.asyncio
    async def test_dns_resolver_initialization(self):
        """Test DNS resolver initialization."""
        resolver = DNSResolver(max_recursion_depth=32)
        assert resolver.max_recursion_depth == 32

    @pytest.mark.asyncio
    async def test_dns_resolver_non_dns_address(self):
        """Test resolver with non-DNS address."""
        resolver = DNSResolver()
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        resolved = await resolver.resolve(addr)

        # Non-DNS address should return as-is
        assert len(resolved) == 1
        assert resolved[0] == addr

    @pytest.mark.asyncio
    async def test_dns_resolver_cache(self):
        """Test DNS resolver caching."""
        resolver = DNSResolver()
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")

        # First resolution
        resolved1 = await resolver.resolve(addr)
        # Second resolution should use cache
        resolved2 = await resolver.resolve(addr)

        assert resolved1 == resolved2

    @pytest.mark.asyncio
    async def test_dns_resolver_clear_cache(self):
        """Test clearing DNS cache."""
        resolver = DNSResolver()
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")

        await resolver.resolve(addr)
        assert len(resolver._cache) > 0

        resolver.clear_cache()
        assert len(resolver._cache) == 0


class TestConnectionConfig:
    """Test connection configuration."""

    def test_connection_config_defaults(self):
        """Test default configuration values."""
        config = ConnectionConfig()
        assert config.max_connections == 300
        assert config.max_parallel_dials == 100
        assert config.dial_timeout == 10.0
        assert config.inbound_connection_threshold == 5

    def test_connection_config_custom_values(self):
        """Test custom configuration values."""
        config = ConnectionConfig(
            max_connections=500,
            max_parallel_dials=50,
            dial_timeout=5.0,
        )
        assert config.max_connections == 500
        assert config.max_parallel_dials == 50
        assert config.dial_timeout == 5.0

    def test_connection_config_allow_deny_lists(self):
        """Test allow/deny list configuration."""
        config = ConnectionConfig(
            allow_list=["192.168.1.0/24"],
            deny_list=["192.168.1.100"],
        )
        assert len(config.allow_list) == 1
        assert len(config.deny_list) == 1
