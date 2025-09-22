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
    python identify_push_listener_dialer.py -d /ip4/[HOST_IP]/tcp/8888/p2p/PEER_ID
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
from libp2p.identity.identify.identify import (
    _remote_address_to_multiaddr,
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

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

# Configure logging
logger = logging.getLogger("libp2p.identity.identify-push-example")


def custom_identify_push_handler_for(host, use_varint_format: bool = True):
    """
    Create a custom handler for the identify/push protocol that logs and prints
    the identity information received from the dialer.

    Args:
        host: The libp2p host
        use_varint_format: If True, expect length-prefixed format; if False, expect
            raw protobuf

    """

    async def handle_identify_push(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id

        # Get remote address information
        try:
            remote_address = stream.get_remote_address()
            if remote_address:
                observed_multiaddr = _remote_address_to_multiaddr(remote_address)
                logger.info(
                    "Connection from remote peer %s, address: %s, multiaddr: %s",
                    peer_id,
                    remote_address,
                    observed_multiaddr,
                )
                print(f"\n🔗 Received identify/push request from peer: {peer_id}")
                # Add the peer ID to create a complete multiaddr
                complete_multiaddr = f"{observed_multiaddr}/p2p/{peer_id}"
                print(f"   Remote address: {complete_multiaddr}")
        except Exception as e:
            logger.error("Error getting remote address: %s", e)
            print(f"\n🔗 Received identify/push request from peer: {peer_id}")

        try:
            # Use the utility function to read the protobuf message
            from libp2p.utils.varint import read_length_prefixed_protobuf

            data = await read_length_prefixed_protobuf(stream, use_varint_format)

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
            print(f"✅ Successfully processed identify/push from peer {peer_id}")

        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Error processing identify/push from %s: %s", peer_id, error_msg
            )
            print(f"\nError processing identify/push from {peer_id}: {error_msg}")

            # Check for specific format mismatch errors
            if (
                "Error parsing message" in error_msg
                or "DecodeError" in error_msg
                or "ParseFromString" in error_msg
            ):
                print("\n" + "=" * 60)
                print("FORMAT MISMATCH DETECTED!")
                print("=" * 60)
                if use_varint_format:
                    print(
                        "You are using length-prefixed format (default) but the "
                        "dialer is using raw protobuf format."
                    )
                    print("\nTo fix this, run the dialer with the --raw-format flag:")
                    print(
                        "identify-push-listener-dialer-demo --raw-format -d <ADDRESS>"
                    )
                else:
                    print("You are using raw protobuf format but the dialer")
                    print("is using length-prefixed format (default).")
                    print(
                        "\nTo fix this, run the dialer without the --raw-format flag:"
                    )
                    print("identify-push-listener-dialer-demo -d <ADDRESS>")
                print("=" * 60)
        finally:
            # Close the stream after processing
            await stream.close()

    return handle_identify_push


async def run_listener(
    port: int, use_varint_format: bool = True, raw_format_flag: bool = False
) -> None:
    """Run a host in listener mode."""
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    format_name = "length-prefixed" if use_varint_format else "raw protobuf"
    print(
        f"\n==== Starting Identify-Push Listener on port {port} "
        f"(using {format_name} format) ====\n"
    )

    # Create key pair for the listener
    key_pair = create_new_key_pair()

    # Create the listener host
    host = new_host(key_pair=key_pair)

    # Set up the identify and identify/push handlers with specified format
    host.set_stream_handler(
        ID_IDENTIFY, identify_handler_for(host, use_varint_format=use_varint_format)
    )
    host.set_stream_handler(
        ID_IDENTIFY_PUSH,
        custom_identify_push_handler_for(host, use_varint_format=use_varint_format),
    )

    # Start listening on all available interfaces
    listen_addrs = get_available_interfaces(port)

    try:
        async with host.run(listen_addrs):
            all_addrs = host.get_addrs()
            logger.info("Listener host ready!")
            print("Listener host ready!")

            logger.info("Listener ready, listening on:")
            print("Listener ready, listening on:")
            for addr in all_addrs:
                logger.info(f"{addr}")
                print(f"{addr}")

            logger.info(f"Peer ID: {host.get_id().pretty()}")
            print(f"Peer ID: {host.get_id().pretty()}")

            # Use the first address as the default for the dialer command
            default_addr = all_addrs[0]
            print("\nRun this from the same folder in another console:")
            if raw_format_flag:
                print(
                    f"identify-push-listener-dialer-demo -d {default_addr} --raw-format"
                )
            else:
                print(f"identify-push-listener-dialer-demo -d {default_addr}")
            print("\nWaiting for incoming identify/push requests... (Ctrl+C to exit)")

            # Keep running until interrupted
            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                print("\n🛑 Shutting down listener...")
                logger.info("Listener interrupted by user")
                return
    except Exception as e:
        logger.error(f"Listener error: {e}")
        raise


async def run_dialer(
    port: int, destination: str, use_varint_format: bool = True
) -> None:
    """Run a host in dialer mode that connects to a listener."""
    format_name = "length-prefixed" if use_varint_format else "raw protobuf"
    print(
        f"\n==== Starting Identify-Push Dialer on port {port} "
        f"(using {format_name} format) ====\n"
    )

    # Create key pair for the dialer
    key_pair = create_new_key_pair()

    # Create the dialer host
    host = new_host(key_pair=key_pair)

    # Set up the identify and identify/push handlers with specified format
    host.set_stream_handler(
        ID_IDENTIFY, identify_handler_for(host, use_varint_format=use_varint_format)
    )
    host.set_stream_handler(
        ID_IDENTIFY_PUSH,
        identify_push_handler_for(host, use_varint_format=use_varint_format),
    )

    # Start listening on available interfaces
    from libp2p.utils.address_validation import get_available_interfaces

    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs):
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
            print("✅ Successfully connected to listener!")
            print(f"   Connected to: {peer_info.peer_id}")
            print(f"   Full address: {destination}")

            # Push identify information to the listener
            logger.info("Pushing identify information to listener...")
            print("\nPushing identify information to listener...")

            try:
                # Call push_identify_to_peer which returns a boolean
                success = await push_identify_to_peer(
                    host, peer_info.peer_id, use_varint_format=use_varint_format
                )

                if success:
                    logger.info("Identify push completed successfully!")
                    print("✅ Identify push completed successfully!")

                    logger.info("Example completed successfully!")
                    print("\nExample completed successfully!")
                else:
                    logger.warning("Identify push didn't complete successfully.")
                    print("\nWarning: Identify push didn't complete successfully.")

                    logger.warning("Example completed with warnings.")
                    print("Example completed with warnings.")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error during identify push: {error_msg}")
                print(f"\nError during identify push: {error_msg}")

                # Check for specific format mismatch errors
                if (
                    "Error parsing message" in error_msg
                    or "DecodeError" in error_msg
                    or "ParseFromString" in error_msg
                ):
                    print("\n" + "=" * 60)
                    print("FORMAT MISMATCH DETECTED!")
                    print("=" * 60)
                    if use_varint_format:
                        print(
                            "You are using length-prefixed format (default) but the "
                            "listener is using raw protobuf format."
                        )
                        print(
                            "\nTo fix this, run the dialer with the --raw-format flag:"
                        )
                        print(
                            f"identify-push-listener-dialer-demo --raw-format -d "
                            f"{destination}"
                        )
                    else:
                        print("You are using raw protobuf format but the listener")
                        print("is using length-prefixed format (default).")
                        print(
                            "\nTo fix this, run the dialer without the --raw-format "
                            "flag:"
                        )
                        print(f"identify-push-listener-dialer-demo -d {destination}")
                    print("=" * 60)

                logger.error("Example completed with errors.")
                print("Example completed with errors.")
                # Continue execution despite the push error

        except Exception as e:
            error_msg = str(e)
            if "unable to connect" in error_msg or "SwarmException" in error_msg:
                print(f"\n❌ Cannot connect to peer: {peer_info.peer_id}")
                print(f"   Address: {destination}")
                print(f"   Error: {error_msg}")
                print("\n💡 Make sure the peer is running and the address is correct.")
                return
            else:
                logger.error(f"Error during dialer operation: {error_msg}")
                print(f"\nError during dialer operation: {error_msg}")
                raise


def main() -> None:
    """Parse arguments and start the appropriate mode."""
    description = """
    This program demonstrates the libp2p identify/push protocol.
    Without arguments, it runs as a listener on random port.
    With -d parameter, it runs as a dialer on random port.

    Port 0 (default) means the OS will automatically assign an available port.
    This prevents port conflicts when running multiple instances.

    Use --raw-format to send raw protobuf messages (old format) instead of
    length-prefixed protobuf messages (new format, default).
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-p",
        "--port",
        default=0,
        type=int,
        help="source port number (0 = random available port)",
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="destination multiaddr string",
    )
    parser.add_argument(
        "--raw-format",
        action="store_true",
        help=(
            "use raw protobuf format (old format) instead of "
            "length-prefixed (new format)"
        ),
    )

    args = parser.parse_args()

    # Determine format: raw format if --raw-format is specified, otherwise
    # length-prefixed
    use_varint_format = not args.raw_format

    try:
        if args.destination:
            # Run in dialer mode with random available port if not specified
            trio.run(run_dialer, args.port, args.destination, use_varint_format)
        else:
            # Run in listener mode with random available port if not specified
            trio.run(run_listener, args.port, use_varint_format, args.raw_format)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        logger.info("Application interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        logger.error("Error: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
