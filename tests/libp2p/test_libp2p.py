import multiaddr
import pytest

from libp2p.libp2p import new_node
from peer.peerinfo import info_from_p2p_addr


@pytest.mark.asyncio
async def test_simple_messages():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8001"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8000"])

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
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8002"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8003"])

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
async def test_host_connect():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8001/"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8000/"])

    assert len(node_a.get_peerstore().peers()) == 0

    addr = node_b.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node_a.connect(info)

    assert len(node_a.get_peerstore().peers()) == 1

    await node_a.connect(info)

    # make sure we don't do double connection
    assert len(node_a.get_peerstore().peers()) == 1

    assert node_b.get_id() in node_a.get_peerstore().peers()
    ma_node_b = multiaddr.Multiaddr('/ipfs/%s' % node_b.get_id().pretty())
    for addr in node_a.get_peerstore().addrs(node_b.get_id()):
        assert addr.encapsulate(ma_node_b) in node_b.get_addrs()
