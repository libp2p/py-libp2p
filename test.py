from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.tls.transport import TLSTransport


async def run():
    # 1. Setup Listener
    listener_key_pair = create_new_key_pair()
    listener_tls = TLSTransport(listener_key_pair)

    listener_host = new_host(
        sec_opt={"/tls/1.0.0": listener_tls},
        key_pair=listener_key_pair
    )

    # 2. Setup Dialer
    dialer_key_pair = create_new_key_pair()
    dialer_tls = TLSTransport(dialer_key_pair)

    dialer_host = new_host(
        sec_opt={"/tls/1.0.0": dialer_tls},
        key_pair=dialer_key_pair
    )

    # 3. Run hosts and connect
    async with listener_host.run([]), dialer_host.run([]):
        # Listen on localhost with a random port
        listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0")
        await listener_host.get_network().listen(listen_maddr)

        # Get the actual listening address
        actual_listen_addrs = listener_host.get_addrs()
        target_maddr = actual_listen_addrs[0]
        print(f"Listener started on: {target_maddr}")

        # Connect from dialer to listener
        target_peer_info = info_from_p2p_addr(target_maddr)
        print(f"Dialing from {dialer_host.get_id()} to {target_peer_info.peer_id}...")

        await dialer_host.connect(target_peer_info)
        print("Connected securely over TLS!")

if __name__ == "__main__":
    trio.run(run)
