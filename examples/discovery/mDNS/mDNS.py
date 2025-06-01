import secrets
import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair

async def main():
    # Generate a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Listen on a random TCP port
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")

    # Enable mDNS discovery
    host = new_host(key_pair=key_pair, enable_mDNS=True)

    async with host.run(listen_addrs=[listen_addr]):
        print("Host started!")
        print("Peer ID:", host.get_id())
        print("Listening on:", [str(addr) for addr in host.get_addrs()])

        # Print discovered peers via mDNS
        print("Waiting for mDNS peer discovery events (Ctrl+C to exit)...")
        try:
            while True:
                # Print all known peers every 5 seconds
                peers = host.get_peerstore().peer_ids()
                print("Known peers:", [str(p) for p in peers if p != host.get_id()])
                await trio.sleep(5)
        except KeyboardInterrupt:
            print("Exiting...")

if __name__ == "__main__":
    trio.run(main)