import argparse
import base64
import logging
import sys

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.identity.identify.identify import (
    ID as IDENTIFY_PROTOCOL_ID,
    identify_handler_for,
    parse_identify_response,
)
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.peer.envelope import debug_dump_envelope, unmarshal_envelope
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

logger = logging.getLogger("libp2p.identity.identify-example")


def decode_multiaddrs(raw_addrs):
    """Convert raw listen addresses into human-readable multiaddresses."""
    decoded_addrs = []
    for addr in raw_addrs:
        try:
            decoded_addrs.append(str(multiaddr.Multiaddr(addr)))
        except Exception as e:
            decoded_addrs.append(f"Invalid Multiaddr ({addr}): {e}")
    return decoded_addrs


def print_identify_response(identify_response: Identify):
    """Pretty-print Identify response."""
    public_key_b64 = base64.b64encode(identify_response.public_key).decode("utf-8")
    listen_addrs = decode_multiaddrs(identify_response.listen_addrs)
    signed_peer_record = unmarshal_envelope(identify_response.signedPeerRecord)
    try:
        observed_addr_decoded = decode_multiaddrs([identify_response.observed_addr])
    except Exception:
        observed_addr_decoded = identify_response.observed_addr
    print(
        f"Identify response:\n"
        f"  Public Key (Base64): {public_key_b64}\n"
        f"  Listen Addresses: {listen_addrs}\n"
        f"  Protocols: {list(identify_response.protocols)}\n"
        f"  Observed Address: "
        f"{observed_addr_decoded if identify_response.observed_addr else 'None'}\n"
        f"  Protocol Version: {identify_response.protocol_version}\n"
        f"  Agent Version: {identify_response.agent_version}"
    )

    debug_dump_envelope(signed_peer_record)


