import asyncio
import socket

import pytest

from libp2p.transport.tcp.tcp import _multiaddr_from_socket


def create_socket(
    addr, family: socket.AddressFamily, type: socket.SocketKind
) -> socket.socket:
    sock = socket.socket(family, type)
    sock.bind(addr)
    return sock


@pytest.mark.asyncio
async def test_multiaddr_from_socket():
    def handler(r, w):
        pass

    # Test with IPv4
    server = await asyncio.start_server(handler, "127.0.0.1", 8000)
    assert str(_multiaddr_from_socket(server.sockets[0])) == "/ip4/127.0.0.1/tcp/8000"
    server.close()

    # Additional test with raw sockets
    sock = create_socket(("127.0.0.1", 8089), socket.AF_INET, socket.SOCK_STREAM)
    assert str(_multiaddr_from_socket(sock)) == "/ip4/127.0.0.1/tcp/8089"
    sock.close()

    sock = create_socket(("127.0.0.1", 8091), socket.AF_INET, socket.SOCK_DGRAM)
    assert str(_multiaddr_from_socket(sock)) == "/ip4/127.0.0.1/udp/8091"
    sock.close()

    # Test if ipv4 address stays the same with random-port socket
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    addr = _multiaddr_from_socket(server.sockets[0])
    assert addr.value_for_protocol("ip4") == "127.0.0.1"
    port = addr.value_for_protocol("tcp")
    assert int(port) > 0
    server.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not socket.has_ipv6, reason="IPv6 not supported on test host")
async def test_ipv6_multiaddr_from_socket():
    def handler(r, w):
        pass

    # Test if socket.has_ipv6 isn't lying
    try:
        server = await asyncio.start_server(handler, "::1", 0)
    except OSError as e:
        # OSError [99]: cannot assign requested address
        if e.errno == 99:
            # The reason we skip this test instead of passing it is because we are testing if
            # _multiaddr_from_socket returns a correct value from low-level socket objects,
            # not if the host supports ipv6. If it doesn't, this test cannot run.
            pytest.skip("Binding to random ipv6 address failed.")
    else:
        server.close()

    # Test with IPv6
    server = await asyncio.start_server(handler, "::1", 8081)
    assert str(_multiaddr_from_socket(server.sockets[0])) == "/ip6/::1/tcp/8081"
    server.close()

    # Additional test with raw sockets
    sock = create_socket(("::", 8090), socket.AF_INET6, socket.SOCK_STREAM)
    assert str(_multiaddr_from_socket(sock)) == "/ip6/::/tcp/8090"
    sock.close()

    sock = create_socket(("::", 8092), socket.AF_INET6, socket.SOCK_DGRAM)
    assert str(_multiaddr_from_socket(sock)) == "/ip6/::/udp/8092"
    sock.close()
