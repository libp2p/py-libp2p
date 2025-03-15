
import argparse
import logging
import trio
import multiaddr
from libp2p import new_host
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service.trio_service import background_trio_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pubsub-chat")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/gossipsub/1.0.0")

async def receive_loop(subscription):
    while True:
        message = await subscription.get()
        logger.info(f"Received message: {message.data.decode('utf-8')}")
        logger.info(f"From peer: {message.from_id}")

async def publish_loop(pubsub: Pubsub, topic: str) -> None:
    logger.info("Enter message to publish (or 'quit' to exit): ")
    while True:
        message = await trio.to_thread.run_sync(input)
        if message.lower() == 'quit':
            logger.info("Exiting publish loop.")
            nursery.cancel_scope.cancel()
            break
        await pubsub.publish(topic, message.encode())
        logger.debug(f"Published message to topic {topic}: {message}")

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
        logger.info(f"Node started with peer ID: {host.get_id()}")
        logger.info(f"Subscribed to topic: {topic}")
        logger.debug(f"Destination is: {destination}")
        logger.info("Initializing pubsub...")
        async with background_trio_service(pubsub) as manager:
            
            logger.info("Pubsub initialized.")
            await pubsub.wait_until_ready()
            logger.info("Pubsub ready.")

            if not destination:
                logger.info(
                    "Run this script in another console with:\n"
                    f"python pubsub.py -p {int(port) + 1} "
                    f"-d /ip4/{localhost_ip}/tcp/{port}/p2p/{host.get_id()}\n"
                )
                logger.info("Waiting for peers...")

                # Start message publish and receive loops
                nursery.start_soon(receive_loop, subscription)
                nursery.start_soon(publish_loop, pubsub, topic)

            else:
                # Client mode
                maddr = multiaddr.Multiaddr(destination)
                info = info_from_p2p_addr(maddr)
                logger.info(f"Connecting to peer: {info.peer_id}")
                await host.connect(info)
                logger.info(f"Connected to peer: {info.peer_id}")
                
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

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Set debug level if verbose flag is provided
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    logger.info("Running pubsub chat example...")
    logger.info(f"Your selected topic is: {args.topic}")

    try:
        trio.run(run, *(args.topic, args.destination, args.port))
    except KeyboardInterrupt:
        logger.info("Application terminated by user")


if __name__ == "__main__":
    main()
