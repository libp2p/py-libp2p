#!/usr/bin/env python3
"""
Local Python ping listener for transport-interop tests.
This version writes the listener address to a file instead of Redis.
"""

import logging
from pathlib import Path
import sys

import multiaddr
import trio

from libp2p import create_mplex_muxer_option, new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.utils.address_validation import get_available_interfaces

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32

logger = logging.getLogger("libp2p.local_ping_listener")


def configure_logging(debug: bool = False):
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )
    if not debug:
        logging.getLogger("libp2p").setLevel(logging.WARNING)


class LocalPingListener:
    def __init__(
        self,
        transport: str = "ws",
        port: int = 0,
        address_file: str = "/tmp/libp2p_listener_addr.txt",
        debug: bool = False,
    ):
        self.transport = transport
        self.port = port
        self.address_file = Path(address_file)
        self.debug = debug
        self.host = None
        self.ping_received = False

    def create_security_options(self):
        """Create security options (noise)."""
        key_pair = create_new_key_pair()
        noise_key_pair = create_new_x25519_key_pair()
        transport = NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=noise_key_pair.private_key,
            early_data=None,
        )
        return {NOISE_PROTOCOL_ID: transport}, key_pair

    def create_listen_addresses(self, port: int = 0) -> list:
        """Create listen addresses for WebSocket transport."""
        base_addrs = get_available_interfaces(port, protocol="tcp")
        ws_addrs = []
        for addr in base_addrs:
            try:
                protocols = [p.name for p in addr.protocols()]
                if "ws" in protocols or "wss" in protocols:
                    ws_addrs.append(addr)
                else:
                    # Preserve /p2p component if present
                    p2p_value = None
                    if "p2p" in protocols:
                        p2p_value = addr.value_for_protocol("p2p")
                        if p2p_value:
                            addr = addr.decapsulate(
                                multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                            )
                    ws_addr = addr.encapsulate(multiaddr.Multiaddr("/ws"))
                    if p2p_value:
                        ws_addr = ws_addr.encapsulate(
                            multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                        )
                    ws_addrs.append(ws_addr)
            except Exception as e:
                print(
                    f"Error converting address {addr} to WebSocket: {e}",
                    file=sys.stderr,
                )
        if ws_addrs:
            return ws_addrs
        return [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws")]

    def _get_peer_id(self, stream: INetStream) -> str:
        """Get peer ID from stream."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return str(stream.muxed_conn.peer_id)
            except (AttributeError, Exception):
                return "unknown"

    async def handle_ping(self, stream: INetStream) -> None:
        """Handle incoming ping requests."""
        try:
            payload = await stream.read(PING_LENGTH)
            if payload is not None:
                peer_id = self._get_peer_id(stream)
                print(f"received ping from {peer_id}", file=sys.stderr)
                await stream.write(payload)
                print(f"responded with pong to {peer_id}", file=sys.stderr)
                self.ping_received = True
        except Exception as e:
            print(f"Error in ping handler: {e}", file=sys.stderr)
            if self.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
            try:
                await stream.reset()
            except Exception:
                pass

    def _get_publishable_address(self, addresses: list) -> str:
        """Get the best address to publish."""
        # Prefer non-loopback addresses
        for addr in addresses:
            ip_value = addr.value_for_protocol("ip4") or addr.value_for_protocol("ip6")
            if ip_value and ip_value not in ["127.0.0.1", "0.0.0.0", "::1", "::"]:
                return str(addr)
        # Fallback: use first address
        return str(addresses[0])

    def write_address_to_file(self, address: str) -> None:
        """Write listener address to file."""
        self.address_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.address_file, "w") as f:
            f.write(address)
        print(
            f"Wrote listener address to {self.address_file}: {address}", file=sys.stderr
        )

    async def run(self) -> None:
        """Run the listener."""
        try:
            # Create security and muxer options
            sec_opt, key_pair = self.create_security_options()
            muxer_opt = create_mplex_muxer_option()
            listen_addrs = self.create_listen_addresses(self.port)

            self.host = new_host(
                key_pair=key_pair,
                sec_opt=sec_opt,
                muxer_opt=muxer_opt,
                listen_addrs=listen_addrs,
            )
            self.host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)

            async with self.host.run(listen_addrs=listen_addrs):
                all_addrs = self.host.get_addrs()
                if not all_addrs:
                    raise RuntimeError("No listen addresses available")

                # Filter for WebSocket addresses
                ws_addrs = [
                    addr
                    for addr in all_addrs
                    if "ws" in [p.name for p in addr.protocols()]
                ]
                if not ws_addrs:
                    ws_addrs = all_addrs

                actual_addr = self._get_publishable_address(ws_addrs)
                print("Listener ready, listening on:", file=sys.stderr)
                for addr in ws_addrs:
                    print(f"  {addr}", file=sys.stderr)

                # Write address to file for dialer to read
                self.write_address_to_file(actual_addr)

                print("Waiting for dialer to connect...", file=sys.stderr)

                # Wait for ping (with timeout)
                timeout = 300  # 5 minutes
                check_interval = 0.5
                elapsed = 0

                while elapsed < timeout:
                    if self.ping_received:
                        print(
                            "Ping received and responded, listener exiting",
                            file=sys.stderr,
                        )
                        return
                    await trio.sleep(check_interval)
                    elapsed += check_interval

                if not self.ping_received:
                    print(
                        f"Timeout: No ping received within {timeout} seconds",
                        file=sys.stderr,
                    )
                    sys.exit(1)

        except Exception as e:
            print(f"Listener error: {e}", file=sys.stderr)
            if self.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
            sys.exit(1)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Local Python ping listener")
    parser.add_argument(
        "--port", type=int, default=0, help="Port number (0 = auto-select)"
    )
    parser.add_argument(
        "--address-file",
        type=str,
        default="/tmp/libp2p_listener_addr.txt",
        help="File to write listener address",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--transport",
        type=str,
        default="ws",
        choices=["ws"],
        help="Transport protocol (default: ws)",
    )

    args = parser.parse_args()

    configure_logging(debug=args.debug)

    listener = LocalPingListener(
        transport=args.transport,
        port=args.port,
        address_file=args.address_file,
        debug=args.debug,
    )

    await listener.run()


if __name__ == "__main__":
    trio.run(main)
