import pytest
import trio

from libp2p.host.exceptions import (
    StreamFailure,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.tools.utils import (
    MAX_READ_LEN,
)
from tests.utils.factories import (
    HostFactory,
)

CHAT_PROTOCOL_ID = "/chat/1.0.0"
ECHO_PROTOCOL_ID = "/echo/1.0.0"
PING_PROTOCOL_ID = "/ipfs/ping/1.0.0"


async def hello_world(host_a, host_b):
    hello_world_from_host_a = b"hello world from host a"
    hello_world_from_host_b = b"hello world from host b"

    async def stream_handler(stream):
        read = await stream.read(len(hello_world_from_host_b))
        assert read == hello_world_from_host_b
        await stream.write(hello_world_from_host_a)
        await stream.close()

    host_a.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [CHAT_PROTOCOL_ID])
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

    host_a.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [CHAT_PROTOCOL_ID])
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

    host_a.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler)

    # Start a stream with the destination.
    # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
    stream = await host_b.new_stream(host_a.get_id(), [CHAT_PROTOCOL_ID])
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

    host_a.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler)

    # try to creates a new new with a procotol not known by the other host
    with pytest.raises(StreamFailure):
        await host_b.new_stream(host_a.get_id(), ["/fakeproto/0.0.1"])


async def chat_demo(host_a, host_b):
    messages_received_a = []
    messages_received_b = []

    async def stream_handler_a(stream):
        while True:
            try:
                data = await stream.read(MAX_READ_LEN)
                if not data:
                    break
                messages_received_a.append(data)
                await stream.write(b"ack_a:" + data)
            except Exception:
                break

    async def stream_handler_b(stream):
        while True:
            try:
                data = await stream.read(MAX_READ_LEN)
                if not data:
                    break
                messages_received_b.append(data)
                await stream.write(b"ack_b:" + data)
            except Exception:
                break

    host_a.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler_a)
    host_b.set_stream_handler(CHAT_PROTOCOL_ID, stream_handler_b)

    stream_a = await host_a.new_stream(host_b.get_id(), [CHAT_PROTOCOL_ID])
    stream_b = await host_b.new_stream(host_a.get_id(), [CHAT_PROTOCOL_ID])

    test_messages = [b"hello", b"world", b"test"]
    for msg in test_messages:
        await stream_a.write(msg)
        await stream_b.write(msg)

    await trio.sleep(0.1)

    assert len(messages_received_a) == len(test_messages)
    assert len(messages_received_b) == len(test_messages)


async def echo_demo(host_a, host_b):
    async def echo_handler(stream):
        while True:
            try:
                data = await stream.read(MAX_READ_LEN)
                if not data:
                    break
                await stream.write(data)
            except Exception:
                break

    host_b.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

    stream = await host_a.new_stream(host_b.get_id(), [ECHO_PROTOCOL_ID])
    test_message = b"hello, echo!"

    await stream.write(test_message)
    response = await stream.read(MAX_READ_LEN)

    assert response == test_message


async def ping_demo(host_a, host_b):
    async def ping_handler(stream):
        while True:
            try:
                data = await stream.read(32)  # PING_LENGTH = 32
                if not data:
                    break
                await stream.write(data)
            except Exception:
                break

    host_b.set_stream_handler(PING_PROTOCOL_ID, ping_handler)

    stream = await host_a.new_stream(host_b.get_id(), [PING_PROTOCOL_ID])
    ping_data = b"x" * 32  # 32 bytes of data

    await stream.write(ping_data)
    response = await stream.read(32)

    assert response == ping_data


@pytest.mark.parametrize(
    "test",
    [
        hello_world,
        connect_write,
        connect_read,
        no_common_protocol,
        chat_demo,
        echo_demo,
        ping_demo,
    ],
)
@pytest.mark.trio
async def test_protocols(test, security_protocol):
    print("!@# ", security_protocol)
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        addr = hosts[0].get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await hosts[1].connect(info)

        await test(hosts[0], hosts[1])
