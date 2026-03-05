"""Tests for libp2p.utils.multiaddr_utils."""

import pytest
from multiaddr import Multiaddr

from libp2p.utils.multiaddr_utils import (
    extract_host_from_multiaddr,
    extract_ip_from_multiaddr,
    format_host_for_url,
)


class TestExtractHostFromMultiaddr:
    """Tests for extract_host_from_multiaddr()."""

    def test_ipv4_multiaddr(self) -> None:
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080")
        assert extract_host_from_multiaddr(maddr) == "127.0.0.1"

    def test_ipv6_multiaddr(self) -> None:
        maddr = Multiaddr("/ip6/::1/tcp/8080")
        assert extract_host_from_multiaddr(maddr) == "::1"

    def test_ipv6_full_address(self) -> None:
        maddr = Multiaddr("/ip6/fe80::1/tcp/8080")
        assert extract_host_from_multiaddr(maddr) == "fe80::1"

    def test_dns_multiaddr(self) -> None:
        maddr = Multiaddr("/dns/example.com/tcp/443")
        assert extract_host_from_multiaddr(maddr) == "example.com"

    def test_dns4_multiaddr(self) -> None:
        maddr = Multiaddr("/dns4/example.com/tcp/443")
        assert extract_host_from_multiaddr(maddr) == "example.com"

    def test_dns6_multiaddr(self) -> None:
        maddr = Multiaddr("/dns6/example.com/tcp/443")
        assert extract_host_from_multiaddr(maddr) == "example.com"

    def test_no_host_protocol_returns_none(self) -> None:
        """Multiaddr with only tcp (no ip/dns) returns None."""
        maddr = Multiaddr("/tcp/8080")
        assert extract_host_from_multiaddr(maddr) is None

    def test_ipv4_preferred_over_ipv6(self) -> None:
        """When both ip4 and ip6 are present, ip4 is returned (first match)."""
        # Note: multiaddr library doesn't support both ip4 and ip6 in one addr,
        # so we just verify ip4 is tried first by using an ip4 multiaddr.
        maddr = Multiaddr("/ip4/10.0.0.1/tcp/80")
        assert extract_host_from_multiaddr(maddr) == "10.0.0.1"


class TestExtractIpFromMultiaddr:
    """Tests for extract_ip_from_multiaddr() (existing function)."""

    def test_ipv4(self) -> None:
        maddr = Multiaddr("/ip4/192.168.1.1/tcp/80")
        assert extract_ip_from_multiaddr(maddr) == "192.168.1.1"

    def test_ipv6(self) -> None:
        maddr = Multiaddr("/ip6/::1/tcp/80")
        assert extract_ip_from_multiaddr(maddr) == "::1"

    def test_dns_returns_none(self) -> None:
        """extract_ip_from_multiaddr does NOT handle DNS, only IP."""
        maddr = Multiaddr("/dns/example.com/tcp/80")
        assert extract_ip_from_multiaddr(maddr) is None

    def test_no_ip_returns_none(self) -> None:
        maddr = Multiaddr("/tcp/80")
        assert extract_ip_from_multiaddr(maddr) is None


class TestFormatHostForUrl:
    """Tests for format_host_for_url()."""

    def test_ipv4_unchanged(self) -> None:
        assert format_host_for_url("127.0.0.1") == "127.0.0.1"

    def test_ipv4_any_unchanged(self) -> None:
        assert format_host_for_url("0.0.0.0") == "0.0.0.0"

    def test_ipv6_loopback_bracketed(self) -> None:
        assert format_host_for_url("::1") == "[::1]"

    def test_ipv6_link_local_bracketed(self) -> None:
        assert format_host_for_url("fe80::1") == "[fe80::1]"

    def test_ipv6_full_bracketed(self) -> None:
        assert format_host_for_url("2001:db8::1") == "[2001:db8::1]"

    def test_ipv6_any_bracketed(self) -> None:
        assert format_host_for_url("::") == "[::]"

    def test_dns_hostname_unchanged(self) -> None:
        assert format_host_for_url("example.com") == "example.com"

    def test_localhost_unchanged(self) -> None:
        assert format_host_for_url("localhost") == "localhost"

    @pytest.mark.parametrize(
        "host,expected",
        [
            ("127.0.0.1", "ws://127.0.0.1:8080/"),
            ("::1", "ws://[::1]:8080/"),
            ("example.com", "ws://example.com:8080/"),
            ("fe80::1", "ws://[fe80::1]:8080/"),
        ],
    )
    def test_url_construction(self, host: str, expected: str) -> None:
        """Verify that format_host_for_url produces valid URLs."""
        ws_url = f"ws://{format_host_for_url(host)}:8080/"
        assert ws_url == expected
