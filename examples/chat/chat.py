import argparse
import asyncio
import sys
import urllib.request

import multiaddr

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr


PROTOCOL_ID = "/chat/1.0.0"


async def read_data(stream):
    while True:
        read_string = await stream.read()
        if read_string is not None:
            read_string = read_string.decode()
            if read_string != "\n":
                # Green console colour: 	\x1b[32m
                # Reset console colour: 	\x1b[0m
                print("\x1b[32m %s\x1b[0m " % read_string, end="")


# FIXME(mhchia): Reconsider whether we should use a thread pool here.
async def write_data(stream):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        await stream.write(line.encode())


async def run(port, destination):
    external_ip = urllib.request.urlopen("https://v4.ident.me/").read().decode("utf8")
    transport_opt = "/ip4/%s/tcp/%s" % (external_ip, port)
    host = await new_node(transport_opt=[transport_opt])

    await host.get_network().listen(multiaddr.Multiaddr(transport_opt))

    if not destination:  # its the server

        async def stream_handler(stream):
            asyncio.ensure_future(read_data(stream))
            asyncio.ensure_future(write_data(stream))

        host.set_stream_handler(PROTOCOL_ID, stream_handler)


        print(
            "Run './examples/chat/chat.py -p %s -d /ip4/%s/tcp/%s/p2p/%s' on another console.\n"
            % (int(port) + 1, external_ip, port, host.get_id().pretty())
        )
        print("\nWaiting for incoming connection\n\n")

    else:  # its the client
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)
        # Associate the peer with local ip address
        await host.connect(info)

        # Start a stream with the destination.
        # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        asyncio.ensure_future(read_data(stream))
        asyncio.ensure_future(write_data(stream))
        print("Connected to peer %s" % info.addrs[0])


def main():
    description = """
    This program demonstrates a simple p2p chat application using libp2p.
    To use it, first run 'python ./chat -p <PORT>', where <PORT> is the port number.
    Then, run another host with 'python ./chat -p <ANOTHER_PORT> -d <DESTINATION>',
    where <DESTINATION> is the multiaddress of the previous listener host.
    """
    example_maddr = (
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--debug",
        action="store_true",
        help="generate the same node ID on every execution",
    )
    parser.add_argument(
        "-p", "--port", default=8000, type=int, help="source port number"
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    args = parser.parse_args()

    if not args.port:
        raise RuntimeError("was not able to determine a local port")

    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(run(args.port, args.destination))
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
