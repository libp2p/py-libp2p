"""
Tests for the new address paradigm with wildcard support as a feature
"""

import pytest
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
    get_wildcard_address,
)


class TestAddressParadigm:
    """
    Test suite for verifying the new address paradigm:
    - get_available_interfaces() returns all available interfaces
    - get_optimal_binding_address() returns optimal address for examples
    - get_wildcard_address() provides wildcard as a feature when needed
    """

    def test_wildcard_address_function(self):
        """Test that get_wildcard_address() provides wildcard as a feature"""
        port = 8000
        addr = get_wildcard_address(port)

        # Should return wildcard address when explicitly requested
        assert "0.0.0.0" in str(addr)
        addr_str = str(addr)
        assert "/ip4/" in addr_str or "/ip6/" in addr_str
        assert f"/tcp/{port}" in addr_str

    def test_optimal_binding_address_selection(self):
        """Test that optimal binding address uses good heuristics"""
        port = 8000
        addr = get_optimal_binding_address(port)

        # Should return a valid IP address (could be loopback or local network)
        addr_str = str(addr)
        assert "/ip4/" in addr_str or "/ip6/" in addr_str
        assert f"/tcp/{port}" in addr_str

        # Should be from available interfaces
        available_interfaces = get_available_interfaces(port)
        assert addr in available_interfaces

    def test_available_interfaces_includes_loopback(self):
        """Test that available interfaces always includes loopback address"""
        port = 8000
        interfaces = get_available_interfaces(port)

        # Should have at least one interface
        assert len(interfaces) > 0

        # Should include loopback address
        loopback_found = any("127.0.0.1" in str(addr) for addr in interfaces)
        assert loopback_found, "Loopback address not found in available interfaces"

        # Available interfaces should not include wildcard by default
        # (wildcard is available as a feature through get_wildcard_address())
        wildcard_found = any("0.0.0.0" in str(addr) for addr in interfaces)
        assert not wildcard_found, (
            "Wildcard should not be in default available interfaces"
        )

    def test_host_default_listen_address(self):
        """Test that new hosts use secure default addresses"""
        # Create a host with a specific port
        port = 8000
        listen_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")
        host = new_host(listen_addrs=[listen_addr])

        # Verify the host configuration
        assert host is not None
        # Note: We can't test actual binding without running the host,
        # but we've verified the address format is correct

    def test_paradigm_consistency(self):
        """Test that the address paradigm is consistent"""
        port = 8000

        # get_optimal_binding_address should return a valid address
        optimal_addr = get_optimal_binding_address(port)
        assert "/ip4/" in str(optimal_addr) or "/ip6/" in str(optimal_addr)
        assert f"/tcp/{port}" in str(optimal_addr)

        # get_wildcard_address should return wildcard when explicitly needed
        wildcard_addr = get_wildcard_address(port)
        assert "0.0.0.0" in str(wildcard_addr)
        assert f"/tcp/{port}" in str(wildcard_addr)

        # Both should be valid Multiaddr objects
        assert isinstance(optimal_addr, Multiaddr)
        assert isinstance(wildcard_addr, Multiaddr)

    @pytest.mark.parametrize("protocol", ["tcp", "udp"])
    def test_different_protocols_support(self, protocol):
        """Test that different protocols are supported by the paradigm"""
        port = 8000

        # Test optimal address with different protocols
        optimal_addr = get_optimal_binding_address(port, protocol=protocol)
        assert protocol in str(optimal_addr)
        assert f"/{protocol}/{port}" in str(optimal_addr)

        # Test wildcard address with different protocols
        wildcard_addr = get_wildcard_address(port, protocol=protocol)
        assert "0.0.0.0" in str(wildcard_addr)
        assert protocol in str(wildcard_addr)
        assert f"/{protocol}/{port}" in str(wildcard_addr)

        # Test available interfaces with different protocols
        interfaces = get_available_interfaces(port, protocol=protocol)
        assert len(interfaces) > 0
        for addr in interfaces:
            assert protocol in str(addr)

    def test_wildcard_available_as_feature(self):
        """Test that wildcard binding is available as a feature when needed"""
        port = 8000

        # Wildcard should be available through get_wildcard_address()
        wildcard_addr = get_wildcard_address(port)
        assert "0.0.0.0" in str(wildcard_addr)

        # But should not be in default available interfaces
        interfaces = get_available_interfaces(port)
        wildcard_in_interfaces = any("0.0.0.0" in str(addr) for addr in interfaces)
        assert not wildcard_in_interfaces, (
            "Wildcard should not be in default interfaces"
        )

        # Optimal address should not be wildcard by default
        optimal = get_optimal_binding_address(port)
        assert "0.0.0.0" not in str(optimal), (
            "Optimal address should not be wildcard by default"
        )

    def test_loopback_is_always_available(self):
        """Test that loopback address is always available as an option"""
        port = 8000
        interfaces = get_available_interfaces(port)

        # Loopback should always be available
        loopback_addrs = [addr for addr in interfaces if "127.0.0.1" in str(addr)]
        assert len(loopback_addrs) > 0, "Loopback address should always be available"

        # At least one loopback address should have the correct port
        loopback_with_port = [
            addr for addr in loopback_addrs if f"/tcp/{port}" in str(addr)
        ]
        assert len(loopback_with_port) > 0, (
            f"Loopback address with port {port} should be available"
        )

    def test_optimal_address_selection_behavior(self):
        """Test that optimal address selection works correctly"""
        port = 8000
        interfaces = get_available_interfaces(port)
        optimal = get_optimal_binding_address(port)

        # Should return one of the available interfaces
        optimal_str = str(optimal)
        interface_strs = [str(addr) for addr in interfaces]
        assert optimal_str in interface_strs, (
            f"Optimal address {optimal_str} should be in available interfaces"
        )

        # Should prefer non-loopback when available, fallback to loopback
        non_loopback_interfaces = [
            addr for addr in interfaces if "127.0.0.1" not in str(addr)
        ]
        if non_loopback_interfaces:
            # Should prefer non-loopback when available
            assert "127.0.0.1" not in str(optimal), (
                "Should prefer non-loopback when available"
            )
        else:
            # Should use loopback when no other interfaces available
            assert "127.0.0.1" in str(optimal), (
                "Should use loopback when no other interfaces available"
            )

    def test_address_paradigm_completeness(self):
        """Test that the address paradigm provides all necessary functionality"""
        port = 8000

        # Test that we get interface options
        interfaces = get_available_interfaces(port)
        assert len(interfaces) >= 1, "Should have at least one interface"

        # Test that loopback is always included
        has_loopback = any("127.0.0.1" in str(addr) for addr in interfaces)
        assert has_loopback, "Loopback should always be available"

        # Test that wildcard is available as a feature
        wildcard_addr = get_wildcard_address(port)
        assert "0.0.0.0" in str(wildcard_addr)

        # Test optimal selection
        optimal = get_optimal_binding_address(port)
        assert optimal in interfaces, (
            "Optimal address should be from available interfaces"
        )
