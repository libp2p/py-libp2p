import argparse
import base64
import logging

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.identity.identify.identify import ID as IDENTIFY_PROTOCOL_ID
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
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


async def run(port: int, destination: str) -> None:
    localhost_ip = "0.0.0.0"

    if not destination:
        # Create first host (listener)
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}")
        host_a = new_host()

        async with host_a.run(listen_addrs=[listen_addr]):
            print(
                "First host listening. Run this from another console:\n\n"
                f"identify-demo "
                f"-d {host_a.get_addrs()[0]}\n"
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
                response = await stream.read()
                await stream.close()
                identify_msg = Identify()
                identify_msg.ParseFromString(response)
                print_identify_response(identify_msg)
            except Exception as e:
                print(f"Identify protocol error: {e}")

            return


def main() -> None:
    description = """
    This program demonstrates the libp2p identify protocol.
    First run identify-demo -p <PORT>' to start a listener.
    Then run 'identify-demo <ANOTHER_PORT> -d <DESTINATION>'
    where <DESTINATION> is the multiaddress shown by the listener.
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
    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
