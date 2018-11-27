import pytest

from libp2p.libp2p import new_node

@pytest.mark.asyncio
async def test_simple_messages():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8001/ipfs/node_a"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8000/ipfs/node_b"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()
            print("host B received:" + read_string)

            response = "ack:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addr("node_b", "/ip4/127.0.0.1/tcp/8000", 10)

    stream = await node_a.new_stream("node_b", "/echo/1.0.0")
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
    host_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8002/ipfs/host_a"])
    host_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8003/ipfs/host_b"])

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

    host_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    host_a.get_peerstore().add_addr("hostB", "/ip4/127.0.0.1/tcp/8003", 10)
    print("hostA about to open stream")
    stream = await host_a.new_stream("hostB", "/echo/1.0.0")
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
