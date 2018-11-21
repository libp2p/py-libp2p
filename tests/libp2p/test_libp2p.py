import pytest

from libp2p.libp2p import Libp2p

@pytest.mark.asyncio
async def test_simple_messages():
    libA = Libp2p(transport_opt=["/ip4/127.0.0.1/tcp/8001/ipfs/hostA"])
    libB = Libp2p(transport_opt=["/ip4/127.0.0.1/tcp/8000/ipfs/hostB"])

    hostA = await libA.new_node()
    hostB = await libB.new_node()

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()
            print("host B received:" + read_string)

            response = "ack:" + read_string
            print("sending response:" + response)
            await stream.write(response.encode())

    hostB.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    hostA.get_peerstore().add_addr("hostB", "/ip4/127.0.0.1/tcp/8000", 10)
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
