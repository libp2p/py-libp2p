import os

import pytest
from multiaddr import Multiaddr

from libp2p.utils.address_validation import (
    expand_wildcard_address,
    get_available_interfaces,
    get_optimal_binding_address,
    has_public_ipv6,
    is_relay_address,
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


class _FakeIfInet6File:
    """Minimal file-like object feeding lines to ``open`` readers."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._idx = 0

    def __enter__(self) -> "_FakeIfInet6File":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self) -> "_FakeIfInet6File":
        return self

    def __next__(self) -> str:
        if self._idx >= len(self._lines):
            raise StopIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line


@pytest.mark.parametrize(
    "lines,expected",
    [
        (
            # Loopback only — no public IPv6 (typical EC2 without IPv6).
            ["00000000000000000000000000000001 01 80 10 80 lo\n"],
            False,
        ),
        (
            # Loopback + a real global IPv6 on eth0.
            [
                "00000000000000000000000000000001 01 80 10 80 lo\n",
                "26000000000000000000000000000001 02 40 00 00 eth0\n",
            ],
            True,
        ),
        (
            # Loopback + link-local only (fe80::) — still no public IPv6.
            [
                "00000000000000000000000000000001 01 80 10 80 lo\n",
                "fe800000000000000000000000000001 02 40 20 00 eth0\n",
            ],
            False,
        ),
    ],
)
def test_has_public_ipv6_linux_proc(
    monkeypatch: pytest.MonkeyPatch, lines: list[str], expected: bool
) -> None:
    """has_public_ipv6 requires a non-loopback IPv6 interface on Linux."""
    has_public_ipv6.cache_clear()
    monkeypatch.setattr(
        "builtins.open",
        lambda *a, **k: _FakeIfInet6File(lines),  # type: ignore[no-any-return]
    )
    try:
        assert has_public_ipv6() is expected
    finally:
        has_public_ipv6.cache_clear()


def test_has_public_ipv6_returns_bool() -> None:
    """On the local (non-Linux or Linux) host the probe returns a bool."""
    has_public_ipv6.cache_clear()
    try:
        assert isinstance(has_public_ipv6(), bool)
    finally:
        has_public_ipv6.cache_clear()


def test_is_relay_address() -> None:
    """is_relay_address detects /p2p-circuit paths and never raises."""
    assert is_relay_address(
        Multiaddr(
            "/ip4/141.11.164.205/udp/4001/quic-v1/p2p/"
            "12D3KooWEnYdmNc1VkgodEq8Hyoi9WtAsYqeXsV96rPJyuZjhYSc/p2p-circuit"
        )
    )
    assert is_relay_address(
        Multiaddr(
            "/ip4/8.8.8.8/tcp/4001/p2p-circuit/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )
    )
    assert not is_relay_address(Multiaddr("/ip4/8.8.8.8/tcp/4001"))
    assert not is_relay_address(Multiaddr("/ip4/52.7.183.75/udp/4001/quic-v1"))
