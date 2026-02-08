import argparse
import logging

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import (
    Pubsub,
)
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.tools.async_service.trio_service import (
    background_trio_service,
)
from libp2p.utils.address_validation import (
    find_free_port,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set default to DEBUG for more verbose output
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("floodsub-demo")
CHAT_TOPIC = "floodsub-chat"
FLOODSUB_PROTOCOL_ID = TProtocol("/floodsub/1.0.0")


# Generate a key pair for the node
key_pair = create_new_key_pair()


async def receive_loop(subscription, termination_event):
    logger.debug("Starting receive loop")
    while not termination_event.is_set():
        try:
            message = await subscription.get()
            from libp2p.peer.id import ID

            logger.info(f"From peer: {ID(message.from_id).to_base58()}")
            print(f"Received message: {message.data.decode('utf-8')}")
        except Exception:
            logger.exception("Error in receive loop")
            await trio.sleep(1)


async def publish_loop(pubsub, topic, termination_event):
    """Continuously read input from user and publish to the topic."""
    logger.debug("Starting publish loop...")
    print("Type messages to send (press Enter to send):")
    while not termination_event.is_set():
        try:
            # Use trio's run_sync_in_worker_thread to avoid blocking the event loop
            message = await trio.to_thread.run_sync(input)
            if message.lower() == "quit":
                termination_event.set()  # Signal termination
                break
            if message:
                logger.debug(f"Publishing message: {message}")
                await pubsub.publish(topic, message.encode())
                print(f"Published: {message}")
        except Exception:
            logger.exception("Error in publish loop")
            await trio.sleep(1)  # Avoid tight loop on error


async def monitor_peer_topics(pubsub, nursery, termination_event):
    """
    Monitor for new topics that peers are subscribed to and
    automatically subscribe the server to those topics.
    """
    # Keep track of topics we've already subscribed to
    subscribed_topics = set()

    while not termination_event.is_set():
        # Check for new topics in peer_topics
        for topic in pubsub.peer_topics.keys():
            if topic not in subscribed_topics:
                logger.info(f"Auto-subscribing to new topic: {topic}")
                subscription = await pubsub.subscribe(topic)
                subscribed_topics.add(topic)
                # Start a receive loop for this topic
                nursery.start_soon(receive_loop, subscription, termination_event)

        # Check every 2 seconds for new topics
        await trio.sleep(2)


async def run(topic: str, destination: str | None, port: int | None) -> None:
    from libp2p.utils.address_validation import (
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port is None or port == 0:
        port = find_free_port()
        logger.info(f"Using random available port: {port}")

    listen_addrs = get_available_interfaces(port)

    # Create a new libp2p host
    host = new_host(
        key_pair=key_pair,
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
    )
    # Log available protocols
    logger.debug(f"Host ID: {host.get_id()}")
    logger.debug(
        f"Host multiselect protocols: "
        f"{host.get_mux().get_protocols() if hasattr(host, 'get_mux') else 'N/A'}"
    )
    # Create and start floodsub
    floodsub = FloodSub(
        protocols=[FLOODSUB_PROTOCOL_ID],
    )

    # pubsub = Pubsub(host, gossipsub)
    pubsub = Pubsub(host, floodsub)
    termination_event = trio.Event()  # Event to signal termination
    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        logger.info(f"Node started with peer ID: {host.get_id()}")
        logger.info("Initializing PubSub and GossipSub...")
        async with background_trio_service(pubsub):
            # async with background_trio_service(gossipsub):
            logger.info("Pubsub and Floodsub services started.")
            await pubsub.wait_until_ready()
            # logger.info("Pubsub ready.")

            # Subscribe to the topic
            subscription = await pubsub.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")

            if not destination:
                # Server mode
                # Get all available addresses with peer ID
                all_addrs = host.get_addrs()

                logger.info("Listener ready, listening on:")
                for addr in all_addrs:
                    logger.info(f"{addr}")

                # Use optimal address for the client command
                optimal_addr = get_optimal_binding_address(port)
                optimal_addr_with_peer = (
                    f"{optimal_addr}/p2p/{host.get_id().to_string()}"
                )
                logger.info(
                    f"\nRun this from the same folder in another console:\n\n"
                    f" floodsub-demo -d {optimal_addr_with_peer}\n"
                )
                logger.info("Waiting for peers...")

                # Start topic monitoring to auto-subscribe to client topics
                nursery.start_soon(
                    monitor_peer_topics, pubsub, nursery, termination_event
                )

                # Start message publish and receive loops
                nursery.start_soon(receive_loop, subscription, termination_event)
                nursery.start_soon(publish_loop, pubsub, topic, termination_event)
            else:
                # Client mode
                maddr = multiaddr.Multiaddr(destination)
                protocols_in_maddr = maddr.protocols()
                info = info_from_p2p_addr(maddr)
                logger.debug(f"Multiaddr protocols: {protocols_in_maddr}")
                logger.info(
                    f"Connecting to peer: {info.peer_id} "
                    f"using protocols: {protocols_in_maddr}"
                )
                try:
                    await host.connect(info)
                    logger.info(f"Connected to peer: {info.peer_id}")
                    if logger.isEnabledFor(logging.DEBUG):
                        await trio.sleep(1)
                        logger.debug(f"After connection, pubsub.peers: {pubsub.peers}")
                        peer_protocols = [
                            floodsub.peer_protocol.get(p) for p in pubsub.peers.keys()
                        ]
                        logger.debug(f"Peer protocols: {peer_protocols}")

                    # Start the loops
                    nursery.start_soon(receive_loop, subscription, termination_event)
                    nursery.start_soon(publish_loop, pubsub, topic, termination_event)
                except Exception:
                    logger.exception(f"Failed to connect to peer: {info.peer_id}")
                    return

            await termination_event.wait()  # Wait for termination signal

        # Ensure all tasks are completed before exiting
        nursery.cancel_scope.cancel()

    print("Application shutdown complete")  # Print shutdown message


def main() -> None:
    description = """
    This program demonstrates a pubsub p2p chat application using libp2p with
    the gossipsub protocol as the pubsub router.
    To use it, first run 'python pubsub.py -p <PORT> -t <TOPIC>',
    where <PORT> is the port number,
    and <TOPIC> is the name of the topic you want to subscribe to.
    Then, run another instance with 'python pubsub.py -p <ANOTHER_PORT> -t <TOPIC>
    -d <DESTINATION>', where <DESTINATION> is the multiaddress of the previous
    listener host. Messages typed in either terminal will be received by all peers
    subscribed to the same topic.
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-t",
        "--topic",
        type=str,
        help="topic name to subscribe",
        default=CHAT_TOPIC,
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
        default=None,
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
