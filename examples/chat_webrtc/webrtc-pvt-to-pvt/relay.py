#!/usr/bin/env python3
"""
WebRTC P2P — Step 1: Circuit Relay v2 Server
=============================================
Run this FIRST. It starts a public relay node and writes its multiaddr
to relay_addr.json so Alice and Bob can find it.

Usage:
    Terminal 1:  python relay.py [--port 9091]
    Terminal 2:  python peer_node.py --mode listen  (Alice)
    Terminal 3:  python peer_node.py --mode dial    (Bob)

Architecture:
    [Alice] ──TCP──> [Relay] <──TCP── [Bob]
        │                                 │
        └── SDP signaling via relay ──────┘
        └══════ direct UDP after ICE ═════╝

"""

import argparse
import json
import logging
from pathlib import Path

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID as HOP_PROTO,
    STOP_PROTOCOL_ID as STOP_PROTO,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.tools.async_service import background_trio_service

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("webrtc-relay")

ADDR_FILE = Path("relay_addr.json")

RELAY_LIMITS = RelayLimits(
    duration=3600,  # 1 hour per circuit
    data=100 * 1024 * 1024,  # 100 MB per circuit
    max_circuit_conns=32,
    max_reservations=16,
)


async def run_relay(port: int) -> None:
    print("\n" + "=" * 60)
    print("  WebRTC P2P — Relay Node")
    print("=" * 60)

    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    # CircuitV2Protocol with allow_hop=True
    relay_protocol = CircuitV2Protocol(host, limits=RELAY_LIMITS, allow_hop=True)

    relay_config = RelayConfig(
        roles=RelayRole.HOP | RelayRole.STOP | RelayRole.CLIENT,
        limits=RELAY_LIMITS,
    )

    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        peer_id = host.get_id()
        addrs = host.get_addrs()

        # Register hop and stop handlers so relay can accept reservations & circuits
        host.set_stream_handler(HOP_PROTO, relay_protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTO, relay_protocol._handle_stop_stream)

        async with background_trio_service(relay_protocol):
            # CircuitV2Transport wires up internal plumbing
            CircuitV2Transport(host, relay_protocol, relay_config)

            # Build the full address peers will use: /ip4/.../tcp/.../p2p/<relay-id>
            # Replace 0.0.0.0 with 127.0.0.1 for local demo
            #  (get_addrs already adds /p2p/)
            full_addr = str(addrs[0]).replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

            # Write to file so peers can read it
            ADDR_FILE.write_text(
                json.dumps(
                    {
                        "addr": full_addr,
                        "peer_id": peer_id.to_base58(),
                    }
                )
            )

            print(f"\n  🔀 Relay ID  : {peer_id}")
            print(f"  📡 Address   : {full_addr}")
            print(f"\n  💾 Saved → {ADDR_FILE}")
            print("\n  Now start Alice:")
            print("     python peer_node.py --mode listen")
            print("\n  Then Bob:")
            print("     python peer_node.py --mode dial")
            print("\n  Running... (Ctrl+C to stop)\n")
            print("-" * 60)

            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                pass
            finally:
                ADDR_FILE.unlink(missing_ok=True)
                print("\n  Relay stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="WebRTC P2P Relay Node")
    parser.add_argument(
        "--port", "-p", type=int, default=9091, help="TCP port (default: 9091)"
    )
    args = parser.parse_args()
    try:
        trio.run(run_relay, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
