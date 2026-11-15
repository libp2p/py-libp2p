import os

import pytest
from multiaddr import Multiaddr

from libp2p.utils.address_validation import (
    expand_wildcard_address,
    get_available_interfaces,
    get_optimal_binding_address,
    is_public_ipv6_address,
)


@pytest.mark.parametrize("proto", ["tcp"])
def test_get_available_interfaces(proto: str) -> None:
    interfaces = get_available_interfaces(0, protocol=proto)
    assert len(interfaces) > 0
    for addr in interfaces:
        assert isinstance(addr, Multiaddr)
        assert f"/{proto}/" in str(addr)


def test_get_optimal_binding_address() -> None:
    addr = get_optimal_binding_address(0)
    assert isinstance(addr, Multiaddr)
    # At least IPv4 or IPv6 prefix present
    s = str(addr)
    assert ("/ip4/" in s) or ("/ip6/" in s)


def test_expand_wildcard_address_ipv4() -> None:
    wildcard = Multiaddr("/ip4/0.0.0.0/tcp/0")
    expanded = expand_wildcard_address(wildcard)
    assert len(expanded) > 0
    for e in expanded:
        assert isinstance(e, Multiaddr)
        assert "/tcp/" in str(e)


def test_expand_wildcard_address_port_override() -> None:
    wildcard = Multiaddr("/ip4/0.0.0.0/tcp/7000")
    overridden = expand_wildcard_address(wildcard, port=9001)
    assert len(overridden) > 0
    for e in overridden:
        assert str(e).endswith("/tcp/9001")


@pytest.mark.skipif(
    os.environ.get("NO_IPV6") == "1",
    reason="Environment disallows IPv6",
)
def test_expand_wildcard_address_ipv6() -> None:
    wildcard = Multiaddr("/ip6/::/tcp/0")
    expanded = expand_wildcard_address(wildcard)
    assert len(expanded) > 0
    for e in expanded:
        assert "/ip6/" in str(e)


@pytest.mark.parametrize(
    ("addr", "expected"),
    [
        ("/ip6/::1/tcp/4001", False),
        ("/ip6/fd00::1/tcp/4001", False),
        ("/ip6/fe80::1/tcp/4001", False),
        ("/ip6/2001:4860:4860::8888/tcp/4001", True),
        # RFC 6761: localhost names resolve to loopback (#1585).
        ("/dns6/localhost/tcp/4001", False),
        ("/dns6/LOCALHOST/tcp/4001", False),
        ("/dns6/node.localhost/tcp/4001", False),
        ("/dns6/example.com/tcp/4001", True),
        ("/dns6/localhost.example.com/tcp/4001", True),
        ("/dns6/notlocalhost/tcp/4001", True),
        ("/dns/localhost/tcp/4001", False),
    ],
)
def test_is_public_ipv6_address(addr: str, expected: bool) -> None:
    assert is_public_ipv6_address(Multiaddr(addr)) is expected