async def run(port: int, destination: str, use_varint_format: bool = True) -> None:
    from libp2p.utils.address_validation import (
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if not destination:
        # Create first host (listener)
        if port <= 0:
            from libp2p.utils.address_validation import find_free_port

            port = find_free_port()

        listen_addrs = get_available_interfaces(port)
        host_a = new_host()

        # Set up identify handler with specified format
        # Set use_varint_format = False, if want to checkout the Signed-PeerRecord
        identify_handler = identify_handler_for(
            host_a, use_varint_format=use_varint_format
        )
        host_a.set_stream_handler(IDENTIFY_PROTOCOL_ID, identify_handler)

        async with (
            host_a.run(listen_addrs=listen_addrs),
            trio.open_nursery() as nursery,
        ):
            # Start the peer-store cleanup task
            nursery.start_soon(host_a.get_peerstore().start_cleanup_task, 60)

            # Get all available addresses with peer ID
            all_addrs = host_a.get_addrs()

            if use_varint_format:
                format_name = "length-prefixed"
                print(f"First host listening (using {format_name} format).")
                print("Listener ready, listening on:\n")
                for addr in all_addrs:
                    print(f"{addr}")

                # Use optimal address for the client command
                optimal_addr = get_optimal_binding_address(port)
                optimal_addr_with_peer = (
                    f"{optimal_addr}/p2p/{host_a.get_id().to_string()}"
                )
                print(
                    f"\nRun this from the same folder in another console:\n\n"
                    f"identify-demo -d {optimal_addr_with_peer}\n"
                )
                print("Waiting for incoming identify request...")
            else:
                format_name = "raw protobuf"
                print(f"First host listening (using {format_name} format).")
                print("Listener ready, listening on:\n")
                for addr in all_addrs:
                    print(f"{addr}")

                # Use optimal address for the client command
                optimal_addr = get_optimal_binding_address(port)
                optimal_addr_with_peer = (
                    f"{optimal_addr}/p2p/{host_a.get_id().to_string()}"
                )
                print(
                    f"\nRun this from the same folder in another console:\n\n"
                    f"identify-demo -d {optimal_addr_with_peer}\n"
                )
                print("Waiting for incoming identify request...")

            # Add a custom handler to show connection events
            async def custom_identify_handler(stream):
                peer_id = stream.muxed_conn.peer_id
                print(f"\n🔗 Received identify request from peer: {peer_id}")

                # Show remote address in multiaddr format
                try:
                    from libp2p.identity.identify.identify import (
                        _remote_address_to_multiaddr,
                    )

                    remote_address = stream.get_remote_address()
                    if remote_address:
                        observed_multiaddr = _remote_address_to_multiaddr(
                            remote_address
                        )
                        # Add the peer ID to create a complete multiaddr
                        complete_multiaddr = f"{observed_multiaddr}/p2p/{peer_id}"
                        print(f"   Remote address: {complete_multiaddr}")
                    else:
                        print(f"   Remote address: {remote_address}")
                except Exception:
                    print(f"   Remote address: {stream.get_remote_address()}")

                # Call the original handler
                await identify_handler(stream)

                print(f"✅ Successfully processed identify request from {peer_id}")

            # Replace the handler with our custom one
            host_a.set_stream_handler(IDENTIFY_PROTOCOL_ID, custom_identify_handler)

            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                print("\n🛑 Shutting down listener...")
                logger.info("Listener interrupted by user")
                return

    else:
        # Create second host (dialer)
        from libp2p.utils.address_validation import (
            find_free_port,
            get_available_interfaces,
            get_optimal_binding_address,
        )

        if port <= 0:
            port = find_free_port()

        listen_addrs = get_available_interfaces(port)
        host_b = new_host()

        async with (
            host_b.run(listen_addrs=listen_addrs),
            trio.open_nursery() as nursery,
        ):
            # Start the peer-store cleanup task
            nursery.start_soon(host_b.get_peerstore().start_cleanup_task, 60)

            # Connect to the first host
            print(f"dialer (host_b) listening on {host_b.get_addrs()[0]}")
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            print(f"Second host connecting to peer: {info.peer_id}")

            try:
                await host_b.connect(info)
            except Exception as e:
                error_msg = str(e)
                if "unable to connect" in error_msg or "SwarmException" in error_msg:
                    print(f"\n❌ Cannot connect to peer: {info.peer_id}")
                    print(f"   Address: {destination}")
                    print(f"   Error: {error_msg}")
                    print(
                        "\n💡 Make sure the peer is running and the address is correct."
                    )
                    return
                else:
                    # Re-raise other exceptions
                    raise

            stream = await host_b.new_stream(info.peer_id, (IDENTIFY_PROTOCOL_ID,))

            try:
                print("Starting identify protocol...")

                # Read the response using the utility function
                from libp2p.utils.varint import read_length_prefixed_protobuf

                response = await read_length_prefixed_protobuf(
                    stream, use_varint_format
                )
                full_response = response

                await stream.close()

                # Parse the response using the robust protocol-level function
                # This handles both old and new formats automatically
                identify_msg = parse_identify_response(full_response)
                print_identify_response(identify_msg)

            except Exception as e:
                error_msg = str(e)
                print(f"Identify protocol error: {error_msg}")

                # Check for specific format mismatch errors
                if "Error parsing message" in error_msg or "DecodeError" in error_msg:
                    print("\n" + "=" * 60)
                    print("FORMAT MISMATCH DETECTED!")
                    print("=" * 60)
                    if use_varint_format:
                        print(
                            "You are using length-prefixed format (default) but the "
                            "listener"
                        )
                        print("is using raw protobuf format.")
                        print(
                            "\nTo fix this, run the dialer with the --raw-format flag:"
                        )
                        print(f"identify-demo --raw-format -d {destination}")
                    else:
                        print("You are using raw protobuf format but the listener")
                        print("is using length-prefixed format (default).")
                        print(
                            "\nTo fix this, run the dialer without the --raw-format "
                            "flag:"
                        )
                        print(f"identify-demo -d {destination}")
                    print("=" * 60)
                else:
                    import traceback

                    traceback.print_exc()

            return


def main() -> None:
    description = """
    This program demonstrates the libp2p identify protocol.
    First run 'identify-demo -p <PORT> [--raw-format]' to start a listener.
    Then run 'identify-demo <ANOTHER_PORT> -d <DESTINATION>'
    where <DESTINATION> is the multiaddress shown by the listener.

    Use --raw-format to send raw protobuf messages (old format) instead of
    length-prefixed protobuf messages (new format, default).
    """

    example_maddr = (
        "/ip4/[HOST_IP]/tcp/8888/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
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

    # Determine format: use varint (length-prefixed) if --raw-format is specified,
    # otherwise use raw protobuf format (old format)
    use_varint_format = not args.raw_format

    try:
        if args.destination:
            # Run in dialer mode
            trio.run(run, *(args.port, args.destination, use_varint_format))
        else:
            # Run in listener mode
            trio.run(run, *(args.port, args.destination, use_varint_format))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        logger.info("Application interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        logger.error("Error: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
