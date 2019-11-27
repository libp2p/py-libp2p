import multiaddr
import pytest

from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.constants import MAX_READ_LEN
from libp2p.tools.utils import set_up_nodes_by_transport_opt


@pytest.mark.asyncio
async def test_simple_messages():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        await stream.write(message.encode())

        response = (await stream.read(MAX_READ_LEN)).decode()

        assert response == ("ack:" + message)

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_double_response():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack1:" + read_string
            await stream.write(response.encode())

            response = "ack2:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        await stream.write(message.encode())

        response1 = (await stream.read(MAX_READ_LEN)).decode()
        assert response1 == ("ack1:" + message)

        response2 = (await stream.read(MAX_READ_LEN)).decode()
        assert response2 == ("ack2:" + message)

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_multiple_streams():
    # Node A should be able to open a stream with node B and then vice versa.
    # Stream IDs should be generated uniquely so that the stream state is not overwritten
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler_a(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a:" + read_string
            await stream.write(response.encode())

    async def stream_handler_b(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_b:" + read_string
            await stream.write(response.encode())

    node_a.set_stream_handler("/echo_a/1.0.0", stream_handler_a)
    node_b.set_stream_handler("/echo_b/1.0.0", stream_handler_b)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    node_b.get_peerstore().add_addrs(node_a.get_id(), node_a.get_addrs(), 10)

    stream_a = await node_a.new_stream(node_b.get_id(), ["/echo_b/1.0.0"])
    stream_b = await node_b.new_stream(node_a.get_id(), ["/echo_a/1.0.0"])

    # A writes to /echo_b via stream_a, and B writes to /echo_a via stream_b
    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        a_message = message + "_a"
        b_message = message + "_b"

        await stream_a.write(a_message.encode())
        await stream_b.write(b_message.encode())

        response_a = (await stream_a.read(MAX_READ_LEN)).decode()
        response_b = (await stream_b.read(MAX_READ_LEN)).decode()

        assert response_a == ("ack_b:" + a_message) and response_b == (
            "ack_a:" + b_message
        )

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_multiple_streams_same_initiator_different_protocols():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler_a1(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a1:" + read_string
            await stream.write(response.encode())

    async def stream_handler_a2(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a2:" + read_string
            await stream.write(response.encode())

    async def stream_handler_a3(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a3:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo_a1/1.0.0", stream_handler_a1)
    node_b.set_stream_handler("/echo_a2/1.0.0", stream_handler_a2)
    node_b.set_stream_handler("/echo_a3/1.0.0", stream_handler_a3)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    node_b.get_peerstore().add_addrs(node_a.get_id(), node_a.get_addrs(), 10)

    # Open streams to node_b over echo_a1 echo_a2 echo_a3 protocols
    stream_a1 = await node_a.new_stream(node_b.get_id(), ["/echo_a1/1.0.0"])
    stream_a2 = await node_a.new_stream(node_b.get_id(), ["/echo_a2/1.0.0"])
    stream_a3 = await node_a.new_stream(node_b.get_id(), ["/echo_a3/1.0.0"])

    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        a1_message = message + "_a1"
        a2_message = message + "_a2"
        a3_message = message + "_a3"

        await stream_a1.write(a1_message.encode())
        await stream_a2.write(a2_message.encode())
        await stream_a3.write(a3_message.encode())

        response_a1 = (await stream_a1.read(MAX_READ_LEN)).decode()
        response_a2 = (await stream_a2.read(MAX_READ_LEN)).decode()
        response_a3 = (await stream_a3.read(MAX_READ_LEN)).decode()

        assert (
            response_a1 == ("ack_a1:" + a1_message)
            and response_a2 == ("ack_a2:" + a2_message)
            and response_a3 == ("ack_a3:" + a3_message)
        )

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_multiple_streams_two_initiators():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler_a1(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a1:" + read_string
            await stream.write(response.encode())

    async def stream_handler_a2(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_a2:" + read_string
            await stream.write(response.encode())

    async def stream_handler_b1(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_b1:" + read_string
            await stream.write(response.encode())

    async def stream_handler_b2(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack_b2:" + read_string
            await stream.write(response.encode())

    node_a.set_stream_handler("/echo_b1/1.0.0", stream_handler_b1)
    node_a.set_stream_handler("/echo_b2/1.0.0", stream_handler_b2)

    node_b.set_stream_handler("/echo_a1/1.0.0", stream_handler_a1)
    node_b.set_stream_handler("/echo_a2/1.0.0", stream_handler_a2)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    node_b.get_peerstore().add_addrs(node_a.get_id(), node_a.get_addrs(), 10)

    stream_a1 = await node_a.new_stream(node_b.get_id(), ["/echo_a1/1.0.0"])
    stream_a2 = await node_a.new_stream(node_b.get_id(), ["/echo_a2/1.0.0"])

    stream_b1 = await node_b.new_stream(node_a.get_id(), ["/echo_b1/1.0.0"])
    stream_b2 = await node_b.new_stream(node_a.get_id(), ["/echo_b2/1.0.0"])

    # A writes to /echo_b via stream_a, and B writes to /echo_a via stream_b
    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        a1_message = message + "_a1"
        a2_message = message + "_a2"

        b1_message = message + "_b1"
        b2_message = message + "_b2"

        await stream_a1.write(a1_message.encode())
        await stream_a2.write(a2_message.encode())

        await stream_b1.write(b1_message.encode())
        await stream_b2.write(b2_message.encode())

        response_a1 = (await stream_a1.read(MAX_READ_LEN)).decode()
        response_a2 = (await stream_a2.read(MAX_READ_LEN)).decode()

        response_b1 = (await stream_b1.read(MAX_READ_LEN)).decode()
        response_b2 = (await stream_b2.read(MAX_READ_LEN)).decode()

        assert (
            response_a1 == ("ack_a1:" + a1_message)
            and response_a2 == ("ack_a2:" + a2_message)
            and response_b1 == ("ack_b1:" + b1_message)
            and response_b2 == ("ack_b2:" + b2_message)
        )

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_triangle_nodes_connection():
    transport_opt_list = [
        ["/ip4/127.0.0.1/tcp/0"],
        ["/ip4/127.0.0.1/tcp/0"],
        ["/ip4/127.0.0.1/tcp/0"],
    ]
    (node_a, node_b, node_c) = await set_up_nodes_by_transport_opt(transport_opt_list)

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            response = "ack:" + read_string
            await stream.write(response.encode())

    node_a.set_stream_handler("/echo/1.0.0", stream_handler)
    node_b.set_stream_handler("/echo/1.0.0", stream_handler)
    node_c.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    # Associate all permutations
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    node_a.get_peerstore().add_addrs(node_c.get_id(), node_c.get_addrs(), 10)

    node_b.get_peerstore().add_addrs(node_a.get_id(), node_a.get_addrs(), 10)
    node_b.get_peerstore().add_addrs(node_c.get_id(), node_c.get_addrs(), 10)

    node_c.get_peerstore().add_addrs(node_a.get_id(), node_a.get_addrs(), 10)
    node_c.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    stream_a_to_b = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])
    stream_a_to_c = await node_a.new_stream(node_c.get_id(), ["/echo/1.0.0"])

    stream_b_to_a = await node_b.new_stream(node_a.get_id(), ["/echo/1.0.0"])
    stream_b_to_c = await node_b.new_stream(node_c.get_id(), ["/echo/1.0.0"])

    stream_c_to_a = await node_c.new_stream(node_a.get_id(), ["/echo/1.0.0"])
    stream_c_to_b = await node_c.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    messages = ["hello" + str(x) for x in range(5)]
    streams = [
        stream_a_to_b,
        stream_a_to_c,
        stream_b_to_a,
        stream_b_to_c,
        stream_c_to_a,
        stream_c_to_b,
    ]

    for message in messages:
        for stream in streams:
            await stream.write(message.encode())

            response = (await stream.read(MAX_READ_LEN)).decode()

            assert response == ("ack:" + message)

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_host_connect():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    # Only our peer ID is stored in peer store
    assert len(node_a.get_peerstore().peer_ids()) == 1

    addr = node_b.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node_a.connect(info)

    assert len(node_a.get_peerstore().peer_ids()) == 2

    await node_a.connect(info)

    # make sure we don't do double connection
    assert len(node_a.get_peerstore().peer_ids()) == 2

    assert node_b.get_id() in node_a.get_peerstore().peer_ids()
    ma_node_b = multiaddr.Multiaddr("/p2p/%s" % node_b.get_id().pretty())
    for addr in node_a.get_peerstore().addrs(node_b.get_id()):
        assert addr.encapsulate(ma_node_b) in node_b.get_addrs()

    # Success, terminate pending tasks.
