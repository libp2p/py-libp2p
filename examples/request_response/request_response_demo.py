from __future__ import annotations

import argparse
import logging
import random
import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.request_response import JSONCodec, RequestResponse
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/example/request-response/1.0.0")


async def run(
    port: int,
    destination: str | None,
    message: str,
    seed: int | None = None,
) -> None:
    if port <= 0:
        port = find_free_port()
    listen_addr = get_available_interfaces(port)

    if seed is not None:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)

    host = new_host(key_pair=create_new_key_pair(secret))
    rr = RequestResponse(host)
    codec = JSONCodec()

    async def handler(request: dict[str, str], context) -> dict[str, str]:
        return {
            "message": request["message"],
            "echo": request["message"].upper(),
            "peer": str(context.peer_id),
        }

    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
        print(f"I am {host.get_id().to_string()}")

        if not destination:
            rr.set_handler(PROTOCOL_ID, handler=handler, codec=codec)
            peer_id = host.get_id().to_string()
            print("Listener ready, listening on:\n")
            for addr in listen_addr:
                print(f"{addr}/p2p/{peer_id}")

            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"
            print(
                "\nRun this from the same folder in another console:\n\n"
                f"request-response-demo -d {optimal_addr_with_peer} --message hello\n"
            )
            print("Waiting for incoming requests...")
            await trio.sleep_forever()

        destination_str = destination
        if destination_str is None:
            raise ValueError("destination is required in dialer mode")
        maddr = multiaddr.Multiaddr(destination_str)
        info = info_from_p2p_addr(maddr)
        await host.connect(info)
        response = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request={"message": message},
            codec=codec,
        )
        print(f"Sent: {message}")
        print(f"Received: {response}")


def main() -> None:
    description = """
    Demonstrates the request/response helper with a single JSON request and response.
    Run once without -d to start a listener, then run again with -d to send a request.
    """
    example_maddr = (
        "/ip4/[HOST_IP]/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    parser.add_argument(
        "--message",
        type=str,
        default="hello",
        help="JSON message payload to send",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="seed the RNG to make peer IDs reproducible",
    )
    args = parser.parse_args()
    try:
        trio.run(run, args.port, args.destination, args.message, args.seed)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
