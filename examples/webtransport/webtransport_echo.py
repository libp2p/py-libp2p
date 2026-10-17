#!/usr/bin/env python3
"""
WebTransport Echo Example

Demonstrates a simple echo protocol over libp2p WebTransport (HTTP/3 ALPN ``h3``
+ Noise XX on the first client-opened stream). Listen multiaddrs look like:

    /ip4/<host>/udp/<port>/quic-v1/webtransport/certhash/<mh>/.../p2p/<peer>

Unlike native ``quic-v1`` (ALPN ``libp2p``), on-wire traffic looks like ordinary
HTTP/3 — useful for DPI camouflage. Identity is still bound by Noise +
``webtransport_certhashes`` (TLS + Noise double encryption is required by the
spec).
"""

from __future__ import annotations

import argparse
import logging
import secrets

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr

# Verbose enough for DEMO.md annotations (ALPN / CONNECT / Noise paths live in
# the webtransport package).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("aioquic").setLevel(logging.INFO)
logging.getLogger("libp2p.transport.webtransport").setLevel(logging.DEBUG)
logging.getLogger("libp2p").setLevel(logging.INFO)

PROTOCOL_ID = TProtocol("/echo/1.0.0")
LISTEN_TEMPLATE = "/ip4/127.0.0.1/udp/{port}/quic-v1/webtransport"


async def _echo_stream_handler(stream: INetStream) -> None:
    try:
        msg = await stream.read()
        await stream.write(msg)
        await stream.close()
    except Exception as e:
        print(f"Echo handler error: {e}")
        try:
            await stream.close()
        except Exception:  # noqa: BLE001
            pass


def _key_pair(seed: int | None):
    if seed is not None:
        import random

        random.seed(seed)
        secret = random.getrandbits(32 * 8).to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)
    return create_new_key_pair(secret)


async def run_server(port: int, seed: int | None = None) -> None:
    from libp2p.utils.address_validation import find_free_port

    if port <= 0:
        port = find_free_port()

    host = new_host(
        enable_webtransport=True,
        enable_tcp=False,
        key_pair=_key_pair(seed),
    )
    listen_addrs = [Multiaddr(LISTEN_TEMPLATE.format(port=port))]

    async with host.run(listen_addrs=listen_addrs):
        print(f"I am {host.get_id().to_string()}")
        host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

        print("Listener ready, listening on:")
        for addr in host.get_addrs():
            print(f"{addr}")

        addrs = host.get_addrs()
        if addrs:
            print(
                "\nRun this from the same folder in another console:\n\n"
                f"python3 ./examples/webtransport/webtransport_echo.py "
                f"-d {addrs[0]}\n"
            )
        print(
            "Waiting for inbound WebTransport (ALPN h3, "
            "CONNECT /.well-known/libp2p-webtransport?type=noise)..."
        )
        await trio.sleep_forever()


async def run_client(destination: str, seed: int | None = None) -> None:
    host = new_host(
        enable_webtransport=True,
        enable_tcp=False,
        key_pair=_key_pair(seed),
    )

    async with host.run(listen_addrs=[]):
        print(f"I am {host.get_id().to_string()}")
        maddr = Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        print("STARTING CLIENT CONNECTION PROCESS")
        print(f"Dialing WebTransport multiaddr (expects /certhash/): {destination}")
        await host.connect(info)
        print("CLIENT CONNECTED TO SERVER")

        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
        msg = b"hi, there!\n"
        await stream.write(msg)
        response = await stream.read()

        print(f"Sent: {msg.decode('utf-8')}")
        print(f"Got: {response.decode('utf-8')}")
        await stream.close()
        await host.disconnect(info.peer_id)


async def run(port: int, destination: str, seed: int | None = None) -> None:
    if not destination:
        await run_server(port, seed)
    else:
        await run_client(destination, seed)


def main() -> None:
    description = """
    Echo demo over libp2p WebTransport (HTTP/3 ALPN h3 + Noise).

    First run:  python3 webtransport_echo.py -p <PORT>
    Then dial:  python3 webtransport_echo.py -d <LISTEN_MULTIADDR>
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="UDP port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="destination WebTransport multiaddr with /certhash/ and /p2p/",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="seed for deterministic key generation",
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.destination, args.seed)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
