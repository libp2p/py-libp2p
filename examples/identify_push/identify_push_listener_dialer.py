#!/usr/bin/env python3
"""
Example demonstrating the identify/push protocol with separate listener and dialer
roles.

This example shows how to:
1. Set up a listener host with the identify/push protocol handler
2. Connect to the listener from a dialer peer
3. Push identify information to the listener
4. Receive and process identify/push messages

Usage:
    # First run this script as a listener (default port 8888):
    python identify_push_listener_dialer.py

    # Then in another console, run as a dialer (default port 8889):
    python identify_push_listener_dialer.py -d /ip4/127.0.0.1/tcp/8888/p2p/PEER_ID
    (where PEER_ID is the peer ID displayed by the listener)
"""

import argparse
import logging
import sys

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.identity.identify import (
    identify_handler_for,
)
from libp2p.identity.identify_push import (
    ID_PUSH,
    identify_push_handler_for,
    push_identify_to_peer,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("libp2p.identity.identify-push-example")


async def run_listener(port: int) -> None:
    """Run a host in listener mode."""
    print(f"\n==== Starting Identify-Push Listener on port {port} ====\n")

    # Create key pair for the listener
    key_pair = create_new_key_pair()

    # Create the listener host
    host = new_host(key_pair=key_pair)

    # Set up the identify and identify/push handlers
    host.set_stream_handler(TProtocol("/ipfs/id/1.0.0"), identify_handler_for(host))
    host.set_stream_handler(ID_PUSH, identify_push_handler_for(host))

    # Start listening
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run([listen_addr]):
        addr = host.get_addrs()[0]
        logger.info("Listener host ready")
        logger.info("Listening on: %s", addr)
        logger.info("Peer ID: %s", host.get_id().pretty())

        # Print user-friendly information
        print("Listener host ready!")
        print(f"Listening on: {addr}")
        print(f"Peer ID: {host.get_id().pretty()}")
        print("\nRun dialer with command:")
        print(f"python identify_push_listener_dialer.py -d {addr}")
        print("\nWaiting for incoming connections... (Ctrl+C to exit)")

        # Keep running until interrupted
        await trio.sleep_forever()


async def run_dialer(port: int, destination: str) -> None:
    """Run a host in dialer mode that connects to a listener."""
    print(f"\n==== Starting Identify-Push Dialer on port {port} ====\n")

    # Create key pair for the dialer
    key_pair = create_new_key_pair()

    # Create the dialer host
    host = new_host(key_pair=key_pair)

    # Set up the identify and identify/push handlers
    host.set_stream_handler(TProtocol("/ipfs/id/1.0.0"), identify_handler_for(host))
    host.set_stream_handler(ID_PUSH, identify_push_handler_for(host))

    # Start listening on a different port
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run([listen_addr]):
        logger.info("Dialer host ready")
        logger.info("Listening on: %s", host.get_addrs()[0])

        print("Dialer host ready!")
        print(f"Listening on: {host.get_addrs()[0]}")

        # Parse the destination multiaddress and connect to the listener
        maddr = multiaddr.Multiaddr(destination)
        peer_info = info_from_p2p_addr(maddr)
        logger.info("Connecting to peer: %s", peer_info.peer_id)
        print(f"\nConnecting to peer: {peer_info.peer_id}")

        try:
            await host.connect(peer_info)
            logger.info("Successfully connected to listener")
            print("Successfully connected to listener!")

            # Wait briefly for the connection to establish
            await trio.sleep(1)

            # Push identify information to the listener
            logger.info("Pushing identify information to listener")
            print("\nPushing identify information to listener...")
            await push_identify_to_peer(host, peer_info.peer_id)

            logger.info("Identify push completed. Waiting a moment...")
            print("Identify push completed successfully!")

            # Keep the connection open for a bit to observe what happens
            print("Waiting a moment to keep connection open...")
            await trio.sleep(5)

            logger.info("Example completed successfully")
            print("\nExample completed successfully!")
        except Exception as e:
            logger.error("Error during dialer operation: %s", str(e))
            print(f"\nError during dialer operation: {str(e)}")
            raise


def main() -> None:
    """Parse arguments and start the appropriate mode."""
    description = """
    This program demonstrates the libp2p identify/push protocol.
    Without arguments, it runs as a listener on port 8888.
    With -d parameter, it runs as a dialer on port 8889.
    """

    example = (
        "/ip4/127.0.0.1/tcp/8888/p2p/QmQn4SwGkDZkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="port to listen on (default: 8888 for listener, 8889 for dialer)",
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example}",
    )
    args = parser.parse_args()

    try:
        if args.destination:
            # Run in dialer mode with default port 8889 if not specified
            port = args.port if args.port is not None else 8889
            trio.run(run_dialer, port, args.destination)
        else:
            # Run in listener mode with default port 8888 if not specified
            port = args.port if args.port is not None else 8888
            trio.run(run_listener, port)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        logger.info("Interrupted by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
        logger.error("Error: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
