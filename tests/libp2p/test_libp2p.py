from libp2p.libp2p import Libp2p


# TODO: are these connections async? how do we wait on responses?
def test_simple_messages():
    lib = Libp2p()

    hostA = lib.new_node()
    hostB = lib.new_node()

    def stream_handler(stream):
        print("stream received in host B")

        read_string = stream.read().decode()
        print("host B received: " + read_string)

        response = "ack: " + read_string
        stream.write(response.encode())

    hostB.set_stream_handler("/echo/1.0.0", stream_handler)

    # associate the peer with local ip address (see default parameters of Libp2p())
    hostA.get_peerstore().add_addr("hostB", "/ip4/127.0.0.1/tcp/10000")

    stream = hostA.new_stream("hostB", "/echo/1.0.0")
    message = "hello"
    stream.write(message.encode())

    response = stream.read().decode()
    assert response == ("ack: " + message)
