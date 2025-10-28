#!/usr/bin/env python3
"""Python relay server for hole punching interop tests."""

import argparse
import json
import logging
import signal
import sys
import time
import traceback

import trio
from libp2p import new_host
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol, DEFAULT_RELAY_LIMITS
from libp2p.tools.async_service import background_trio_service

logger = logging.getLogger(__name__)

class RelayServer:
    def __init__(self, port=8000):
        self.port = port
        self.host = None
        self.relay_protocol = None
        self.stop_event = trio.Event()

    async def start(self):
        """Start the relay server."""
        # Create py-libp2p host (new_host used synchronously in many py-libp2p examples)
        try:
            self.host = new_host(listen_addrs=[f"/ip4/0.0.0.0/tcp/{self.port}"])
        except Exception:
            logger.exception("Failed to create host with new_host()")
            raise

        # Build relay limits defensively (DEFAULT_RELAY_LIMITS might not be a dict)
        limits = None
        try:
            if isinstance(DEFAULT_RELAY_LIMITS, dict):
                limits = DEFAULT_RELAY_LIMITS.copy()
            else:
                # try to extract non-callable public attributes into a dict
                limits = {}
                for name in dir(DEFAULT_RELAY_LIMITS):
                    if name.startswith("_"):
                        continue
                    try:
                        val = getattr(DEFAULT_RELAY_LIMITS, name)
                    except Exception:
                        continue
                    if callable(val):
                        continue
                    limits[name] = val
        except Exception:
            logger.warning("Could not convert DEFAULT_RELAY_LIMITS into mapping; will fall back to passing it directly.")
            limits = None

        # Override the fields we want (safe even if limits is a dict)
        if isinstance(limits, dict):
            limits["max_reservations"] = 1024
            limits["max_circuits"] = 1024

        # Instantiate CircuitV2Protocol with best-effort limits object
        try:
            if limits is not None:
                self.relay_protocol = CircuitV2Protocol(self.host, limits, allow_hop=True)
            else:
                # fallback: pass DEFAULT_RELAY_LIMITS object directly
                self.relay_protocol = CircuitV2Protocol(self.host, DEFAULT_RELAY_LIMITS, allow_hop=True)
        except Exception:
            logger.exception("Failed to create CircuitV2Protocol with provided limits. Traceback:")
            # If it fails, re-raise so caller can exit/see the error
            raise

        # Start the relay service
        async with background_trio_service(self.relay_protocol):
            await self.relay_protocol.event_started.wait()

            logger.info(f"Python relay server running on: {self.host.get_addrs()}")
            logger.info(f"Python relay server peer ID: {self.host.get_id()}")

            # Set up monitoring stream handler
            self.host.set_stream_handler("/relay/monitor/1.0.0", self._handle_monitor_stream)

            # Wait for termination signal
            await self.stop_event.wait()

    async def _handle_monitor_stream(self, stream):
        """Handle monitor stream requests."""
        try:
            status = {
                "status": "active",
                "timestamp": int(time.time()),
                "connections": len(self.host.get_network().connections),
                "peer_id": str(self.host.get_id())
            }

            data = json.dumps(status).encode("utf-8")
            await stream.write(data)

        except Exception:
            logger.exception("Error in monitor stream")
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def stop(self):
        """Stop the relay server."""
        self.stop_event.set()

    def get_info(self):
        """Get server information."""
        if not self.host:
            return None

        return {
            "peer_id": str(self.host.get_id()),
            "addresses": [str(addr) for addr in self.host.get_addrs()],
            "status": "active",
        }

async def main():
    """Main function to run the relay server."""
    parser = argparse.ArgumentParser(description="Python Relay Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--print-id-only", action="store_true", help="Print only peer ID and exit")
    parser.add_argument("--print-info", action="store_true", help="Print server info as JSON and exit")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    server = RelayServer(port=args.port)

    if args.print_id_only or args.print_info:
        # Start server briefly to get info
        try:
            server.host = new_host(listen_addrs=[f"/ip4/0.0.0.0/tcp/{args.port}"])

            if args.print_id_only:
                print(str(server.host.get_id()), end="")
                return

            if args.print_info:
                info = server.get_info()
                print(json.dumps(info), end="")
                return

        except Exception:
            logger.exception("Error getting server info")
            sys.exit(1)
    else:
        # Set up signal handler
        def signal_handler(signum, frame=None):
            logger.info(f"Received signal {signum}, shutting down...")
            server.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            await server.start()
        except Exception:
            logger.exception("Error running relay server")
            sys.exit(1)

if __name__ == "__main__":
    trio.run(main)
