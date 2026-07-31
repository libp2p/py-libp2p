import traceback

import trio

from libp2p.io.trio import TrioTCPStream
from libp2p.protocol_muxer.multiselect_communicator import MultiselectCommunicator
from libp2p.transport.cmux import DemultiplexedConnType, PortDemultiplexer


async def mock_handler(stream):
    print("Handler started")
    try:
        tcp_stream = TrioTCPStream(stream)
        communicator = MultiselectCommunicator(tcp_stream)

        print("Writing to communicator...")
        await communicator.write("/multistream/1.0.0\n")

        print("Reading from communicator...")
        msg = await communicator.read()
        print(f"Read msg: {msg}")
    except Exception:
        print("Exception in handler:")
        traceback.print_exc()

async def server(nursery, task_status=trio.TASK_STATUS_IGNORED):
    listeners = await trio.open_tcp_listeners(0, host="127.0.0.1")
    port = listeners[0].socket.getsockname()[1]
    print(f"Listening on port {port}")
    task_status.started(port)

    demux = PortDemultiplexer("127.0.0.1", port)
    from multiaddr import Multiaddr
    maddr = Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")
    listener = demux.demultiplexed_listen(maddr, DemultiplexedConnType.MULTISTREAM_SELECT, mock_handler)
    listener.background_nursery = nursery
    nursery.start_soon(listener.listen, maddr)

    async def wrapped_serve(stream):
        await demux._classify_and_route(stream)

    await trio.serve_listeners(wrapped_serve, listeners)

async def client(port):
    print("Client connecting...")
    stream = await trio.open_tcp_stream("127.0.0.1", port)

    print("Client sending 3 bytes...")
    await stream.send_all(b"\x13/m")

    await trio.sleep(1)

    print("Client sending remaining 17 bytes...")
    await stream.send_all(b"ultistream/1.0.0\n")

    print("Client reading...")
    try:
        res = await stream.receive_some(1024)
        print(f"Client got: {res}")
    except Exception as e:
        print(f"Client error: {e}")

    await trio.sleep(1)
    print("Client closing")
    await stream.aclose()

async def main():
    async with trio.open_nursery() as nursery:
        port = await nursery.start(server, nursery)
        nursery.start_soon(client, port)

if __name__ == '__main__':
    trio.run(main)
