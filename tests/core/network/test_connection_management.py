"""
Unit tests for connection management components (go-libp2p style).
"""

from multiaddr import Multiaddr

from libp2p.network.config import ConnectionConfig
from libp2p.network.connection_gate import ConnectionGate, extract_ip_from_multiaddr


class TestExtractIpFromMultiaddr:
    def test_extract_ipv4(self):
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        assert extract_ip_from_multiaddr(addr) == "192.168.1.1"

    def test_extract_ipv6(self):
        addr = Multiaddr("/ip6/::1/tcp/1234")
        assert extract_ip_from_multiaddr(addr) == "::1"

    def test_extract_no_ip(self):
        addr = Multiaddr("/dns4/example.com/tcp/1234")
        assert extract_ip_from_multiaddr(addr) is None


class TestConnectionGate:
    def test_deny_list(self):
        gate = ConnectionGate(deny_list=["192.168.1.1"], allow_private_addresses=True)
        denied = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        allowed = Multiaddr("/ip4/192.168.1.2/tcp/1234")
        assert gate.is_allowed(denied) is False
        assert gate.is_allowed(allowed) is True

    def test_allow_list(self):
        gate = ConnectionGate(allow_list=["192.168.1.1"], allow_private_addresses=True)
        allowed = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        denied = Multiaddr("/ip4/192.168.1.2/tcp/1234")
        assert gate.is_allowed(allowed) is True
        assert gate.is_allowed(denied) is False

    def test_cidr_blocks(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.0/24"], allow_private_addresses=True
        )
        addr1 = Multiaddr("/ip4/192.168.1.10/tcp/1234")
        addr2 = Multiaddr("/ip4/192.168.2.10/tcp/1234")
        assert gate.is_allowed(addr1) is True
        assert gate.is_allowed(addr2) is False

    def test_deny_takes_precedence(self):
        gate = ConnectionGate(
            allow_list=["192.168.1.1"],
            deny_list=["192.168.1.1"],
            allow_private_addresses=True,
        )
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")
        assert gate.is_allowed(addr) is False


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
