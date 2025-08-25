import os

import pytest
from multiaddr import Multiaddr

from libp2p.utils.address_validation import (
    expand_wildcard_address,
    get_available_interfaces,
    get_optimal_binding_address,
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
