import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port


async def run_test():
    port = find_free_port()

    listen_addrs = [
        multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}"),
        multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws"),
        multiaddr.Multiaddr(f"/ip4/127.0.0.1/udp/{port}/quic"),
    ]

    server = new_host(key_pair=create_new_key_pair(), listen_addrs=listen_addrs)
    async with server.run(listen_addrs=listen_addrs):
        print("Success!")


trio.run(run_test)
