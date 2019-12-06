from multiaddr import Multiaddr
import pytest
import trio

from libp2p.network.connection.raw_connection import RawConnection
from libp2p.tools.constants import LISTEN_MADDR
from libp2p.transport.tcp.tcp import TCP


@pytest.mark.trio
async def test_tcp_listener(nursery):
    transport = TCP()

    async def handler(tcp_stream):
        ...

    listener = transport.create_listener(handler)
    assert len(listener.get_addrs()) == 0
    await listener.listen(LISTEN_MADDR, nursery)
    assert len(listener.get_addrs()) == 1
    await listener.listen(LISTEN_MADDR, nursery)
    assert len(listener.get_addrs()) == 2


@pytest.mark.trio
async def test_tcp_dial(nursery):
    transport = TCP()
    raw_conn_other_side = None

    async def handler(tcp_stream):
        nonlocal raw_conn_other_side
        raw_conn_other_side = RawConnection(tcp_stream, False)
        await trio.sleep_forever()

    # Test: OSError is raised when trying to dial to a port which no one is not listening to.
    with pytest.raises(OSError):
        await transport.dial(Multiaddr("/ip4/127.0.0.1/tcp/1"))

    listener = transport.create_listener(handler)
    await listener.listen(LISTEN_MADDR, nursery)
    assert len(listener.multiaddrs) == 1
    listen_addr = listener.multiaddrs[0]
    raw_conn = await transport.dial(listen_addr)

    data = b"123"
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data
