import os
import logging
import trio
import multiaddr
from libp2p import new_host, generate_new_ed25519_identity
import libp2p.utils.paths as paths

logging.basicConfig(level=logging.INFO)
logging.getLogger("libp2p.transport.quic.security").setLevel(logging.INFO)
logging.getLogger("libp2p.network.basic_host").setLevel(logging.INFO)

listen = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/udp/{os.environ['PORT']}/quic-v1")]
host = new_host(
    key_pair=generate_new_ed25519_identity(),
    listen_addrs=listen,
    enable_quic=True,
    enable_autotls=True,
)

async def main():
    async with host.run(listen_addrs=listen):
        await host.initiate_autotls_procedure(public_ip=os.environ["PUBLIC_IP"])
        print("cert:", paths.AUTOTLS_CERT_PATH, paths.AUTOTLS_CERT_PATH.exists())
        print("key :", paths.AUTOTLS_KEY_PATH, paths.AUTOTLS_KEY_PATH.exists())
        await trio.sleep_forever()

trio.run(main)