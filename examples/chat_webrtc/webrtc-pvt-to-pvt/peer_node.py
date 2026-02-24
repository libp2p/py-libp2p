#!/usr/bin/env python3
"""
WebRTC P2P — Step 2 & 3: Peer Node (Alice or Bob)
==================================================
Run relay.py first, then:
    Terminal 2:  python peer_node.py --mode listen  ← Alice
    Terminal 3:  python peer_node.py --mode dial    ← Bob

How it works:
  Alice (listen):
    1. Reads relay_addr.json, connects to relay via TCP
    2. Starts WebRTCTransport (registers /webrtc-signaling handler + circuit relay)
    3. Calls ensure_listener_ready() → relay reserves a slot for Alice
    4. Gets WebRTC circuit address:
    /ip4/.../tcp/.../p2p/relay/p2p-circuit/webrtc/p2p/<alice_peer_id>
    5. Writes it to alice_webrtc_addr.json, then waits for Bob

  Bob (dial):
    1. Reads relay_addr.json + alice_webrtc_addr.json
    2. Starts WebRTCTransport, connects to relay
    3. Calls transport.dial(alice_webrtc_addr):
         - Opens relay circuit to Alice
         - Exchanges SDP offer/answer over relay stream
         - ICE negotiation → DTLS handshake → direct UDP (if NAT allows)
    4. Opens chat stream on the now-connected WebRTC connection

"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import cast

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID as HOP_PROTO,
    STOP_PROTOCOL_ID as STOP_PROTO,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service import background_trio_service
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport

RELAY_HOP_PROTOCOL = str(HOP_PROTO)
RELAY_STOP_PROTOCOL = str(STOP_PROTO)


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
for _n in ("aioice", "aiortc"):
    logging.getLogger(_n).setLevel(logging.WARNING)
logger = logging.getLogger("webrtc-p2p-peer")

# ── Constants ─────────────────────────────────────────────────────────────────
CHAT_PROTOCOL = TProtocol("/webrtc-p2p-chat/1.0.0")
RELAY_ADDR_FILE = Path("relay_addr.json")
ALICE_ADDR_FILE = Path("alice_webrtc_addr.json")
MAX_READ = 4096

RELAY_LIMITS = RelayLimits(
    duration=3600,
    data=10 * 1024 * 1024,
    max_circuit_conns=8,
    max_reservations=4,
)

CONNECT_TIMEOUT = 90.0  # ICE + DTLS can take time
ALICE_ADDR_POLL = 0.5  # seconds between polling for alice_webrtc_addr.json


# ── Chat handlers ─────────────────────────────────────────────────────────────
async def alice_chat_handler(stream) -> None:
    """Bidirectional chat — Alice can both receive from and send to Bob."""
    yamux = cast(YamuxStream, stream)
    remote = getattr(getattr(yamux, "muxed_conn", None), "peer_id", "Bob")
    print(f"\n  ✅ Bob connected: {remote}")
    print("  💬 Chat ready. Type messages and press Enter.")
    print("     Type 'quit' to exit.\n")
    print("-" * 60)

    async def read_from_bob() -> None:
        try:
            while True:
                data = await yamux.read(MAX_READ)
                if not data:
                    break
                msg = data.decode("utf-8", errors="replace").rstrip()
                print(f"\n  \x1b[36m[Bob]\x1b[0m {msg}")
                print("  Alice: ", end="", flush=True)
        except Exception as exc:
            logger.debug("Alice read error: %s", exc)

    async def write_to_bob() -> None:
        async_stdin = trio.wrap_file(sys.stdin)
        while True:
            print("  Alice: ", end="", flush=True)
            line = await async_stdin.readline()
            if not line or line.strip().lower() == "quit":
                break
            try:
                await yamux.write(line.strip().encode())
            except Exception as exc:
                logger.debug("Alice write error: %s", exc)
                break

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_from_bob)
        nursery.start_soon(write_to_bob)

    try:
        await yamux.close()
    except Exception:
        pass
    print("\n  Alice disconnected.")


# ── Shared: connect a host to the relay ──────────────────────────────────────
async def connect_to_relay(host, relay_addr_str: str) -> None:
    """
    Connect host to relay via TCP.
    relay_addr_str is the full multiaddr: /ip4/.../tcp/.../p2p/relay-id
    Source: relay_example.py :: setup_destination_node() connect block
    """
    relay_maddr = Multiaddr(relay_addr_str)
    relay_info = info_from_p2p_addr(relay_maddr)

    peerstore = host.get_peerstore()
    base = relay_info.addrs[0] if relay_info.addrs else None
    if base:
        try:
            peerstore.add_addrs(relay_info.peer_id, [base], 3600)
        except Exception:
            pass

    await host.connect(relay_info)

    try:
        peerstore.add_protocols(
            relay_info.peer_id,
            [RELAY_HOP_PROTOCOL, RELAY_STOP_PROTOCOL],
        )
    except Exception:
        pass
    print(f"  ✅ Connected to relay: {relay_info.peer_id}")


# ── Alice (listener) ──────────────────────────────────────────────────────────
async def run_alice(relay_addr_str: str) -> None:
    print("\n" + "=" * 60)
    print("  WebRTC P2P — Alice (Listener)")
    print("=" * 60)

    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)
    peer_id = host.get_id()
    print(f"\n  🆔 Alice ID: {peer_id}")

    # Register application chat handler BEFORE starting transport
    host.set_stream_handler(CHAT_PROTOCOL, alice_chat_handler)

    swarm = host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)

        # CircuitV2Protocol with allow_hop=False (Alice is a client, not a relay)
        # WebRTCTransport._setup_circuit_relay_support() creates its own internally,
        # but we register the stop handler so Alice can accept circuit connections.
        circuit_protocol = CircuitV2Protocol(host, limits=RELAY_LIMITS, allow_hop=False)
        host.set_stream_handler(HOP_PROTO, circuit_protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTO, circuit_protocol._handle_stop_stream)

        async with background_trio_service(circuit_protocol):
            # 1. Connect to relay
            print("\n  🔗 Connecting to relay...")
            await connect_to_relay(host, relay_addr_str)
            await trio.sleep(0.5)

            # 2. Start WebRTCTransport — this:
            #    - Spawns the asyncio bridge for aiortc
            #    - Registers /webrtc-signaling handler on the host
            #    - Sets up internal CircuitRelaySupport (discovery, reservations)
            transport = WebRTCTransport({})
            transport.set_host(host)
            await transport.start()
            print("  ✅ WebRTC transport started")

            # 3. Ensure relay reservation — Alice advertises her circuit/webrtc address
            print("  ⏳ Making relay reservation...")
            await transport.ensure_listener_ready()

            webrtc_addrs = transport.get_listener_addresses()
            if not webrtc_addrs:
                print("  ❌ No WebRTC listener addresses. Is the relay running?")
                await transport.stop()
                return

            # 4. Pick the first circuit/webrtc addr and share it with Bob
            # Format: /ip4/.../tcp/.../p2p/relay/p2p-circuit/webrtc/p2p/alice
            alice_webrtc_addr = str(webrtc_addrs[0])
            ALICE_ADDR_FILE.write_text(
                json.dumps(
                    {
                        "addr": alice_webrtc_addr,
                        "peer_id": peer_id.to_base58(),
                    }
                )
            )

            print("\n  📡 Alice WebRTC address:")
            print(f"     {alice_webrtc_addr}")
            print(f"\n  💾 Saved → {ALICE_ADDR_FILE}")
            print("\n  Now start Bob in another terminal:")
            print("     python peer_node.py --mode dial")
            print("\n  Waiting for Bob... (Ctrl+C to stop)\n")
            print("-" * 60)

            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                pass
            finally:
                ALICE_ADDR_FILE.unlink(missing_ok=True)
                await transport.stop()
                print("\n  Alice stopped.")


# ── Bob (dialer) ──────────────────────────────────────────────────────────────
async def run_bob(relay_addr_str: str) -> None:
    print("\n" + "=" * 60)
    print("  WebRTC P2P — Bob (Dialer)")
    print("=" * 60)

    # Wait for Alice to write her address
    print(f"\n  ⏳ Waiting for Alice ({ALICE_ADDR_FILE})...")
    deadline = trio.current_time() + 60.0
    while not ALICE_ADDR_FILE.exists():
        if trio.current_time() > deadline:
            print("  ❌ Timed out waiting for alice_webrtc_addr.json")
            print("     Start Alice first: python peer_node.py --mode listen")
            return
        await trio.sleep(ALICE_ADDR_POLL)

    alice_data = json.loads(ALICE_ADDR_FILE.read_text())
    alice_webrtc_addr_str = alice_data["addr"]
    alice_peer_id_str = alice_data["peer_id"]
    print(f"  📂 Alice address: {alice_webrtc_addr_str}")

    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)
    peer_id = host.get_id()
    print(f"\n  🆔 Bob ID: {peer_id}")

    swarm = host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)

        circuit_protocol = CircuitV2Protocol(host, limits=RELAY_LIMITS, allow_hop=False)
        host.set_stream_handler(HOP_PROTO, circuit_protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTO, circuit_protocol._handle_stop_stream)

        async with background_trio_service(circuit_protocol):
            # 1. Connect to relay
            print("\n  🔗 Connecting to relay...")
            await connect_to_relay(host, relay_addr_str)
            await trio.sleep(0.5)

            # 2. Start WebRTC transport
            transport = WebRTCTransport({})
            transport.set_host(host)
            await transport.start()
            print("  ✅ WebRTC transport started")
            await trio.sleep(0.5)

            # 3. Dial Alice's WebRTC circuit address
            #    This triggers: circuit open → SDP exchange → ICE → DTLS
            alice_maddr = Multiaddr(alice_webrtc_addr_str)
            print("\n  📞 Dialing Alice...")
            print("     (ICE negotiation + DTLS handshake — may take ~10s)")

            with trio.move_on_after(CONNECT_TIMEOUT) as scope:
                connection = await transport.dial(alice_maddr)

            if scope.cancelled_caught:
                print(f"  ❌ Connection timed out after {CONNECT_TIMEOUT}s")
                await transport.stop()
                return

            if connection is None:
                print("  ❌ Failed to establish WebRTC connection")
                await transport.stop()
                return

            print("  ✅ WebRTC P2P connection established!\n")

            # 4. Open chat stream to Alice
            from libp2p.peer.id import ID

            alice_id = ID.from_base58(alice_peer_id_str)

            stream = await host.new_stream(alice_id, [CHAT_PROTOCOL])
            print("  💬 Chat open. Type messages and press Enter.")
            print("     Type 'quit' to exit.\n")
            print("-" * 60)

            # Receive loop
            async def recv() -> None:
                try:
                    while True:
                        data = await stream.read(MAX_READ)
                        if not data:
                            break
                        print(
                            f"\n  \x1b[32m[Alice]\x1b[0m "
                            f"{data.decode('utf-8', errors='replace').rstrip()}"
                        )
                        print("  Bob: ", end="", flush=True)
                except Exception:
                    pass

            async with trio.open_nursery() as nursery:
                nursery.start_soon(recv)

                async_stdin = trio.wrap_file(sys.stdin)
                while True:
                    print("  Bob: ", end="", flush=True)
                    line = await async_stdin.readline()
                    if not line or line.strip().lower() == "quit":
                        nursery.cancel_scope.cancel()
                        break
                    await stream.write(line.strip().encode())

            await stream.close()
            await connection.close()
            await transport.stop()
            print("\n  👋 Bob disconnected.")


# ── Entry point ───────────────────────────────────────────────────────────────
async def main_async(mode: str) -> None:
    # Load relay address
    if not RELAY_ADDR_FILE.exists():
        print(f"  ❌ {RELAY_ADDR_FILE} not found.")
        print("     Start the relay first: python relay.py")
        return

    relay_data = json.loads(RELAY_ADDR_FILE.read_text())
    relay_addr_str = relay_data["addr"]
    print(f"  📂 Relay: {relay_addr_str}")

    if mode == "listen":
        await run_alice(relay_addr_str)
    else:
        await run_bob(relay_addr_str)


def main() -> None:
    parser = argparse.ArgumentParser(description="WebRTC P2P Peer (Alice or Bob)")
    parser.add_argument(
        "--mode",
        "-m",
        choices=["listen", "dial"],
        required=True,
        help="'listen' = Alice (starts first), 'dial' = Bob (dials Alice)",
    )
    args = parser.parse_args()
    try:
        trio.run(main_async, args.mode)
    except KeyboardInterrupt:
        print("\n  👋 Interrupted.")


if __name__ == "__main__":
    main()
