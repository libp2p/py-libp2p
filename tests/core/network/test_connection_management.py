"""
Unit tests for connection management components (go-libp2p style).
"""

import pytest
from multiaddr import Multiaddr

from libp2p.network.config import ConnectionConfig
from libp2p.network.connection_gate import (
    ConnectionGate,
    extract_ip_from_multiaddr,
)


@pytest.mark.trio
class TestExtractIpFromMultiaddr:
    async def test_extract_ipv4(self):
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        assert ips == ["192.168.1.1"]

    async def test_extract_ipv6(self):
        addr = Multiaddr("/ip6/::1/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        assert ips == ["::1"]

    async def test_dns4_resolution(self):
        # Test with localhost which should resolve
        addr = Multiaddr("/dns4/localhost/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        # localhost should resolve to at least one IP
        assert len(ips) > 0
        # Should contain 127.0.0.1
        assert "127.0.0.1" in ips

    async def test_dns6_resolution(self):
        # Test with localhost IPv6
        addr = Multiaddr("/dns6/localhost/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        # Should resolve to IPv6 addresses
        assert len(ips) > 0
        # Should contain ::1 for localhost
        assert "::1" in ips

    async def test_dnsaddr_resolution(self):
        # Test with dnsaddr (can resolve to both IPv4 and IPv6)
        addr = Multiaddr("/dnsaddr/localhost/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        # localhost should resolve to at least one IP
        assert len(ips) > 0
        # Should contain either 127.0.0.1 or ::1
        assert "127.0.0.1" in ips or "::1" in ips

    async def test_invalid_dns(self):
        # Test with invalid DNS name
        addr = Multiaddr("/dns4/this-domain-does-not-exist-12345.com/tcp/1234")
        ips = await extract_ip_from_multiaddr(addr)
        # Should return empty list on resolution failure
        assert ips == []

    async def test_p2p_circuit_address(self):
        # Test with p2p-circuit address (no IP to extract)
        addr = Multiaddr(
            "/p2p-circuit/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
        ips = await extract_ip_from_multiaddr(addr)
        # Should return empty list for circuit addresses
        assert ips == []

    async def test_complex_multiaddr_with_dns(self):
        # Test complex multiaddr with dns4
        addr = Multiaddr(
            "/dns4/example.com/tcp/4001/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
        ips = await extract_ip_from_multiaddr(addr)
        # Should resolve example.com
        assert len(ips) > 0


@pytest.mark.trio
class TestConnectionGate:
    async def test_deny_list(self):
        gate = ConnectionGate(deny_list=["192.168.1.1"], allow_private_addresses=True)
        denied = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        allowed = Multiaddr("/ip4/192.168.1.2/tcp/1234")
        assert await gate.is_allowed(denied) is False
        assert await gate.is_allowed(allowed) is True

    async def test_allow_list(self):
        gate = ConnectionGate(allow_list=["192.168.1.1"], allow_private_addresses=True)
        allowed = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        denied = Multiaddr("/ip4/192.168.1.2/tcp/1234")
        assert await gate.is_allowed(allowed) is True
        assert await gate.is_allowed(denied) is False

    async def test_cidr_blocks(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.0/24"], allow_private_addresses=True
        )
        addr1 = Multiaddr("/ip4/192.168.1.10/tcp/1234")
        addr2 = Multiaddr("/ip4/192.168.2.10/tcp/1234")
        assert await gate.is_allowed(addr1) is True
        assert await gate.is_allowed(addr2) is False

    async def test_deny_takes_precedence(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.1"],
            deny_list=["192.168.1.1"],
            allow_private_addresses=True,
        )
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        assert await gate.is_allowed(addr) is False

    async def test_non_ip_addresses_allowed_by_default(self):
        gate = ConnectionGate(allow_private_addresses=True)
        # Circuit relay addresses should be allowed when no allow list
        circuit_addr = Multiaddr(
            "/p2p-circuit/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
        assert await gate.is_allowed(circuit_addr) is True

    async def test_dns_with_deny_list(self):
        # Create a gate that denies localhost IPs
        gate = ConnectionGate(deny_list=["127.0.0.1"], allow_private_addresses=True)
        dns_addr = Multiaddr("/dns4/localhost/tcp/1234")
        # Should be denied because localhost resolves to 127.0.0.1
        result = await gate.is_allowed(dns_addr)
        assert result is False

    async def test_dns_with_allow_list(self):
        # Create a gate with an allow list
        gate = ConnectionGate(allow_list=["127.0.0.1"], allow_private_addresses=True)
        dns_addr = Multiaddr("/dns4/localhost/tcp/1234")
        # Should be allowed because localhost resolves to 127.0.0.1
        result = await gate.is_allowed(dns_addr)
        assert result is True

    async def test_dns4_resolution_allowed(self):
        gate = ConnectionGate(allow_private_addresses=True)
        dns_addr = Multiaddr("/dns4/localhost/tcp/1234")
        # Should be allowed after resolving to 127.0.0.1
        result = await gate.is_allowed(dns_addr)
        assert result is True

    async def test_dns6_resolution_allowed(self):
        gate = ConnectionGate(allow_private_addresses=True)
        dns_addr = Multiaddr("/dns6/localhost/tcp/1234")
        # Should be allowed after resolving to ::1
        result = await gate.is_allowed(dns_addr)
        assert result is True

    async def test_dnsaddr_resolution_allowed(self):
        gate = ConnectionGate(allow_private_addresses=True)
        dns_addr = Multiaddr("/dnsaddr/localhost/tcp/1234")
        # Should be allowed after DNS resolution
        result = await gate.is_allowed(dns_addr)
        assert result is True

    async def test_circuit_relay_allowed_no_allow_list(self):
        gate = ConnectionGate(allow_private_addresses=True)
        # Circuit relay should be allowed when no allow list is configured
        circuit_addr = Multiaddr(
            "/p2p-circuit/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
        result = await gate.is_allowed(circuit_addr)
        assert result is True

    async def test_circuit_relay_denied_with_allow_list(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.0/24"], allow_private_addresses=True
        )
        # Circuit relay denied when allow list configured (no IP to check)
        circuit_addr = Multiaddr(
            "/p2p-circuit/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
        result = await gate.is_allowed(circuit_addr)
        assert result is False

    async def test_dns_resolution_failure_with_allow_list(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.0/24"], allow_private_addresses=True
        )
        # Invalid DNS should be denied when allow list is configured
        dns_addr = Multiaddr("/dns4/invalid-domain-xyz-123.com/tcp/1234")
        result = await gate.is_allowed(dns_addr)
        assert result is False

    async def test_dns_resolution_failure_no_allow_list(self):
        gate = ConnectionGate(allow_private_addresses=True)
        # Invalid DNS should be allowed when no allow list is configured
        dns_addr = Multiaddr("/dns4/invalid-domain-xyz-123.com/tcp/1234")
        result = await gate.is_allowed(dns_addr)
        assert result is True


class TestConnectionConfig:
    def test_custom_values(self):
        config = ConnectionConfig(
            max_connections=500,
            min_connections=25,
            low_watermark=50,
            high_watermark=400,
        )
        assert config.max_connections == 500
        assert config.min_connections == 25
        assert config.low_watermark == 50
        assert config.high_watermark == 400

    def test_allow_deny_lists(self):
        config = ConnectionConfig(
            allow_list=["192.168.1.0/24"],
            deny_list=["192.168.1.100"],
        )
        assert len(config.allow_list) == 1
        assert len(config.deny_list) == 1
