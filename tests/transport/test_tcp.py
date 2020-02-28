from multiaddr import Multiaddr
import pytest
import trio

from libp2p.network.connection.raw_connection import RawConnection
from libp2p.tools.constants import LISTEN_MADDR
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.tcp.tcp import TCP


@pytest.mark.trio
async def test_tcp_listener(nursery):
    transport = TCP()

    async def handler(tcp_stream):
        pass

    listener = transport.create_listener(handler)
    assert len(listener.get_addrs()) == 0
    await nursery.start(listener.listen, LISTEN_MADDR)
    assert len(listener.get_addrs()) == 1
    await nursery.start(listener.listen, LISTEN_MADDR)
    assert len(listener.get_addrs()) == 2


@pytest.mark.trio
async def test_tcp_dial(nursery):
    transport = TCP()
    raw_conn_other_side = None
    event = trio.Event()

    async def handler(tcp_stream):
        nonlocal raw_conn_other_side
        raw_conn_other_side = RawConnection(tcp_stream, False)
        event.set()
        await trio.sleep_forever()

    # Test: `OpenConnectionError` is raised when trying to dial to a port which
    #   no one is not listening to.
    with pytest.raises(OpenConnectionError):
        await transport.dial(Multiaddr("/ip4/127.0.0.1/tcp/1"))

    listener = transport.create_listener(handler)
    await nursery.start(listener.listen, LISTEN_MADDR)
    addrs = listener.get_addrs()
    assert len(addrs) == 1
    listen_addr = addrs[0]
    raw_conn = await transport.dial(listen_addr)
    await event.wait()

    data = b"123"
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data
