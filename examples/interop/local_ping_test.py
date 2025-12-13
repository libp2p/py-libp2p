#!/usr/bin/env python3
"""
Local libp2p ping test implementation.

This is a standalone console script version of the transport-interop ping test
that runs without Docker or Redis dependencies. It supports both listener and
dialer roles and measures ping RTT and handshake times.

Usage:
    # Run as listener (waits for connection)
    python local_ping_test.py --listener --port 8000

    # Run as dialer (connects to listener)
    python local_ping_test.py --dialer --destination /ip4/127.0.0.1/tcp/8000/p2p/Qm...
"""

import argparse
import json
import logging
import sys
import time

import multiaddr
import trio

from libp2p import create_mplex_muxer_option, create_yamux_muxer_option, new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.utils.address_validation import get_available_interfaces

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
MAX_TEST_TIMEOUT = 300
DEFAULT_RESP_TIMEOUT = 30

logger = logging.getLogger("libp2p.ping_test")


def configure_logging(debug: bool = False):
    """Configure logging based on debug flag."""
    # Set up basic handler on root logger if not already configured
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    if debug:
        # Set DEBUG level for all relevant loggers (they will propagate to root)
        logger_names = [
            "libp2p.ping_test",
            "libp2p",
            "libp2p.transport",
            "libp2p.transport.quic",
            "libp2p.transport.quic.connection",
            "libp2p.transport.quic.listener",
            "libp2p.network",
            "libp2p.network.connection",
            "libp2p.network.connection.swarm_connection",
            "libp2p.protocol_muxer",
            "libp2p.protocol_muxer.multiselect",
            "libp2p.host",
            "libp2p.host.basic_host",
        ]
        for logger_name in logger_names:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.DEBUG)
            # Ensure propagation is enabled (default, but be explicit)
            logger.propagate = True
        print("Debug logging enabled", file=sys.stderr)
    else:
        root_logger.setLevel(logging.INFO)
        logging.getLogger("libp2p.ping_test").setLevel(logging.INFO)
        # Suppress verbose logs from dependencies
        for logger_name in [
            "multiaddr",
            "multiaddr.transforms",
            "multiaddr.codecs",
            "libp2p",
            "libp2p.transport",
        ]:
            logging.getLogger(logger_name).setLevel(logging.WARNING)


