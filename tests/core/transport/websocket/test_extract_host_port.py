"""
Unit tests for ``_extract_host_port_from_sockname``.

Historically ``WebsocketListener.listen`` unpacked ``sock.getsockname()``
as a 2-tuple, which worked for IPv4 sockets but failed with
``ValueError: too many values to unpack`` for IPv6 sockets (whose
``getsockname()`` returns a 4-tuple ``(host, port, flowinfo, scopeid)``).
This regression test pins the supported shapes for the extractor so the
IPv6 path doesn't re-break.
"""

from __future__ import annotations

from libp2p.transport.websocket.listener import _extract_host_port_from_sockname


def test_ipv4_two_tuple() -> None:
    assert _extract_host_port_from_sockname(("127.0.0.1", 12345)) == (
        "127.0.0.1",
        12345,
    )


def test_ipv6_four_tuple() -> None:
    # (host, port, flowinfo, scopeid)
    assert _extract_host_port_from_sockname(("::1", 23456, 0, 0)) == ("::1", 23456)


def test_ipv6_four_tuple_with_nonzero_scopeid() -> None:
    assert _extract_host_port_from_sockname(("fe80::1", 34567, 0, 3)) == (
        "fe80::1",
        34567,
    )


def test_unexpected_shape_returns_none() -> None:
    # Not a tuple, single element, wrong element types — all graceful.
    assert _extract_host_port_from_sockname(None) is None
    assert _extract_host_port_from_sockname(("127.0.0.1",)) is None
    assert _extract_host_port_from_sockname((12345, "127.0.0.1")) is None
    # A raw string (e.g. what an AF_UNIX socket's getsockname returns) is
    # not a tuple and must be rejected.
    assert _extract_host_port_from_sockname("socket-path") is None
