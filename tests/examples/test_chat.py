import pytest

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.protocol_muxer.multiselect_client import MultiselectClientError


PROTOCOL_ID = '/chat/1.0.0'


async def hello_world(host_a, host_b):
    async def stream_handler(stream):
        read = await stream.read()
        assert read == b'hello world from host b'
        await stream.write(b'hello world from host a')
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    await stream.write(b'hello world from host b')
    read = await stream.read()
    assert read == b'hello world from host a'
    await stream.close()


async def connect_write(host_a, host_b):
    messages = [b'data %d' % i for i in range(5)]

    async def stream_handler(stream):
        received = []
        while True:
            try:
                received.append((await stream.read()).decode())
            except Exception:  # exception is raised when other side close the stream ?
                break
        await stream.close()
        assert received == messages
    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    for message in messages:
        await stream.write(message)
    await stream.close()


async def connect_read(host_a, host_b):
    messages = [b'data %d' % i for i in range(5)]

    async def stream_handler(stream):
        for message in messages:
            await stream.write(message)
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    received = []
    # while True: Seems the close stream event from the other host is not received
    for _ in range(5):
        try:
            received.append(await stream.read())
        except Exception:  # exception is raised when other side close the stream ?
            break
    await stream.close()
    assert received == messages


async def no_common_protocol(host_a, host_b):
    messages = [b'data %d' % i for i in range(5)]

    async def stream_handler(stream):
        for message in messages:
            await stream.write(message)
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # try to creates a new new with a procotol not known by the other host
    with pytest.raises(MultiselectClientError):
        _ = await host_b.new_stream(host_a.get_id(), ['/fakeproto/0.0.1'])


@pytest.mark.asyncio
@pytest.mark.parametrize("test", [
    (hello_world),
    (connect_write),
    (connect_read),
    (no_common_protocol),
])
async def test_chat(test):
    host_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    host_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    addr = host_a.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await host_b.connect(info)

    await test(host_a, host_b)
