import argparse
import base64
import logging

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
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

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


def print_identify_response(identify_response):
    """Pretty-print Identify response."""
    public_key_b64 = base64.b64encode(identify_response.public_key).decode("utf-8")
    listen_addrs = decode_multiaddrs(identify_response.listen_addrs)
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


async def run(port: int, destination: str, use_varint_format: bool = True) -> None:
    localhost_ip = "0.0.0.0"

    if not destination:
        # Create first host (listener)
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}")
        host_a = new_host()

        # Set up identify handler with specified format
        identify_handler = identify_handler_for(
            host_a, use_varint_format=use_varint_format
        )
        host_a.set_stream_handler(IDENTIFY_PROTOCOL_ID, identify_handler)

        async with host_a.run(listen_addrs=[listen_addr]):
            # Get the actual address and replace 0.0.0.0 with 127.0.0.1 for client
            # connections
            server_addr = str(host_a.get_addrs()[0])
            client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

            format_name = "length-prefixed" if use_varint_format else "raw protobuf"
            print(
                f"First host listening (using {format_name} format). "
                f"Run this from another console:\n\n"
                f"identify-demo "
                f"-d {client_addr}\n"
            )
            print("Waiting for incoming identify request...")
            await trio.sleep_forever()

    else:
        # Create second host (dialer)
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}")
        host_b = new_host()

        async with host_b.run(listen_addrs=[listen_addr]):
            # Connect to the first host
            print(f"dialer (host_b) listening on {host_b.get_addrs()[0]}")
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            print(f"Second host connecting to peer: {info.peer_id}")

            await host_b.connect(info)
            stream = await host_b.new_stream(info.peer_id, (IDENTIFY_PROTOCOL_ID,))

            try:
                print("Starting identify protocol...")

                # Read the complete response (could be either format)
                # Read a larger chunk to get all the data before stream closes
                response = await stream.read(8192)  # Read enough data in one go

                await stream.close()

                # Parse the response using the robust protocol-level function
                # This handles both old and new formats automatically
                identify_msg = parse_identify_response(response)
                print_identify_response(identify_msg)

            except Exception as e:
                print(f"Identify protocol error: {e}")

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
        "/ip4/127.0.0.1/tcp/8888/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
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

    # Determine format: raw format if --raw-format is specified, otherwise
    # length-prefixed
    use_varint_format = not args.raw_format

    try:
        trio.run(run, *(args.port, args.destination, use_varint_format))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
