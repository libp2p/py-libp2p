import pytest
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.tools.constants import (
    LISTEN_MADDR,
)
from libp2p.transport.exceptions import (
    OpenConnectionError,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)

@pytest.mark.trio
async def test_tcp_listener():
    transport = TCP()

    async def handler(tcp_stream):
        pass

    listener = transport.create_listener(handler)
    assert len(listener.get_addrs()) == 0
    await listener.listen(LISTEN_MADDR)
    assert len(listener.get_addrs()) == 1
    await listener.listen(LISTEN_MADDR)
    assert len(listener.get_addrs()) == 2


@pytest.mark.trio
async def test_tcp_dial():
    transport = TCP()
    raw_conn_other_side: RawConnection | None = None
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
    await listener.listen(LISTEN_MADDR)
    addrs = listener.get_addrs()
    assert len(addrs) == 1
    listen_addr = addrs[0]
    raw_conn = await transport.dial(listen_addr)
    await event.wait()

    data = b"123"
    assert raw_conn_other_side is not None
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data


def get_local_maddr(port=0):
    return Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")

@pytest.mark.trio
async def test_tcp_listener_lifecycle_success():
    """
    Test successful start, serving, and clean shutdown of internal nursery.
    """
    transport = TCP()
    handler_called = trio.Event()

    async def mock_handler(stream):
        handler_called.set()
        await stream.close()

    listener = transport.create_listener(mock_handler)
    maddr = get_local_maddr(0)

    success = await listener.listen(maddr)
    assert success is True
    assert len(listener.listeners) == 1
    assert listener._nursery is not None
    
    addrs = listener.get_addrs()
    assert len(addrs) == 1
    listen_port = addrs[0].value_for_protocol("tcp")
    assert listen_port != "0"

    client_conn = await transport.dial(addrs[0])
    assert client_conn is not None
    await handler_called.wait()
    await client_conn.close()
    await listener.close()
    
    assert listener._nursery is None or listener._nursery.cancel_scope.cancel_called
    assert len(listener.listeners) == 0

@pytest.mark.trio
async def test_tcp_listener_bind_error():
    """
    Test error propagation when binding to a used port.
    """
    async def dummy_handler(conn):
        await trio.sleep(0)

    transport = TCP()
    listener_a = transport.create_listener(dummy_handler)
    
    await listener_a.listen(get_local_maddr(0))
    addr_a = listener_a.get_addrs()[0]
    
    listener_b = transport.create_listener(dummy_handler)
    
    success = await listener_b.listen(addr_a)
    
    assert success is False
    assert len(listener_b.listeners) == 0
    
    await listener_a.close()
    await listener_b.close()

@pytest.mark.trio
async def test_tcp_listener_double_close():
    """
    Test that calling close() multiple times is safe.
    """
    async def dummy_handler(conn):
        await trio.sleep(0)

    transport = TCP()
    listener = transport.create_listener(dummy_handler)
    await listener.listen(get_local_maddr(0))
    
    await listener.close()
    try:
        await listener.close()
    except Exception as e:
        pytest.fail(f"Second close() raised exception: {e}")