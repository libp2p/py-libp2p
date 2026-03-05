#!/usr/bin/env python3
"""
WebRTC-Direct Chat Server (Private-to-Public)
=============================================
A public server node that listens on webrtc-direct.
Clients (simulated "browsers") can dial it directly over UDP.

Usage:
    Terminal 1:  python private_peer.py
    Terminal 2:  python public_peer.py           # reads addr from file
                 python public_peer.py <maddr>   # or pass addr directly

Architecture:
    [Client]  ──UDP/DTLS/SCTP──>  [This Server]
               aiortc WebRTC-Direct (no relay needed)

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
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.transport.webrtc import (
    multiaddr_protocols,  # noqa: F401 – registers /webrtc-direct etc.
)
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
for _name in ("aioice", "aiortc", "libp2p.transport.webrtc"):
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger("webrtc-direct-server")

# ── Protocol & address file ───────────────────────────────────────────────────
CHAT_PROTOCOL = TProtocol("/webrtc-chat/1.0.0")
ADDR_FILE = Path("webrtc_direct_addr.json")
MAX_READ = 4096


# ── Chat handler ──────────────────────────────────────────────────────────────
async def chat_handler(stream) -> None:
    """Receive messages from a client and response back."""
    yamux = cast(YamuxStream, stream)
    remote = getattr(getattr(yamux, "muxed_conn", None), "peer_id", "?")
    print(f"\n  ✅ Client connected: {remote}")

    try:
        async with trio.open_nursery() as nursery:

            async def read_from_peer() -> None:
                try:
                    while True:
                        data = await yamux.read(MAX_READ)
                        if not data:
                            break
                        print(f"\n  \x1b[36m[{remote}]\x1b[0m {data.decode().rstrip()}")
                        print("  Server: ", end="", flush=True)
                except Exception as exc:
                    logger.debug("Read error: %s", exc)
                finally:
                    nursery.cancel_scope.cancel()

            async def write_to_peer() -> None:
                try:
                    async_stdin = trio.wrap_file(sys.stdin)
                    while True:
                        print("  Server: ", end="", flush=True)
                        line = await async_stdin.readline()
                        if not line or line.strip().lower() == "quit":
                            break
                        await yamux.write(line.strip().encode())
                except trio.Cancelled:
                    pass
                except Exception as exc:
                    logger.debug("Write error: %s", exc)
                finally:
                    nursery.cancel_scope.cancel()

            nursery.start_soon(read_from_peer)
            nursery.start_soon(write_to_peer)
    finally:
        print(f"\n  ❌ Client disconnected: {remote}")
        try:
            await yamux.close()
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────
async def run_server(udp_port: int) -> None:
    print("\n" + "=" * 60)
    print("  WebRTC-Direct Chat Server")
    print("=" * 60)

    # 1. Create a host (TCP is unused but new_host needs a listen addr)
    host = new_host(key_pair=create_new_key_pair())
    host.set_stream_handler(CHAT_PROTOCOL, chat_handler)

    swarm = host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)

        # 2. Create & start WebRTCDirectTransport
        transport = WebRTCDirectTransport()
        transport.set_host(host)

        async with trio.open_nursery() as nursery:
            await transport.start(nursery)

            # 3. Create listener on webrtc-direct
            listener = transport.create_listener(chat_handler)
            listen_maddr = Multiaddr(f"/ip4/0.0.0.0/udp/{udp_port}/webrtc-direct")
            ok = await listener.listen(listen_maddr, nursery)
            if not ok:
                print("  ❌ Listener failed to start")
                return

            addrs = listener.get_addrs()
            if not addrs:
                print("  ❌ No listening addresses available")
                return

            # Replace 0.0.0.0 with 127.0.0.1 for local demo
            server_addr = str(addrs[0]).replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

            # 4. Persist address so client can read it
            ADDR_FILE.write_text(json.dumps({"addr": server_addr}))

            print("\n  📡 Listening on:")
            print(f"     {server_addr}")
            print(f"\n  💾 Address saved → {ADDR_FILE}")
            print("\n  Run client in another terminal:")
            print("     python public_peer.py")
            print("  or:")
            print(f"     python public_peer.py {server_addr}")
            print("\n  Waiting for connections... (Ctrl+C to stop)\n")
            print("-" * 60)

            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                pass
            finally:
                ADDR_FILE.unlink(missing_ok=True)
                await listener.close()
                await transport.stop()
                print("\n  Server stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="WebRTC-Direct Chat Server")
    parser.add_argument(
        "--port", "-p", type=int, default=0, help="UDP port (default: 0 = random)"
    )
    args = parser.parse_args()
    try:
        trio.run(run_server, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
