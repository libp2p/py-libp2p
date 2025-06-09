import logging

import pytest
import trio

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.exceptions import (
    StreamFailure,
)
from libp2p.identity.identify_push import (
    ID_PUSH,
    identify_push_handler_for,
    push_identify_to_peer,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)
from libp2p.tools.async_service.trio_service import (
    background_trio_service,
)
from libp2p.tools.utils import (
    MAX_READ_LEN,
)
from tests.utils.factories import (
    HostFactory,
)

logger = logging.getLogger(__name__)

CHAT_PROTOCOL_ID = "/chat/1.0.0"
ECHO_PROTOCOL_ID = "/echo/1.0.0"
PING_PROTOCOL_ID = "/ipfs/ping/1.0.0"
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
PUBSUB_TEST_TOPIC = "test-pubsub-topic"


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


async def pubsub_demo(host_a, host_b):
    gossipsub_a = GossipSub(
        [GOSSIPSUB_PROTOCOL_ID],
        3,
        2,
        4,
    )
    gossipsub_b = GossipSub(
        [GOSSIPSUB_PROTOCOL_ID],
        3,
        2,
        4,
    )
    gossipsub_a = GossipSub([GOSSIPSUB_PROTOCOL_ID], 3, 2, 4, None, 1, 1)
    gossipsub_b = GossipSub([GOSSIPSUB_PROTOCOL_ID], 3, 2, 4, None, 1, 1)
    pubsub_a = Pubsub(host_a, gossipsub_a)
    pubsub_b = Pubsub(host_b, gossipsub_b)
    message_a_to_b = "Hello from A to B"
    b_received = trio.Event()
    received_by_b = None

    async def handle_subscription_b(subscription):
        nonlocal received_by_b
        message = await subscription.get()
        received_by_b = message.data.decode("utf-8")
        print(f"Host B received: {received_by_b}")
        b_received.set()

    async with background_trio_service(pubsub_a):
        async with background_trio_service(pubsub_b):
            async with background_trio_service(gossipsub_a):
                async with background_trio_service(gossipsub_b):
                    await pubsub_a.wait_until_ready()
                    await pubsub_b.wait_until_ready()

                    listen_addrs_b = host_b.get_addrs()
                    peer_info_b = info_from_p2p_addr(listen_addrs_b[0])
                    try:
                        await pubsub_a.host.connect(peer_info_b)
                        print("Connection attempt completed")
                    except Exception as e:
                        print(f"Connection error: {e}")
                        raise

                    subscription_b = await pubsub_b.subscribe(PUBSUB_TEST_TOPIC)
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(handle_subscription_b, subscription_b)
                        await trio.sleep(0.1)
                        await pubsub_a.publish(
                            PUBSUB_TEST_TOPIC, message_a_to_b.encode()
                        )
                        with trio.move_on_after(3):
                            await b_received.wait()
                        nursery.cancel_scope.cancel()

    assert received_by_b == message_a_to_b
    assert b_received.is_set()


async def identify_push_demo(host_a, host_b):
    # Set up the identify/push handlers on both hosts
    host_a.set_stream_handler(ID_PUSH, identify_push_handler_for(host_a))
    host_b.set_stream_handler(ID_PUSH, identify_push_handler_for(host_b))

    # Ensure both hosts have the required protocols
    # This is needed because the test hosts
    # might not have all protocols loaded by default
    host_a_protocols = set(host_a.get_mux().get_protocols())

    # Log protocols before push
    logger.debug("Host A protocols before push: %s", host_a_protocols)

    # Push identify information from host_a to host_b
    success = await push_identify_to_peer(host_a, host_b.get_id())
    assert success is True

    # Add a small delay to allow processing
    await trio.sleep(0.1)

    # Check that host_b's peerstore has been updated with host_a's information
    peer_id = host_a.get_id()
    peerstore = host_b.get_peerstore()

    # Check that the peer is in the peerstore
    assert peer_id in peerstore.peer_ids()

    # If peerstore has no protocols for this peer, manually update them for the test
    peerstore_protocols = set(peerstore.get_protocols(peer_id))

    # Log protocols after push
    logger.debug("Host A protocols after push: %s", host_a_protocols)
    logger.debug("Peerstore protocols after push: %s", peerstore_protocols)

    # Check that the protocols were updated
    assert all(protocol in peerstore_protocols for protocol in host_a_protocols)

    # Check that the addresses were updated
    host_a_addrs = set(host_a.get_addrs())
    peerstore_addrs = set(peerstore.addrs(peer_id))

    # Log addresses after push
    logger.debug("Host A addresses: %s", host_a_addrs)
    logger.debug("Peerstore addresses: %s", peerstore_addrs)

    # Check that the addresses were updated
    assert all(addr in peerstore_addrs for addr in host_a_addrs)


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
        pubsub_demo,
        identify_push_demo,
    ],
)
@pytest.mark.trio
async def test_protocols(test, security_protocol):
    print("!@# ", security_protocol)
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        if test != pubsub_demo:
            addr = hosts[0].get_addrs()[0]
            info = info_from_p2p_addr(addr)
            await hosts[1].connect(info)

        await test(hosts[0], hosts[1])
