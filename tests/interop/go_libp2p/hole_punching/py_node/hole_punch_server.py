#!/usr/bin/env python3
"""Python hole punching server for interop tests."""

import argparse
import json
import logging
import time

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.id import ID

# DCUtR may not be present; import defensively
try:
    from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol
except Exception:
    DCUtRProtocol = None

try:
    from libp2p.tools.async_service import background_trio_service
except Exception:
    background_trio_service = None

logger = logging.getLogger(__name__)

class HolePunchServer:
    def __init__(self, port=0):
        self.port = port
        self.host = None
        self.dcutr_protocol = None
        self.connections = []

    async def start(self, relay_addr=None, duration=120):
        """Start the hole punch server."""
        try:
            # Create py-libp2p host (new_host is synchronous)
            listen_addrs = []
            if self.port > 0:
                listen_addrs = [f"/ip4/0.0.0.0/tcp/{self.port}"]

            self.host = new_host(listen_addrs=listen_addrs)  # REMOVE await

            if DCUtRProtocol is None or background_trio_service is None:
                logger.warning("DCUtRProtocol or background_trio_service not available; server will accept relayed streams but cannot do DCUtR hole-punching.")
                # set up ping handler and run
                self.host.set_stream_handler("/test/ping/1.0.0", self._handle_ping_stream)
                logger.info(f"Python hole punch server running on: {self.host.get_addrs()}")
                logger.info(f"Python hole punch server peer ID: {self.host.get_id()}")
                if relay_addr:
                    await self._connect_to_relay(relay_addr)
                logger.info(f"Running server for {duration} seconds...")
                await trio.sleep(duration)
                logger.info("Hole punch server shutting down (DCUtR unavailable).")
                return

            # Enable DCUtR protocol for hole punching
            self.dcutr_protocol = DCUtRProtocol(self.host)

            async with background_trio_service(self.dcutr_protocol):
                await self.dcutr_protocol.event_started.wait()

                logger.info(f"Python hole punch server running on: {self.host.get_addrs()}")
                logger.info(f"Python hole punch server peer ID: {self.host.get_id()}")

                # Connect to relay if provided
                if relay_addr:
                    await self._connect_to_relay(relay_addr)

                # Set up test stream handler
                self.host.set_stream_handler("/test/ping/1.0.0", self._handle_ping_stream)

                # Run for specified duration
                logger.info(f"Running server for {duration} seconds...")
                await trio.sleep(duration)

            logger.info("Hole punch server shutting down...")

        except Exception:
            logger.exception("Unhandled exception in HolePunchServer.start")

    async def _connect_to_relay(self, relay_addr):
        """Connect to the relay server."""
        try:
            relay_multiaddr = Multiaddr(relay_addr)
            relay_str = str(relay_multiaddr)

            # Extract the peer ID after the last '/p2p/' if present
            if "/p2p/" in relay_str:
                try:
                    candidate = relay_str.rsplit("/p2p/", 1)[1]
                    # strip anything after next slash, if present
                    relay_peer_id_str = candidate.split("/")[0]
                    relay_peer_id = ID.from_base58(relay_peer_id_str)
                    relay_peer_info = PeerInfo(relay_peer_id, [relay_multiaddr])
                    await self.host.connect(relay_peer_info)
                    logger.info(f"Connected to relay: {relay_peer_id}")
                except Exception:
                    logger.exception("Failed to parse or connect to relay peer ID from multiaddr")
            else:
                logger.warning("Relay multiaddr does not contain '/p2p/<id>' segment; skipping connect.")
        except Exception:
            logger.exception("Failed in _connect_to_relay")

    async def _handle_ping_stream(self, stream):
        """Handle incoming ping streams."""
        try:
            # stream.muxed_conn may or may not have peer_id attribute
            peer_id = getattr(getattr(stream, "muxed_conn", None), "peer_id", None)
            logger.info(f"Received ping stream from: {peer_id}")

            response = {
                "status": "pong",
                "timestamp": int(time.time()),
                "peer_id": str(self.host.get_id())
            }

            data = json.dumps(response).encode("utf-8")
            await stream.write(data)

        except Exception:
            logger.exception("Error handling ping stream")
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def get_info(self):
        """Get server information."""
        if not self.host:
            return None

        try:
            return {
                "peer_id": str(self.host.get_id()),
                "addresses": [str(addr) for addr in self.host.get_addrs()],
                "status": "active",
                "connections": len(self.host.get_network().connections)
            }
        except Exception:
            logger.exception("Error while building get_info()")
            return None

async def main():
    """Main function for the hole punching server."""
    parser = argparse.ArgumentParser(description="Python Hole Punch Server")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on")
    parser.add_argument("--relay", help="Relay multiaddr to connect to")
    parser.add_argument("--duration", type=int, default=120, help="Server duration in seconds")
    parser.add_argument("--print-id-only", action="store_true", help="Print only peer ID and exit")
    parser.add_argument("--print-info", action="store_true", help="Print server info as JSON and exit")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    server = HolePunchServer(port=args.port)

    if args.print_id_only or args.print_info:
        # Start server briefly to get info
        try:
            listen_addrs = []
            if args.port > 0:
                listen_addrs = [f"/ip4/0.0.0.0/tcp/{args.port}"]
            server.host = new_host(listen_addrs=listen_addrs)  # REMOVE await

            if args.print_id_only:
                print(str(server.host.get_id()), end="")
                return

            if args.print_info:
                info = server.get_info()
                print(json.dumps(info), end="")
                return

        except Exception:
            logger.exception("Error getting server info")
            return
    else:
        try:
            await server.start(relay_addr=args.relay, duration=args.duration)
        except Exception:
            logger.exception("Error running hole punch server")

if __name__ == "__main__":
    trio.run(main)