class PingTest:
    def __init__(
        self,
        transport: str = "tcp",
        muxer: str = "mplex",
        security: str = "noise",
        port: int = 0,
        destination: str | None = None,
        test_timeout: int = 180,
        debug: bool = False,
    ):
        """Initialize ping test with configuration."""
        self.transport = transport
        self.muxer = muxer
        self.security = security
        self.port = port
        self.destination = destination
        self.is_dialer = destination is not None

        raw_timeout = int(test_timeout)
        self.test_timeout_seconds = min(raw_timeout, MAX_TEST_TIMEOUT)
        self.resp_timeout = max(
            DEFAULT_RESP_TIMEOUT, int(self.test_timeout_seconds * 0.6)
        )
        self.debug = debug

        self.host = None
        self.ping_received = False

    def validate_configuration(self) -> None:
        """Validate configuration parameters."""
        valid_transports = ["tcp", "ws", "quic-v1"]
        valid_security = ["noise", "plaintext"]
        valid_muxers = ["mplex", "yamux"]

        if self.transport not in valid_transports:
            raise ValueError(
                f"Unsupported transport: {self.transport}. "
                f"Supported: {valid_transports}"
            )
        if self.security not in valid_security:
            raise ValueError(
                f"Unsupported security: {self.security}. Supported: {valid_security}"
            )
        if self.muxer not in valid_muxers:
            raise ValueError(
                f"Unsupported muxer: {self.muxer}. Supported: {valid_muxers}"
            )

    def create_security_options(self):
        """Create security options based on configuration."""
        key_pair = create_new_key_pair()

        if self.security == "noise":
            noise_key_pair = create_new_x25519_key_pair()
            transport = NoiseTransport(
                libp2p_keypair=key_pair,
                noise_privkey=noise_key_pair.private_key,
                early_data=None,
            )
            return {NOISE_PROTOCOL_ID: transport}, key_pair
        elif self.security == "plaintext":
            transport = InsecureTransport(
                local_key_pair=key_pair,
                secure_bytes_provider=None,
                peerstore=None,
            )
            return {PLAINTEXT_PROTOCOL_ID: transport}, key_pair
        else:
            raise ValueError(f"Unsupported security: {self.security}")

    def create_muxer_options(self):
        """Create muxer options based on configuration."""
        if self.muxer == "yamux":
            return create_yamux_muxer_option()
        elif self.muxer == "mplex":
            return create_mplex_muxer_option()
        else:
            raise ValueError(f"Unsupported muxer: {self.muxer}")

    def _get_ip_value(self, addr) -> str | None:
        """Extract IP value from multiaddr (IPv4 or IPv6)."""
        return addr.value_for_protocol("ip4") or addr.value_for_protocol("ip6")

    def _get_protocol_names(self, addr) -> list:
        """Get protocol names from multiaddr."""
        return [p.name for p in addr.protocols()]

    def _build_quic_addr(self, ip_value: str, port: int) -> multiaddr.Multiaddr:
        """Build QUIC address from IP and port."""
        is_ipv6 = ":" in ip_value
        if is_ipv6:
            base = multiaddr.Multiaddr(f"/ip6/{ip_value}/udp/{port}")
        else:
            base = multiaddr.Multiaddr(f"/ip4/{ip_value}/udp/{port}")
        return base.encapsulate(multiaddr.Multiaddr("/quic-v1"))

    def create_listen_addresses(self, port: int = 0) -> list:
        """Create listen addresses based on transport type."""
        base_addrs = get_available_interfaces(port, protocol="tcp")

        if self.transport == "quic-v1":
            # Convert TCP addresses to UDP/QUIC addresses
            quic_addrs = []
            for addr in base_addrs:
                try:
                    ip_value = self._get_ip_value(addr)
                    tcp_port = addr.value_for_protocol("tcp") or port
                    if ip_value:
                        quic_addr = self._build_quic_addr(ip_value, tcp_port)
                        # Preserve /p2p component if present
                        if "p2p" in self._get_protocol_names(addr):
                            p2p_value = addr.value_for_protocol("p2p")
                            if p2p_value:
                                quic_addr = quic_addr.encapsulate(
                                    multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                                )
                        quic_addrs.append(quic_addr)
                except Exception as e:
                    print(
                        f"Error converting address {addr} to QUIC: {e}",
                        file=sys.stderr,
                    )
            if quic_addrs:
                return quic_addrs
            return [self._build_quic_addr("127.0.0.1", port)]

        elif self.transport == "ws":
            # Add /ws protocol to TCP addresses
            ws_addrs = []
            for addr in base_addrs:
                try:
                    protocols = self._get_protocol_names(addr)
                    if "ws" in protocols or "wss" in protocols:
                        ws_addrs.append(addr)
                    else:
                        # Preserve /p2p component
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

        return base_addrs

    def _get_peer_id(self, stream: INetStream) -> str:
        """Get peer ID from stream, suppressing warnings."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return str(stream.muxed_conn.peer_id)  # type: ignore
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
            import traceback

            error_msg = (
                str(e) if e else "Unknown error (exception object is None or empty)"
            )
            error_type = type(e).__name__ if e else "UnknownException"
            print(f"Error in ping handler: {error_type}: {error_msg}", file=sys.stderr)
            if self.debug:
                traceback.print_exc(file=sys.stderr)
            try:
                await stream.reset()
            except Exception:
                pass

    def log_protocols(self) -> None:
        """Log registered protocols for debugging."""
        try:
            protocols = self.host.get_mux().get_protocols()  # type: ignore
            protocols_str = [str(p) for p in protocols if p is not None]
            print(f"Registered protocols: {protocols_str}", file=sys.stderr)
        except Exception as e:
            print(f"Error getting protocols: {e}", file=sys.stderr)

    async def send_ping(self, stream: INetStream) -> float:
        """Send ping and measure RTT."""
        try:
            payload = b"\x01" * PING_LENGTH
            peer_id = self._get_peer_id(stream)
            print(f"sending ping to {peer_id}", file=sys.stderr)

            ping_start = time.time()
            await stream.write(payload)

            with trio.fail_after(self.resp_timeout):
                response = await stream.read(PING_LENGTH)
                ping_end = time.time()

                if response == payload:
                    print(f"received pong from {peer_id}", file=sys.stderr)
                    return (ping_end - ping_start) * 1000
                else:
                    raise Exception("Invalid ping response")
        except Exception as e:
            print(f"error occurred: {e}", file=sys.stderr)
            raise

    def _filter_addresses_by_transport(self, addresses: list) -> list:
        """Filter addresses to match current transport type."""
        filtered = []
        for addr in addresses:
            protocols = self._get_protocol_names(addr)
            if self.transport == "ws" and ("ws" in protocols or "wss" in protocols):
                filtered.append(addr)
            elif self.transport == "quic-v1" and "quic-v1" in protocols:
                filtered.append(addr)
            elif self.transport == "tcp" and not any(
                p in protocols for p in ["ws", "wss", "quic-v1"]
            ):
                filtered.append(addr)
        return filtered if filtered else addresses

    def _get_publishable_address(self, addresses: list) -> str:
        """Get the best address to publish, preferring non-loopback."""
        filtered = self._filter_addresses_by_transport(addresses)
        if not filtered:
            print(
                f"Warning: No addresses matched transport {self.transport}, "
                f"using all addresses",
                file=sys.stderr,
            )
            filtered = addresses

        # Prefer non-loopback addresses
        for addr in filtered:
            ip_value = self._get_ip_value(addr)
            if ip_value and ip_value not in ["127.0.0.1", "0.0.0.0", "::1", "::"]:
                return str(addr)

        # Fallback: use first address (for localhost testing)
        return str(filtered[0])

    async def run_listener(self) -> None:
        """Run the listener role."""
        self.validate_configuration()

        # Create security and muxer options
        sec_opt, key_pair = self.create_security_options()
        muxer_opt = self.create_muxer_options()
        listen_addrs = self.create_listen_addresses(self.port)

        self.host = new_host(  # type: ignore
            key_pair=key_pair,
            sec_opt=sec_opt,
            muxer_opt=muxer_opt,
            listen_addrs=listen_addrs,
            enable_quic=(self.transport == "quic-v1"),
        )
        self.host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)  # type: ignore
        self.log_protocols()

        async with self.host.run(listen_addrs=listen_addrs):  # type: ignore
            all_addrs = self.host.get_addrs()  # type: ignore
            if not all_addrs:
                raise RuntimeError("No listen addresses available")

            actual_addr = self._get_publishable_address(all_addrs)
            print("Listener ready, listening on:", file=sys.stderr)
            for addr in all_addrs:
                print(f"  {addr}", file=sys.stderr)
            print("\nTo connect, use this address:", file=sys.stderr)
            print(f"  {actual_addr}", file=sys.stderr)
            print("Waiting for dialer to connect...", file=sys.stderr)

            wait_timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
            check_interval = 0.5
            elapsed = 0

            while elapsed < wait_timeout:
                if self.ping_received:
                    print(
                        "Ping received and responded, listener exiting",
                        file=sys.stderr,
                    )
                    return
                await trio.sleep(float(check_interval))  # type: ignore
                elapsed += check_interval

            if not self.ping_received:
                print(
                    f"Timeout: No ping received within {wait_timeout} seconds",
                    file=sys.stderr,
                )
            sys.exit(1)

    def _debug_connection_state(self, network, peer_id) -> None:
        """Debug connection state (only if debug logging enabled)."""
        if not self.debug:
            return
        try:
            if hasattr(network, "get_connections_to_peer"):
                connections = network.get_connections_to_peer(peer_id)
            elif hasattr(network, "connections"):
                connections = [
                    c
                    for c in network.connections.values()
                    if c.get_peer_id() == peer_id
                ]
            else:
                connections = []
            print(
                f"[DEBUG] Found {len(connections)} connections to peer {peer_id}",
                file=sys.stderr,
            )
            for i, conn in enumerate(connections):
                muxed = hasattr(conn, "get_muxer")
                print(
                    f"[DEBUG] Connection {i}: {type(conn).__name__}, muxed: {muxed}",
                    file=sys.stderr,
                )
                if muxed:
                    try:
                        muxer_type = type(conn.get_muxer()).__name__
                        print(
                            f"[DEBUG] Connection {i} muxer: {muxer_type}",
                            file=sys.stderr,
                        )
                    except Exception as e:
                        print(
                            f"[DEBUG] Connection {i} muxer error: {e}",
                            file=sys.stderr,
                        )
        except Exception as e:
            print(f"[DEBUG] Error checking connections: {e}", file=sys.stderr)

    async def _create_stream_with_retry(self, peer_id) -> INetStream:
        """Create ping stream with retry mechanism for connection readiness."""
        max_retries = 3
        retry_delay = 0.5

        print("Creating ping stream", file=sys.stderr)
        if self.debug:
            print(
                f"[DEBUG] About to create stream for protocol {PING_PROTOCOL_ID}",
                file=sys.stderr,
            )

        for attempt in range(max_retries):
            try:
                stream = await self.host.new_stream(peer_id, [PING_PROTOCOL_ID])  # type: ignore
                print("Ping stream created successfully", file=sys.stderr)
                return stream
            except Exception as e:
                if attempt < max_retries - 1:
                    if self.debug:
                        print(
                            f"[DEBUG] Stream creation attempt {attempt + 1} "
                            f"failed: {e}, retrying...",
                            file=sys.stderr,
                        )
                    await trio.sleep(retry_delay)
                else:
                    if self.debug:
                        print(
                            f"[DEBUG] Stream creation failed after {max_retries} "
                            f"attempts: {e}",
                            file=sys.stderr,
                        )
                    raise
        raise RuntimeError("Failed to create ping stream after retries")

    async def run_dialer(self) -> None:
        """Run the dialer role."""
        print("Running as dialer", file=sys.stderr)

        try:
            self.validate_configuration()

            if not self.destination:
                raise ValueError("Destination address is required for dialer mode")

            listener_addr = self.destination
            print(f"Connecting to listener at: {listener_addr}", file=sys.stderr)

            # Create security and muxer options
            sec_opt, key_pair = self.create_security_options()
            muxer_opt = self.create_muxer_options()

            # WS dialer workaround: need listen addresses to register transport
            # (py-libp2p limitation)
            dialer_listen_addrs = (
                self.create_listen_addresses(self.port)
                if self.transport == "ws"
                else None
            )
            if dialer_listen_addrs:
                addrs_str = [str(addr) for addr in dialer_listen_addrs]
                print(
                    f"Registering WS transport for dialer with addresses: {addrs_str}",
                    file=sys.stderr,
                )

            host_kwargs = {
                "key_pair": key_pair,
                "sec_opt": sec_opt,
                "muxer_opt": muxer_opt,
                "enable_quic": (self.transport == "quic-v1"),
            }
            if dialer_listen_addrs:
                host_kwargs["listen_addrs"] = dialer_listen_addrs  # type: ignore

            self.host = new_host(**host_kwargs)  # type: ignore

            async with self.host.run(listen_addrs=dialer_listen_addrs or []):  # type: ignore
                handshake_start = time.time()
                maddr = multiaddr.Multiaddr(listener_addr)
                info = info_from_p2p_addr(maddr)

                print(f"Connecting to {listener_addr}", file=sys.stderr)
                if self.debug:
                    print(
                        f"[DEBUG] About to call host.connect() for {info.peer_id}",
                        file=sys.stderr,
                    )
                await self.host.connect(info)  # type: ignore
                print("Connected successfully", file=sys.stderr)
                if self.debug:
                    print(
                        "[DEBUG] host.connect() completed, checking connection state",
                        file=sys.stderr,
                    )

                self._debug_connection_state(self.host.get_network(), info.peer_id)  # type: ignore

                # Brief delay to ensure connection is fully ready for stream creation
                await trio.sleep(0.1)

                # Retry stream creation to handle cases where connection needs more time
                stream = await self._create_stream_with_retry(info.peer_id)

                print("Performing ping test", file=sys.stderr)
                ping_rtt = await self.send_ping(stream)
                print(f"Ping test completed, RTT: {ping_rtt}ms", file=sys.stderr)

                handshake_plus_one_rtt = (time.time() - handshake_start) * 1000
                result = {
                    "handshakePlusOneRTTMillis": handshake_plus_one_rtt,
                    "pingRTTMilllis": ping_rtt,
                }
                print(f"Outputting results: {result}", file=sys.stderr)
                print(json.dumps(result))

                await stream.close()
                print("Stream closed successfully", file=sys.stderr)

        except Exception as e:
            print(f"Dialer error: {e}", file=sys.stderr)
            if self.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
            sys.exit(1)

    async def run(self) -> None:
        """Main run method."""
        try:
            if self.is_dialer:
                await self.run_dialer()
            else:
                await self.run_listener()

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if self.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
            sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Local libp2p ping test - standalone console script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run as listener
  python local_ping_test.py --listener --port 8000

  # Run as dialer (connect to listener)
  python local_ping_test.py --dialer --destination /ip4/127.0.0.1/tcp/8000/p2p/Qm...

  # With custom transport/muxer/security
  python local_ping_test.py --listener --transport ws --muxer yamux --security noise
        """,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--listener",
        action="store_true",
        help="Run as listener (wait for connection)",
    )
    mode_group.add_argument(
        "--dialer", action="store_true", help="Run as dialer (connect to listener)"
    )

    # Connection options
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="Destination multiaddr (required for dialer)",
    )
    parser.add_argument(
        "-p", "--port", type=int, default=0, help="Port number (0 = auto-select)"
    )

    # Configuration options
    parser.add_argument(
        "--transport",
        choices=["tcp", "ws", "quic-v1"],
        default="tcp",
        help="Transport protocol (default: tcp)",
    )
    parser.add_argument(
        "--muxer",
        choices=["mplex", "yamux"],
        default="mplex",
        help="Stream muxer (default: mplex)",
    )
    parser.add_argument(
        "--security",
        choices=["noise", "plaintext"],
        default="noise",
        help="Security protocol (default: noise)",
    )

    # Test options
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=180,
        help="Test timeout in seconds (default: 180)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Validate arguments
    if args.dialer and not args.destination:
        parser.error("--destination is required when running as dialer")

    configure_logging(debug=args.debug)

    ping_test = PingTest(
        transport=args.transport,
        muxer=args.muxer,
        security=args.security,
        port=args.port,
        destination=args.destination,
        test_timeout=args.test_timeout,
        debug=args.debug,
    )

    try:
        trio.run(ping_test.run)
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
