#!/usr/bin/env python3
"""
WebRTC-Direct Chat Client (Private-to-Public)
=============================================
Connects to the private_peer.py server over UDP WebRTC-Direct.
No relay needed — dials a known server address directly.

Usage:
    python public_peer.py                          # reads addr from file
    python public_peer.py /ip4/127.0.0.1/udp/...  # explicit addr

"""

import json
import logging
from pathlib import Path
import sys

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
for _name in ("aioice", "aiortc", "libp2p.transport.webrtc"):
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger("webrtc-direct-client")

CHAT_PROTOCOL = TProtocol("/webrtc-chat/1.0.0")
ADDR_FILE = Path("webrtc_direct_addr.json")
MAX_READ = 4096

CONNECTION_TIMEOUT = 60.0  # seconds for ICE + DTLS


# ── Receive loop ──────────────────────────────────────────────────────────────
async def receive_loop(stream) -> None:
    """Print messages received from server."""
    try:
        while True:
            data = await stream.read(MAX_READ)
            if not data:
                break
            msg = data.decode("utf-8", errors="replace").rstrip()
            print(f"\n  \x1b[32m[server]\x1b[0m {msg}")
            print("  You: ", end="", flush=True)
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────
async def run_client(server_addr_str: str) -> None:
    print("\n" + "=" * 60)
    print("  WebRTC-Direct Chat Client")
    print("=" * 60)
    print(f"\n  🔌 Dialing: {server_addr_str}")

    server_maddr = Multiaddr(server_addr_str)

    # Extract server peer ID from the /p2p/... component if present
    try:
        info = info_from_p2p_addr(server_maddr)
        server_peer_id = info.peer_id
    except Exception:
        server_peer_id = None

    # 1. Create host (TCP used only to satisfy new_host; WebRTC-Direct is over UDP)
    host = new_host(key_pair=create_new_key_pair())

    swarm = host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)

        # 2. Start WebRTCDirectTransport
        transport = WebRTCDirectTransport()
        transport.set_host(host)

        async with trio.open_nursery() as nursery:
            await transport.start(nursery)

            # 3. Dial the server — ICE + DTLS handshake happens here
            print("  ⏳ Establishing WebRTC connection (ICE + DTLS)...")
            with trio.move_on_after(CONNECTION_TIMEOUT) as scope:
                connection = await transport.dial(server_maddr)

            if scope.cancelled_caught:
                print(f"  ❌ Connection timed out after {CONNECTION_TIMEOUT}s")
                await transport.stop()
                return

            if connection is None:
                print("  ❌ Failed to establish connection")
                await transport.stop()
                return

            print("  ✅ WebRTC-Direct connection established!\n")

            # 4. Open a stream on our chat protocol
            if server_peer_id is None:
                print("  ❌ Cannot open stream: server peer ID unknown")
                await connection.close()
                await transport.stop()
                return

            stream = await host.new_stream(server_peer_id, [CHAT_PROTOCOL])

            print("  💬 Chat ready. Type messages and press Enter.")
            print("     Type 'quit' to exit.\n")
            print("-" * 60)

            # 5. Concurrent read + write
            async with trio.open_nursery() as chat_nursery:
                chat_nursery.start_soon(receive_loop, stream)

                # Write loop runs in a thread so input() doesn't block trio
                async def write_loop() -> None:
                    async_stdin = trio.wrap_file(sys.stdin)
                    while True:
                        print("  You: ", end="", flush=True)
                        line = await async_stdin.readline()
                        if not line or line.strip().lower() == "quit":
                            chat_nursery.cancel_scope.cancel()
                            break
                        await stream.write(line.strip().encode())

                chat_nursery.start_soon(write_loop)

            await stream.close()
            await connection.close()
            await transport.stop()
            print("\n  👋 Disconnected.")


def main() -> None:
    # Resolve server address: CLI arg > address file > error
    if len(sys.argv) > 1:
        server_addr_str = sys.argv[1]
    elif ADDR_FILE.exists():
        data = json.loads(ADDR_FILE.read_text())
        server_addr_str = data["addr"]
        print(f"  📂 Loaded address from {ADDR_FILE}: {server_addr_str}")
    else:
        print(f"  ❌ No server address provided and {ADDR_FILE} not found.")
        print("     Start private_peer.py first, or pass the address:")
        print("     python public_peer.py <multiaddr>")
        sys.exit(1)

    try:
        trio.run(run_client, server_addr_str)
    except KeyboardInterrupt:
        print("\n  👋 Interrupted.")


if __name__ == "__main__":
    main()
