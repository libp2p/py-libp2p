#!/usr/bin/env python3
"""
Python libp2p node for interop testing with rust-libp2p.
Transport: TCP with Noise encryption and Yamux multiplexing
Protocol: Ping (/ipfs/ping/1.0.0)

Usage:
  python pynode.py <RUST_NODE_MULTIADDR>

Example:
  python pynode.py /ip4/127.0.0.1/tcp/12345/p2p/12D3KooW...

"""

import logging
import sys

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.host.ping import PingService
from libp2p.peer.peerinfo import info_from_p2p_addr

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_ping_test(remote_addr: str, ping_count: int = 5):
    """Connect to rust node and test ping protocol."""
    # Create host with TCP transport
    host = new_host(key_pair=create_new_key_pair())

    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")

    try:
        async with host.run(listen_addrs=[listen_addr]):
            logger.info(f"Local Peer ID: {host.get_id()}")
            logger.info(f"Connecting to rust server: {remote_addr}")

            # Connect to rust server
            maddr = multiaddr.Multiaddr(remote_addr)
            peer_info = info_from_p2p_addr(maddr)
            await host.connect(peer_info)
            logger.info(f"Connected to: {peer_info.peer_id}")

            # Create ping service and send pings
            ping_service = PingService(host)
            logger.info(f"Sending {ping_count} ping(s)...")

            rtts = await ping_service.ping(peer_info.peer_id, ping_amt=ping_count)

            # Print results
            for i, rtt in enumerate(rtts, 1):
                rtt_ms = rtt / 1000
                print(f"Ping {i}: {rtt_ms:.2f} ms ({rtt} μs)")

            avg_rtt = sum(rtts) / len(rtts) / 1000
            print(f"\nAverage RTT: {avg_rtt:.2f} ms")
            logger.info("✅ Ping interop test passed!")

            return rtts

    finally:
        await host.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Error: Please provide the rust node multiaddr")
        sys.exit(1)

    remote_addr = sys.argv[1]
    ping_count = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    trio.run(run_ping_test, remote_addr, ping_count)


if __name__ == "__main__":
    main()
