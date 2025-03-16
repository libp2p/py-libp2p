import argparse
import logging
import trio
import multiaddr
import base58
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
from libp2p.io.msgio import encode_varint_prefixed
from libp2p.pubsub.pb import rpc_pb2

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set default to DEBUG for more verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pubsub-debug")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")

# Generate a key pair for the node
key_pair = create_new_key_pair()
logger.info(f"Node {key_pair.public_key}: Created key pair")

# Security options
NOISE_PROTOCOL_ID = TProtocol("/noise")
security_options_factory = security_options_factory_factory()
security_options = security_options_factory(key_pair)

async def receive_loop(subscription):
    logger.debug("Starting receive loop")
    while True:
        try:
            message = await subscription.get()
            print(f"Received message: {message.data.decode('utf-8')}")
            logger.info(f"From peer: {base58.b58encode(message.from_id).decode()}")
        except Exception as e:
            logger.exception("Error in receive loop")
            await trio.sleep(1)

async def publish_loop(pubsub, topic):
    """Continuously read input from user and publish to the topic."""
    logger.debug("Starting publish loop...")
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
            logger.exception("Error in publish loop")
            await trio.sleep(1)  # Avoid tight loop on error

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
    # Log available protocols
    logger.debug(f"Host ID: {host.get_id()}")
    logger.debug(f"Host multiselect protocols: {host.get_mux().get_protocols() if hasattr(host, 'get_mux') else 'N/A'}")
    # Create and start gossipsub with optimized parameters for testing
    gossipsub = GossipSub(
        protocols=[GOSSIPSUB_PROTOCOL_ID],
        degree=3,          # Number of peers to maintain in mesh
        degree_low=2,      # Lower bound for mesh peers
        degree_high=4,     # Upper bound for mesh peers
        time_to_live=60,   # TTL for message cache in seconds
        gossip_window=2,   # Smaller window for faster gossip
        gossip_history=5,  # Keep more history
        heartbeat_initial_delay=2.0,  # Start heartbeats sooner
        heartbeat_interval=5  # More frequent heartbeats for testing
    )

    pubsub = Pubsub(host, gossipsub)
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        logger.info(f"Node started with peer ID: {host.get_id()}")
        logger.info(f"Listening on: {listen_addr}")
        logger.info("Initializing PubSub and GossipSub...")
        async with background_trio_service(pubsub) as pubsub_manager:
            async with background_trio_service(gossipsub) as gossipsub_manager:
                logger.info("Pubsub and GossipSub services started.")
                await pubsub.wait_until_ready()
                logger.info("Pubsub ready.")
                
                # Subscribe to the topic
                subscription = await pubsub.subscribe(topic)
                logger.info(f"Subscribed to topic: {topic}")
                
                if not destination:
                    # Server mode
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

                        # Give some time for the connection to establish and protocols to negotiate
                        # logger.info("Waiting for connection to stabilize...")
                        # await trio.sleep(3)
                        
                        logger.debug(f"After connection, pubsub.peers: {pubsub.peers}")
                        logger.debug(f"Peer protocols: {[gossipsub.peer_protocol.get(p) for p in pubsub.peers.keys()]}")
                        
                        # Start the loops
                        nursery.start_soon(receive_loop, subscription)
                        nursery.start_soon(publish_loop, pubsub, topic)
                    except Exception as e:
                        logger.exception(f"Failed to connect to peer: {info.peer_id}")
                        return

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
