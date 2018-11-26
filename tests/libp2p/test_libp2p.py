import pytest

from libp2p.libp2p import *

@pytest.mark.asyncio
async def test_simple_messages():
    hostA = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8002/ipfs/hostA"])
    hostB = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8003/ipfs/hostB"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()
            print("host B received:" + read_string)

            response = "ack1:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

    hostB.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    hostA.get_peerstore().add_addr("hostB", "/ip4/127.0.0.1/tcp/8003", 10)
    print("hostA about to open stream")
    stream = await hostA.new_stream("hostB", "/echo/1.0.0")
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
    hostA = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8002/ipfs/hostA"])
    hostB = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8003/ipfs/hostB"])

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

    hostB.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    hostA.get_peerstore().add_addr("hostB", "/ip4/127.0.0.1/tcp/8003", 10)
    print("hostA about to open stream")
    stream = await hostA.new_stream("hostB", "/echo/1.0.0")
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
