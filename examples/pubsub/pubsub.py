import argparse
import trio
import multiaddr
from libp2p import new_host
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr

GOSSIPSUB_PROTOCOL_ID = TProtocol("/gossipsub/1.0.0")

async def receive_loop(subscription):
    while True:
        message = await subscription.get()
        print(f"Received message: {message.data.decode('utf-8')}")
        print(f"From peer: {message.from_id.pretty()}")

async def publish_loop(pubsub: Pubsub, topic: str) -> None:
    print("Enter message to publish (or 'quit' to exit): ")
    while True:
        message = await trio.to_thread.run_sync(input)
        if message.lower() == 'quit':
            print("Exiting publish loop.")
            nursery.cancel_scope.cancel()
            break
        await pubsub.publish(topic, message.encode())

async def run(topic: str, destination: str | None, port: int) -> None:
    # Initialize network settings
    localhost_ip = "127.0.0.1"
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Create a new libp2p host
    host = new_host()
    # Create and start gossipsub
    gossipsub = GossipSub(
        protocols=[GOSSIPSUB_PROTOCOL_ID],
        degree=6,          # Number of peers to maintain in mesh
        degree_low=2,      # Lower bound for mesh peers
        degree_high=12,    # Upper bound for mesh peers
        time_to_live=30    # TTL for message cache in seconds
    )

    pubsub = Pubsub(host, gossipsub)
    subscription = await pubsub.subscribe(topic)
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        print(f"Node started with peer ID: {host.get_id().pretty()}")
        print(f"Subscribed to topic: {topic}")
        print(f"Destination is: {destination}")
        print("Initializing pubsub...")
        nursery.start_soon(pubsub.run)
        print("Pubsub initialized.")
        await pubsub.wait_until_ready()
        print("Pubsub ready.")

        if not destination:
            print(
                "Run this script in another console with:\n"
                f"python pubsub.py -p {int(port) + 1} "
                f"-d /ip4/{localhost_ip}/tcp/{port}/p2p/{host.get_id().pretty()}\n"
            )
            print("Waiting for peers...")

            # Start message publish and receive loops
            nursery.start_soon(receive_loop, subscription)
            nursery.start_soon(publish_loop, pubsub, topic)

        else:
            # Client mode
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            print(f"Connecting to peer: {info.peer_id.pretty()}")
            await host.connect(info)
            print(f"Connected to peer: {info.peer_id.pretty()}")
             
            # Start message publish and receive loops
            nursery.start_soon(publish_loop, pubsub, topic)
            nursery.start_soon(receive_loop, subscription)

        await trio.sleep_forever()
        

def main() -> None:

    description = """
    This program demonstrates a pubsub p2p chat application using libp2p.
    """

    ChatTopic = "pubsub-chat"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-t",
        "--topic",
        type=str,
        help="topic name to subscribe",
        default=ChatTopic,
    )

    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="Address of peer to connect to",
        default=None,
    )

    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="Port to listen on",
        default=8080,
    )

    args = parser.parse_args()

    print("Running pubsub chat example...")
    print(f"Your selected topic is: {args.topic}")

    try:
        trio.run(run, *(args.topic, args.destination, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()