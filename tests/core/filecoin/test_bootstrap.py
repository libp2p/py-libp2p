from collections.abc import Callable
import socket

import multiaddr

from libp2p.filecoin.bootstrap import (
    filter_bootstrap_for_transport,
    get_bootstrap_addresses,
    get_runtime_bootstrap_addresses,
    resolve_dns_bootstrap_to_ip4_tcp,
)
from libp2p.filecoin.networks import CALIBNET_BOOTSTRAP
from libp2p.peer.peerinfo import info_from_p2p_addr


def _build_fake_getaddrinfo(
    host_to_ip: dict[str, str],
    failing_hosts: set[str] | None = None,
) -> Callable[[str, int, int, int], list[tuple[int, int, int, str, tuple[str, int]]]]:
    failing_hosts = failing_hosts or set()

    def _fake_getaddrinfo(
        host: str,
        port: int,
        family: int,
        socktype: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert family == socket.AF_INET
        assert socktype == socket.SOCK_STREAM
        if host in failing_hosts:
            raise OSError(f"cannot resolve {host}")
        ip = host_to_ip[host]
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, port),
            )
        ]

    return _fake_getaddrinfo


def test_filter_bootstrap_canonical_vs_runtime_transport() -> None:
    canonical = get_bootstrap_addresses("mainnet", canonical=True)
    assert any("/webtransport/" in addr for addr in canonical)

    runtime_tcp_only = filter_bootstrap_for_transport(
        canonical, include_tcp=True, include_quic=False
    )
    assert runtime_tcp_only
    assert all("/tcp/" in addr for addr in runtime_tcp_only)
    assert all("/webtransport/" not in addr for addr in runtime_tcp_only)

    runtime_with_quic = filter_bootstrap_for_transport(
        canonical, include_tcp=True, include_quic=True
    )
    assert any("/quic-v1/" in addr for addr in runtime_with_quic)


def test_resolve_dns_bootstrap_to_ip4_tcp(monkeypatch) -> None:
    host_to_ip = {
        "bootstrap.calibration.filecoin.chain.love": "203.0.113.10",
        "bootstrap-calibnet-0.chainsafe-fil.io": "203.0.113.11",
    }
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _build_fake_getaddrinfo(host_to_ip),
    )

    addrs = [
        CALIBNET_BOOTSTRAP[0],
        CALIBNET_BOOTSTRAP[1],
    ]
    resolved = resolve_dns_bootstrap_to_ip4_tcp(addrs)
    assert resolved == [
        "/ip4/203.0.113.10/tcp/1237/p2p/12D3KooWQPYouEAsUQKzvFUA9sQ8tz4rfpqtTzh2eL6USd9bwg7x",
        "/ip4/203.0.113.11/tcp/34000/p2p/12D3KooWABQ5gTDHPWyvhJM7jPhtNwNJruzTEo32Lo4gcS5ABAMm",
    ]


def test_resolve_dns_failures_are_non_fatal(monkeypatch) -> None:
    host_to_ip = {
        "bootstrap.calibration.filecoin.chain.love": "203.0.113.10",
        "bootstrap-calibnet-0.chainsafe-fil.io": "203.0.113.11",
    }
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _build_fake_getaddrinfo(
            host_to_ip=host_to_ip,
            failing_hosts={"bootstrap-calibnet-0.chainsafe-fil.io"},
        ),
    )

    resolved = resolve_dns_bootstrap_to_ip4_tcp(
        [CALIBNET_BOOTSTRAP[0], CALIBNET_BOOTSTRAP[1]]
    )
    assert resolved == [
        "/ip4/203.0.113.10/tcp/1237/p2p/12D3KooWQPYouEAsUQKzvFUA9sQ8tz4rfpqtTzh2eL6USd9bwg7x"
    ]


def test_runtime_bootstrap_addresses_are_parseable(monkeypatch) -> None:
    host_to_ip = {
        "bootstrap.calibration.filecoin.chain.love": "198.51.100.10",
        "bootstrap-calibnet-0.chainsafe-fil.io": "198.51.100.11",
        "bootstrap-calibnet-1.chainsafe-fil.io": "198.51.100.12",
        "bootstrap-calibnet-2.chainsafe-fil.io": "198.51.100.13",
        "bootstrap-archive-calibnet-0.chainsafe-fil.io": "198.51.100.14",
    }
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _build_fake_getaddrinfo(host_to_ip),
    )

    runtime_addrs = get_runtime_bootstrap_addresses(
        "calibnet",
        resolve_dns=True,
        include_quic=False,
    )
    assert len(runtime_addrs) == 5

    for addr in runtime_addrs:
        parsed = info_from_p2p_addr(multiaddr.Multiaddr(addr))
        assert parsed.peer_id is not None
        assert all(str(base_addr).startswith("/ip4/") for base_addr in parsed.addrs)
