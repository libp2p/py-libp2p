import asyncio
import sys
import urllib.request

import click
import multiaddr

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr


PROTOCOL_ID = '/chat/1.0.0'


async def read_data(stream):
    while True:
        read_string = await stream.read()
        if read_string is not None:
            read_string = read_string.decode()
            if read_string != "\n":
                # Green console colour: 	\x1b[32m
                # Reset console colour: 	\x1b[0m
                print("\x1b[32m %s\x1b[0m " % read_string, end="")


async def write_data(stream):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        await stream.write(line.encode())


async def run(port, destination):
    external_ip = urllib.request.urlopen(
        'https://v4.ident.me/').read().decode('utf8')
    host = await new_node(
        transport_opt=["/ip4/%s/tcp/%s" % (external_ip, port)])
    if not destination:  # its the server
        async def stream_handler(stream):
            asyncio.ensure_future(read_data(stream))
            asyncio.ensure_future(write_data(stream))
        host.set_stream_handler(PROTOCOL_ID, stream_handler)

        port = None
        ip = None
        for listener in host.network.listeners.values():
            for addr in listener.get_addrs():
                ip = addr.value_for_protocol('ip4')
                port = int(addr.value_for_protocol('tcp'))

        if not port:
            raise RuntimeError("was not able to find the actual local port")

        print("Run './examples/chat/chat.py -p %s -d /ip4/%s/tcp/%s/p2p/%s' on another console.\n" %
              (int(port) + 1, ip, port, host.get_id().pretty()))
        print("\nWaiting for incoming connection\n\n")

    else: # its the client
        m = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(m)
        # Associate the peer with local ip address
        await host.connect(info)

        # Start a stream with the destination.
        # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        asyncio.ensure_future(read_data(stream))
        asyncio.ensure_future(write_data(stream))
        print("Connected to peer %s" % info.addrs[0])


@click.command()
@click.option('--port', '-p', help='source port number', default=8000)
@click.option('--destination', '-d', help="Destination multiaddr string")
@click.option('--help', is_flag=True, default=False, help='display help')
# @click.option('--debug', is_flag=True, default=False, help='Debug generates the same node ID on every execution')
def main(port, destination, help):

    if help:
        print("This program demonstrates a simple p2p chat application using libp2p\n\n")
        print("Usage: Run './chat -p <SOURCE_PORT>' where <SOURCE_PORT> can be any port number.")
        print("Now run './chat -p <PORT> -d <MULTIADDR>' where <MULTIADDR> is multiaddress of previous listener host.")
        return

    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(run(port, destination))
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == '__main__':
    main()
