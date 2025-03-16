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
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.security.secio.transport import ID as SECIO, Transport as SecioTransport
from libp2p.transport.typing import (
    TMuxerOptions,
    TSecurityOptions,
)
from libp2p.tools.factories import security_options_factory_factory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    # format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pubsub-chat")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/gossipsub/1.0.0")

# Generate a key pair for the node
key_pair = create_new_key_pair()
logger.info(f"Node {key_pair.public_key}: Created key pair")

NOISE_PROTOCOL_ID = TProtocol("/noise")
security_options_factory = security_options_factory_factory()
security_options = security_options_factory(key_pair)

async def receive_loop(subscription):
    while True:
        message = await subscription.get()
        logger.info(f"Received message: {message.data.decode('utf-8')}")
        logger.info(f"From peer: {message.from_id}")

async def publish_loop(pubsub, topic):
    """Continuously read input from user and publish to the topic."""
    print("Starting publish loop...")
    print("Type messages to send (press Enter to send):")
    while True:
        try:
            # Use trio's run_sync_in_worker_thread to avoid blocking the event loop
            message = await trio.to_thread.run_sync(input)
            if message.lower() == "quit":
                print("Exiting publish loop.")
                break
            if message:
                logger.debug(f"Publishing message: {message}")
                await pubsub.publish(topic, message.encode())
                print(f"Published: {message}")
        except Exception as e:
            # Log the complete exception traceback
            logger.exception("Error in publish loop")
            await trio.sleep(1)  # Avoid tight loop on error


async def connection_monitor(host, pubsub, interval=5):
    """Monitor and log connected peers periodically."""
    while True:
        try:
            peers = host.get_connected_peers()
            if peers:
                print(f"Currently connected to {len(peers)} peers: {[p.pretty() for p in peers]}")
                # Check if these peers are in the pubsub peers list
                pubsub_peers = list(pubsub.peers.keys())
                print(f"PubSub peers: {len(pubsub_peers)}")
                if pubsub_peers:
                    print(f"PubSub peer IDs: {[p.pretty() for p in pubsub_peers]}")
                
                # Check peer topics
                if hasattr(pubsub, "peer_topics") and pubsub.peer_topics:
                    for topic, peers_in_topic in pubsub.peer_topics.items():
                        print(f"Peers subscribed to topic '{topic}': {len(peers_in_topic)}")
                        if peers_in_topic:
                            print(f"Topic '{topic}' peer IDs: {[p.pretty() for p in peers_in_topic]}")
            else:
                print("Not connected to any peers")
        except Exception as e:
            print(f"Error in connection monitor: {e}")
        
        await trio.sleep(interval)

async def run(topic: str, destination: str | None, port: int) -> None:
    # Initialize network settings
    localhost_ip = "127.0.0.1"
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    

    # Create a new libp2p host
    host = new_host(
    key_pair=key_pair,
    muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
    sec_opt=security_options
    )   
    # Create and start gossipsub
    gossipsub = GossipSub(
        protocols=[GOSSIPSUB_PROTOCOL_ID],
        degree=6,          # Number of peers to maintain in mesh
        degree_low=2,      # Lower bound for mesh peers
        degree_high=12,    # Upper bound for mesh peers
        time_to_live=30    # TTL for message cache in seconds
    )

    pubsub = Pubsub(host, gossipsub)
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        logger.info(f"Node started with peer ID: {host.get_id()}")
        logger.info(f"Subscribed to topic: {topic}")
        logger.debug(f"Destination is: {destination}")
        logger.info("Initializing pubsub...")
        async with background_trio_service(pubsub) as manager:
            logger.info("Pubsub initialized.")
            await pubsub.wait_until_ready()
            logger.info("Pubsub ready.")
            subscription = await pubsub.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")
            nursery.start_soon(connection_monitor, host, pubsub)
            if not destination:
                logger.info(
                    "Run this script in another console with:\n"
                    f"python3 pubsub.py -p {int(port) + 1} "
                    f"-d /ip4/{localhost_ip}/tcp/{port}/p2p/{host.get_id()}\n"
                )
                logger.info("Waiting for peers...")
                # Start message publish and receive loops
                nursery.start_soon(receive_loop, subscription)
                nursery.start_soon(publish_loop, pubsub, topic)
            else:
                # Client mode
                maddr = multiaddr.Multiaddr(destination)
                protocols_in_maddr = maddr.protocols()
                info = info_from_p2p_addr(maddr)
                logger.debug(f"Multiaddr protocols: {protocols_in_maddr}")
                logger.info(f"Connecting to peer: {info.peer_id} using protocols: {protocols_in_maddr}")
                try:
                    await host.connect(info)
                    logger.info(f"Connected to peer: {info.peer_id}")   
                except Exception as e:
                    logger.exception(f"Failed to connect to peer: {info.peer_id} using protocols: {protocols_in_maddr}")
                    return
                # Debug: log the contents and types for pubsub.peers
                logger.debug(f"After connection, pubsub.peers: {pubsub.peers} (keys types: {[type(p) for p in pubsub.peers.keys()]})")
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
