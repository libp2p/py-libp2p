#!/usr/bin/env python3
"""Python relay server for hole punching interop tests."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from typing import TYPE_CHECKING, cast

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.tools.async_service import background_trio_service

if TYPE_CHECKING:
    from libp2p.abc import IHost, INetStream

logger = logging.getLogger(__name__)


class RelayServer:
    """Relay server for hole punching interop tests."""

    host: IHost | None
    relay_protocol: CircuitV2Protocol | None
    stop_event: trio.Event

    def __init__(self, port: int = 8000) -> None:
        self.port = port
        self.host = None
        self.relay_protocol = None
        self.stop_event = trio.Event()

    async def start(self) -> None:
        """Start the relay server."""
        # Create py-libp2p host (new_host used synchronously in many py-libp2p
        # examples)
        try:
            self.host = new_host(
                listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")]
            )
        except Exception:
            logger.exception("Failed to create host with new_host()")
            raise

        # Create custom relay limits with higher capacity
        limits = RelayLimits(
            duration=3600,  # 1 hour
            data=1024 * 1024 * 1024,  # 1 GB
            max_circuit_conns=1024,
            max_reservations=1024,
        )

        # Instantiate CircuitV2Protocol
        try:
            self.relay_protocol = CircuitV2Protocol(self.host, limits, allow_hop=True)
        except Exception:
            logger.exception("Failed to create CircuitV2Protocol with provided limits.")
            # If it fails, re-raise so caller can exit/see the error
            raise

        # Start the relay service
        async with background_trio_service(self.relay_protocol):
            await self.relay_protocol.event_started.wait()

            logger.info(f"Python relay server running on: {self.host.get_addrs()}")
            logger.info(f"Python relay server peer ID: {self.host.get_id()}")

            # Set up monitoring stream handler
            self.host.set_stream_handler(
                cast(TProtocol, "/relay/monitor/1.0.0"), self._handle_monitor_stream
            )

            # Wait for termination signal
            await self.stop_event.wait()

    async def _handle_monitor_stream(self, stream: INetStream) -> None:
        """Handle monitor stream requests."""
        if self.host is None:
            logger.error("Host is not initialized")
            return

        try:
            status = {
                "status": "active",
                "timestamp": int(time.time()),
                "connections": len(self.host.get_network().connections),
                "peer_id": str(self.host.get_id()),
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

    def stop(self) -> None:
        """Stop the relay server."""
        self.stop_event.set()

    def get_info(self) -> dict[str, object] | None:
        """Get server information."""
        if self.host is None:
            return None

        return {
            "peer_id": str(self.host.get_id()),
            "addresses": [str(addr) for addr in self.host.get_addrs()],
            "status": "active",
        }


async def main() -> None:
    """Main function to run the relay server."""
    parser = argparse.ArgumentParser(description="Python Relay Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument(
        "--print-id-only", action="store_true", help="Print only peer ID and exit"
    )
    parser.add_argument(
        "--print-info", action="store_true", help="Print server info as JSON and exit"
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    server = RelayServer(port=args.port)

    if args.print_id_only or args.print_info:
        # Start server briefly to get info
        try:
            server.host = new_host(
                listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{args.port}")]
            )

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
        def signal_handler(signum: int, frame: object = None) -> None:
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
