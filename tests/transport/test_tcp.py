import asyncio

import pytest

from libp2p.transport.tcp.tcp import _multiaddr_from_socket, TCP
from multiaddr import Multiaddr


@pytest.mark.asyncio
async def test_multiaddr_from_socket():
    def handler(r, w):
        pass

    server = await asyncio.start_server(handler, '127.0.0.1', 8000)
    assert str(_multiaddr_from_socket(server.sockets[0])) == '/ip4/127.0.0.1/tcp/8000'

    server = await asyncio.start_server(handler, '127.0.0.1', 0)
    addr = _multiaddr_from_socket(server.sockets[0])
    assert addr.value_for_protocol('ip4') == '127.0.0.1'
    port = addr.value_for_protocol('tcp')
    assert int(port) > 0

@pytest.mark.asyncio
async def test_tcp_connection_close():
    def handler(r, w):
        pass

    tcp = TCP()
    conn = tcp.create_listener(handler)
    await conn.listen(Multiaddr("/ip4/127.0.0.1/tcp/8002"))
    # Closing a connection should work and return True.
    assert await conn.close()
    # Closing an already closed connection should not work and return False.
    assert not await conn.close()
