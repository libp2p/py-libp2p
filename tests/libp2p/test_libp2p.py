import multiaddr
import pytest

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr


@pytest.mark.asyncio
async def test_simple_messages():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()
            print("host B received:" + read_string)

            response = "ack:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        await stream.write(message.encode())

        response = (await stream.read()).decode()

        print("res: " + response)
        assert response == ("ack:" + message)

    # Success, terminate pending tasks.
    return


@pytest.mark.asyncio
async def test_double_response():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()
            print("host B received:" + read_string)

            response = "ack1:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

            response = "ack2:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    print("node_a about to open stream")
    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])
    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        await stream.write(message.encode())

        response1 = (await stream.read()).decode()

        print("res1: " + response1)
        assert response1 == ("ack1:" + message)

        response2 = (await stream.read()).decode()

        print("res2: " + response2)
        assert response2 == ("ack2:" + message)

    # Success, terminate pending tasks.
    return


@pytest.mark.asyncio
async def test_multiple_streams():
    # Node A should be able to open a stream with node B and then vice versa.
    # Stream IDs should be generated uniquely so that the stream state is not overwritten
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler_a(stream):
        while True:
            read_string = (await stream.read()).decode()

            response = "ack_a:" + read_string
            await stream.write(response.encode())

    async def stream_handler_b(stream):
        while True:
            read_string = (await stream.read()).decode()

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

        response_a = (await stream_a.read()).decode()
        response_b = (await stream_b.read()).decode()

        assert response_a == ("ack_b:" + a_message) and response_b == ("ack_a:" + b_message)

    # Success, terminate pending tasks.
    return


@pytest.mark.asyncio
async def test_host_connect():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    assert not node_a.get_peerstore().peers()

    addr = node_b.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node_a.connect(info)

    assert len(node_a.get_peerstore().peers()) == 1

    await node_a.connect(info)

    # make sure we don't do double connection
    assert len(node_a.get_peerstore().peers()) == 1

    assert node_b.get_id() in node_a.get_peerstore().peers()
    ma_node_b = multiaddr.Multiaddr('/p2p/%s' % node_b.get_id().pretty())
    for addr in node_a.get_peerstore().addrs(node_b.get_id()):
        assert addr.encapsulate(ma_node_b) in node_b.get_addrs()
