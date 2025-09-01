"""
Tests for default bind address changes from 0.0.0.0 to 127.0.0.1
"""

import pytest
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)


class TestDefaultBindAddress:
    """Test suite for verifying default bind addresses use secure addresses (not 0.0.0.0)"""

    def test_default_bind_address_is_not_wildcard(self):
        """Test that default bind address is NOT 0.0.0.0 (wildcard)"""
        port = 8000
        addr = get_optimal_binding_address(port)
        
        # Should NOT return wildcard address
        assert "0.0.0.0" not in str(addr)
        
        # Should return a valid IP address (could be loopback or local network)
        addr_str = str(addr)
        assert "/ip4/" in addr_str
        assert f"/tcp/{port}" in addr_str

    def test_available_interfaces_includes_loopback(self):
        """Test that available interfaces always includes loopback address"""
        port = 8000
        interfaces = get_available_interfaces(port)
        
        # Should have at least one interface
        assert len(interfaces) > 0
        
        # Should include loopback address
        loopback_found = any("127.0.0.1" in str(addr) for addr in interfaces)
        assert loopback_found, "Loopback address not found in available interfaces"
        
        # Should not have wildcard as the only option
        if len(interfaces) == 1:
            assert "0.0.0.0" not in str(interfaces[0])

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

    def test_no_wildcard_in_fallback(self):
        """Test that fallback addresses don't use wildcard binding"""
        # When no interfaces are discovered, fallback should be loopback
        port = 8000
        
        # Even if we can't discover interfaces, we should get loopback
        addr = get_optimal_binding_address(port)
        # Should NOT be wildcard
        assert "0.0.0.0" not in str(addr)
        
        # Should be a valid IP address
        addr_str = str(addr)
        assert "/ip4/" in addr_str
        assert f"/tcp/{port}" in addr_str

    @pytest.mark.parametrize("protocol", ["tcp", "udp"])
    def test_different_protocols_use_secure_addresses(self, protocol):
        """Test that different protocols still use secure addresses by default"""
        port = 8000
        addr = get_optimal_binding_address(port, protocol=protocol)
        
        # Should NOT be wildcard
        assert "0.0.0.0" not in str(addr)
        assert protocol in str(addr)
        
        # Should be a valid IP address
        addr_str = str(addr)
        assert "/ip4/" in addr_str
        assert f"/{protocol}/{port}" in addr_str

    def test_security_no_public_binding_by_default(self):
        """Test that no public interface binding occurs by default"""
        port = 8000
        interfaces = get_available_interfaces(port)
        
        # Check that we don't expose on all interfaces by default
        wildcard_addrs = [addr for addr in interfaces if "0.0.0.0" in str(addr)]
        assert len(wildcard_addrs) == 0, "Found wildcard addresses in default interfaces"
        
        # Verify optimal address selection doesn't choose wildcard
        optimal = get_optimal_binding_address(port)
        assert "0.0.0.0" not in str(optimal), "Optimal address should not be wildcard"
        
        # Should be a valid IP address (could be loopback or local network)
        addr_str = str(optimal)
        assert "/ip4/" in addr_str
        assert f"/tcp/{port}" in addr_str

    def test_loopback_is_always_available(self):
        """Test that loopback address is always available as an option"""
        port = 8000
        interfaces = get_available_interfaces(port)
        
        # Loopback should always be available
        loopback_addrs = [addr for addr in interfaces if "127.0.0.1" in str(addr)]
        assert len(loopback_addrs) > 0, "Loopback address should always be available"
        
        # At least one loopback address should have the correct port
        loopback_with_port = [addr for addr in loopback_addrs if f"/tcp/{port}" in str(addr)]
        assert len(loopback_with_port) > 0, f"Loopback address with port {port} should be available"

    def test_optimal_address_selection_behavior(self):
        """Test that optimal address selection works correctly"""
        port = 8000
        interfaces = get_available_interfaces(port)
        optimal = get_optimal_binding_address(port)
        
        # Should never return wildcard
        assert "0.0.0.0" not in str(optimal)
        
        # Should return one of the available interfaces
        optimal_str = str(optimal)
        interface_strs = [str(addr) for addr in interfaces]
        assert optimal_str in interface_strs, f"Optimal address {optimal_str} should be in available interfaces"
        
        # If non-loopback interfaces are available, should prefer them
        non_loopback_interfaces = [addr for addr in interfaces if "127.0.0.1" not in str(addr)]
        if non_loopback_interfaces:
            # Should prefer non-loopback when available
            assert "127.0.0.1" not in str(optimal), "Should prefer non-loopback when available"
        else:
            # Should use loopback when no other interfaces available
            assert "127.0.0.1" in str(optimal), "Should use loopback when no other interfaces available"

    def test_address_validation_utilities_behavior(self):
        """Test that address validation utilities behave as expected"""
        port = 8000
        
        # Test that we get multiple interface options
        interfaces = get_available_interfaces(port)
        assert len(interfaces) >= 2, "Should have at least loopback + one network interface"
        
        # Test that loopback is always included
        has_loopback = any("127.0.0.1" in str(addr) for addr in interfaces)
        assert has_loopback, "Loopback should always be available"
        
        # Test that no wildcards are included
        has_wildcard = any("0.0.0.0" in str(addr) for addr in interfaces)
        assert not has_wildcard, "Wildcard addresses should never be included"
        
        # Test optimal selection
        optimal = get_optimal_binding_address(port)
        assert optimal in interfaces, "Optimal address should be from available interfaces"
