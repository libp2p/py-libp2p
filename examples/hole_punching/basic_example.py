import argparse

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.protocols.dcutr.dcutr import DCUTR_PROTOCOL_ID, DCUtRProtocol


async def run_listener():
    """Run as listener peer"""
    print("Starting listener...")

    host = new_host()
    dcutr = DCUtRProtocol(host)

    # Register DCUtR handler
    host.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr.handle_inbound_stream)  # type: ignore

    listen_addr = Multiaddr("/ip4/127.0.0.1/tcp/4002")

    async with host.run(listen_addrs=[listen_addr]):
        print(f"Listener ID: {host.get_id()}")
        print(f"Addresses: {host.get_addrs()}")

        # Keep running
        await trio.sleep_forever()


async def run_dialer(target_id):
    """Run as dialer peer"""
    print("Starting dialer...")

    host = new_host()
    dcutr = DCUtRProtocol(host)

    host.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr.handle_inbound_stream)  # type: ignore

    listen_addr = Multiaddr("/ip4/127.0.0.1/tcp/4003")

    async with host.run(listen_addrs=[listen_addr]):
        print(f"Dialer ID: {host.get_id()}")

        try:
            # Connect to target
            target_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/4002/p2p/{target_id}")
            peer_info = info_from_p2p_addr(target_addr)
            await host.connect(peer_info)
            print("Connected!")

            # Try hole punch
            success = await dcutr.upgrade_connection(peer_info.peer_id)
            print(f"Hole punch result: {success}")

        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["listen", "dial"], required=True)
    parser.add_argument("--target", help="Target peer ID for dial mode")

    args = parser.parse_args()

    if args.mode == "listen":
        trio.run(run_listener)
    else:
        if not args.target:
            print("Need --target for dial mode")
            return
        trio.run(run_dialer, args.target)


if __name__ == "__main__":
    main()
