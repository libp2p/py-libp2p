import pytest
import trio

from libp2p.host.exceptions import StreamFailure
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.factories import HostFactory
from libp2p.tools.utils import MAX_READ_LEN

PROTOCOL_ID = "/chat/1.0.0"


async def hello_world(host_a, host_b):
    hello_world_from_host_a = b"hello world from host a"
    hello_world_from_host_b = b"hello world from host b"

    async def stream_handler(stream):
        read = await stream.read(len(hello_world_from_host_b))
        assert read == hello_world_from_host_b
        await stream.write(hello_world_from_host_a)
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    await stream.write(hello_world_from_host_b)
    read = await stream.read(MAX_READ_LEN)
    assert read == hello_world_from_host_a
    await stream.close()


async def connect_write(host_a, host_b):
    messages = ["data %d" % i for i in range(5)]
    received = []

    async def stream_handler(stream):
        for message in messages:
            received.append((await stream.read(len(message))).decode())

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    for message in messages:
        await stream.write(message.encode())

    # Reader needs time due to async reads
    await trio.sleep(2)

    await stream.close()
    assert received == messages


async def connect_read(host_a, host_b):
    messages = [b"data %d" % i for i in range(5)]

    async def stream_handler(stream):
        for message in messages:
            await stream.write(message)
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [PROTOCOL_ID])
    received = []
    for message in messages:
        received.append(await stream.read(len(message)))
    await stream.close()
    assert received == messages


async def no_common_protocol(host_a, host_b):
    messages = [b"data %d" % i for i in range(5)]

    async def stream_handler(stream):
        for message in messages:
            await stream.write(message)
        await stream.close()

    host_a.set_stream_handler(PROTOCOL_ID, stream_handler)

    # try to creates a new new with a procotol not known by the other host
    with pytest.raises(StreamFailure):
        await host_b.new_stream(host_a.get_id(), ["/fakeproto/0.0.1"])


@pytest.mark.parametrize(
    "test", [(hello_world), (connect_write), (connect_read), (no_common_protocol)]
)
@pytest.mark.trio
async def test_chat(test, security_protocol):
    print("!@# ", security_protocol)
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        addr = hosts[0].get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await hosts[1].connect(info)

        await test(hosts[0], hosts[1])
