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
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p import (
    new_host,
)
from libp2p.abc import (
    INetStream,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.identity.identify import (
    ID as ID_IDENTIFY,
    identify_handler_for,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify_push import (
    ID_PUSH as ID_IDENTIFY_PUSH,
    identify_push_handler_for,
    push_identify_to_peer,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Configure logging
logger = logging.getLogger("libp2p.identity.identify-push-example")


def custom_identify_push_handler_for(host):
    """
    Create a custom handler for the identify/push protocol that logs and prints
    the identity information received from the dialer.
    """

    async def handle_identify_push(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id

        try:
            # Read the identify message from the stream
            data = await stream.read()
            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            # Log and print the identify information
            logger.info("Received identify/push from peer %s", peer_id)
            print(f"\n==== Received identify/push from peer {peer_id} ====")

            if identify_msg.HasField("protocol_version"):
                logger.info("  Protocol Version: %s", identify_msg.protocol_version)
                print(f"  Protocol Version: {identify_msg.protocol_version}")

            if identify_msg.HasField("agent_version"):
                logger.info("  Agent Version: %s", identify_msg.agent_version)
                print(f"  Agent Version: {identify_msg.agent_version}")

            if identify_msg.HasField("public_key"):
                logger.info(
                    "  Public Key: %s", identify_msg.public_key.hex()[:16] + "..."
                )
                print(f"  Public Key: {identify_msg.public_key.hex()[:16]}...")

            if identify_msg.listen_addrs:
                addrs = [Multiaddr(addr) for addr in identify_msg.listen_addrs]
                logger.info("  Listen Addresses: %s", addrs)
                print("  Listen Addresses:")
                for addr in addrs:
                    print(f"    - {addr}")

            if identify_msg.HasField("observed_addr") and identify_msg.observed_addr:
                observed_addr = Multiaddr(identify_msg.observed_addr)
                logger.info("  Observed Address: %s", observed_addr)
                print(f"  Observed Address: {observed_addr}")

            if identify_msg.protocols:
                logger.info("  Protocols: %s", identify_msg.protocols)
                print("  Protocols:")
                for protocol in identify_msg.protocols:
                    print(f"    - {protocol}")

            # Update the peerstore with the new information as usual
            peerstore = host.get_peerstore()
            from libp2p.identity.identify_push.identify_push import (
                _update_peerstore_from_identify,
            )

            await _update_peerstore_from_identify(peerstore, peer_id, identify_msg)

            logger.info("Successfully processed identify/push from peer %s", peer_id)
            print(f"\nSuccessfully processed identify/push from peer {peer_id}")

        except Exception as e:
            logger.error("Error processing identify/push from %s: %s", peer_id, e)
            print(f"\nError processing identify/push from {peer_id}: {e}")
        finally:
            # Close the stream after processing
            await stream.close()

    return handle_identify_push


async def run_listener(port: int) -> None:
    """Run a host in listener mode."""
    print(f"\n==== Starting Identify-Push Listener on port {port} ====\n")

    # Create key pair for the listener
    key_pair = create_new_key_pair()

    # Create the listener host
    host = new_host(key_pair=key_pair)

    # Set up the identify and identify/push handlers
    host.set_stream_handler(ID_IDENTIFY, identify_handler_for(host))
    host.set_stream_handler(ID_IDENTIFY_PUSH, custom_identify_push_handler_for(host))

    # Start listening
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run([listen_addr]):
        addr = host.get_addrs()[0]
        logger.info("Listener host ready!")
        print("Listener host ready!")

        logger.info(f"Listening on: {addr}")
        print(f"Listening on: {addr}")

        logger.info(f"Peer ID: {host.get_id().pretty()}")
        print(f"Peer ID: {host.get_id().pretty()}")

        print("\nRun dialer with command:")
        print(f"identify-push-listener-dialer-demo -d {addr}")
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
    host.set_stream_handler(ID_IDENTIFY, identify_handler_for(host))
    host.set_stream_handler(ID_IDENTIFY_PUSH, identify_push_handler_for(host))

    # Start listening on a different port
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run([listen_addr]):
        logger.info("Dialer host ready!")
        print("Dialer host ready!")

        logger.info(f"Listening on: {host.get_addrs()[0]}")
        print(f"Listening on: {host.get_addrs()[0]}")

        # Parse the destination multiaddress and connect to the listener
        maddr = multiaddr.Multiaddr(destination)
        peer_info = info_from_p2p_addr(maddr)
        logger.info(f"Connecting to peer: {peer_info.peer_id}")
        print(f"\nConnecting to peer: {peer_info.peer_id}")

        try:
            await host.connect(peer_info)
            logger.info("Successfully connected to listener!")
            print("Successfully connected to listener!")

            # Push identify information to the listener
            logger.info("Pushing identify information to listener...")
            print("\nPushing identify information to listener...")

            try:
                # Call push_identify_to_peer which returns a boolean
                success = await push_identify_to_peer(host, peer_info.peer_id)

                if success:
                    logger.info("Identify push completed successfully!")
                    print("Identify push completed successfully!")

                    logger.info("Example completed successfully!")
                    print("\nExample completed successfully!")
                else:
                    logger.warning("Identify push didn't complete successfully.")
                    print("\nWarning: Identify push didn't complete successfully.")

                    logger.warning("Example completed with warnings.")
                    print("Example completed with warnings.")
            except Exception as e:
                logger.error(f"Error during identify push: {str(e)}")
                print(f"\nError during identify push: {str(e)}")

                logger.error("Example completed with errors.")
                print("Example completed with errors.")
                # Continue execution despite the push error

        except Exception as e:
            logger.error(f"Error during dialer operation: {str(e)}")
            print(f"\nError during dialer operation: {str(e)}")
            raise


def main() -> None:
    """Parse arguments and start the appropriate mode."""
    description = """
    This program demonstrates the libp2p identify/push protocol.
    Without arguments, it runs as a listener on random port.
    With -d parameter, it runs as a dialer on random port.
    """

    example = (
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example}",
    )
    args = parser.parse_args()

    try:
        if args.destination:
            # Run in dialer mode with random available port if not specified
            trio.run(run_dialer, args.port, args.destination)
        else:
            # Run in listener mode with random available port if not specified
            trio.run(run_listener, args.port)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        logger.info("Interrupted by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
        logger.error("Error: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
