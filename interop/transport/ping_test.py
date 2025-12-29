#!/usr/bin/env python3
"""
Python libp2p ping test implementation for transport-interop tests.

This implementation follows the transport-interop test specification:
- Reads configuration from environment variables
- Connects to Redis for coordination
- Implements both dialer and listener roles
- Measures ping RTT and handshake times
- Outputs results in JSON format to stdout
"""

from datetime import datetime, timedelta
import ipaddress
import json
import logging
import os
import ssl
import sys
import tempfile
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import multiaddr
import redis
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
MAX_TEST_TIMEOUT = 300  # Max timeout (default Docker timeout is 600s)

logger = logging.getLogger("libp2p.ping_test")


def configure_logging():
    """Configure logging based on debug environment variable."""
    debug_enabled = os.getenv("debug", "false").upper() in ["DEBUG", "1", "TRUE", "YES"]

    if debug_enabled:
        logger_names = [
            "",
            "libp2p.ping_test",
            "libp2p",
            "libp2p.transport",
            "libp2p.network",
            "libp2p.protocol_muxer",
        ]
        for logger_name in logger_names:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
        print("Debug logging enabled via debug environment variable", file=sys.stderr)
    else:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("libp2p.ping_test").setLevel(logging.INFO)
        warning_loggers = [
            "multiaddr",
            "multiaddr.transforms",
            "multiaddr.codecs",
            "libp2p",
            "libp2p.transport",
        ]
        for logger_name in warning_loggers:
            logging.getLogger(logger_name).setLevel(logging.WARNING)


class PingTest:
    def __init__(self):
        """Initialize ping test with configuration from environment variables."""
        self.transport = os.getenv("transport", "tcp")
        self.muxer = os.getenv("muxer", "mplex")
        self.security = os.getenv("security", "noise")
        self.is_dialer = os.getenv("is_dialer", "false").lower() == "true"
        self.ip = os.getenv("ip", "0.0.0.0")
        self.redis_addr = os.getenv("redis_addr", "redis:6379")

        raw_timeout = int(os.getenv("test_timeout_seconds", "180"))
        self.test_timeout_seconds = min(raw_timeout, MAX_TEST_TIMEOUT)
        self.resp_timeout = max(30, int(self.test_timeout_seconds * 0.6))

        if ":" in self.redis_addr:
            self.redis_host, port = self.redis_addr.split(":")
            self.redis_port = int(port)
        else:
            self.redis_host = self.redis_addr
            self.redis_port = 6379

        self.host = None
        self.redis_client: redis.Redis | None = None
        self.ping_received = False

    def setup_redis(self) -> None:
        """Set up Redis connection."""
        self.redis_client = redis.Redis(
            host=self.redis_host, port=self.redis_port, decode_responses=True
        )
        self.redis_client.ping()
        print(
            f"Connected to Redis at {self.redis_host}:{self.redis_port}",
            file=sys.stderr,
        )

    def validate_configuration(self) -> None:
        """Validate configuration parameters."""
        valid_transports = ["tcp", "ws", "wss", "quic-v1"]
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

    def create_tls_client_config(self) -> ssl.SSLContext | None:
        """
        Create TLS client config for WSS dialing.

        Doesn't verify certificates for interop.
        """
        if self.transport == "wss":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            print(
                "[DEBUG] TLS client config created: verify_mode=0, "
                "check_hostname=False",
                file=sys.stderr,
            )
            return ctx
        return None

    def create_tls_server_config(self) -> ssl.SSLContext | None:
        """Create TLS server config for WSS listening with self-signed certificate."""
        if self.transport == "wss":
            try:
                # Generate a self-signed certificate for interop tests
                # This is needed for Python-to-Python WSS connections
                private_key = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=2048,
                )

                # Create a self-signed certificate
                subject = issuer = x509.Name(
                    [
                        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
                        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p"),
                        x509.NameAttribute(NameOID.COMMON_NAME, "libp2p.local"),
                    ]
                )

                cert = (
                    x509.CertificateBuilder()
                    .subject_name(subject)
                    .issuer_name(issuer)
                    .public_key(private_key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(datetime.utcnow())
                    .not_valid_after(datetime.utcnow() + timedelta(days=365))
                    .add_extension(
                        x509.SubjectAlternativeName(
                            [
                                x509.DNSName("localhost"),
                                x509.DNSName("libp2p.local"),
                                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                            ]
                        ),
                        critical=False,
                    )
                    .sign(private_key, hashes.SHA256())
                )

                # Create SSL context with the certificate
                ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                # Load the certificate and private key into the context
                # We need to use temporary files because load_cert_chain
                # expects file paths
                with (
                    tempfile.NamedTemporaryFile(mode="wb", delete=False) as cert_file,
                    tempfile.NamedTemporaryFile(mode="wb", delete=False) as key_file,
                ):
                    cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
                    key_file.write(
                        private_key.private_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PrivateFormat.PKCS8,
                            encryption_algorithm=serialization.NoEncryption(),
                        )
                    )
                    cert_path = cert_file.name
                    key_path = key_file.name

                try:
                    ctx.load_cert_chain(cert_path, key_path)
                    print(
                        "[DEBUG] WSS listener: Created TLS server config "
                        "with self-signed certificate",
                        file=sys.stderr,
                    )
                    return ctx
                finally:
                    # Clean up temporary files
                    try:
                        os.unlink(cert_path)
                        os.unlink(key_path)
                    except Exception:
                        pass

            except Exception as e:
                print(
                    f"[WARNING] Failed to create TLS server config: {e}",
                    file=sys.stderr,
                )
                import traceback

                traceback.print_exc(file=sys.stderr)
                return None
        return None

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
                        f"Error converting address {addr} to QUIC: {e}", file=sys.stderr
                    )
            if quic_addrs:
                return quic_addrs
            return [self._build_quic_addr("0.0.0.0", port)]

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
            return [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/ws")]

        elif self.transport == "wss":
            # Add /wss protocol to TCP addresses
            wss_addrs = []
            for addr in base_addrs:
                try:
                    protocols = self._get_protocol_names(addr)
                    if "wss" in protocols:
                        wss_addrs.append(addr)
                    elif "ws" in protocols:
                        # Convert /ws to /wss
                        p2p_value = None
                        if "p2p" in protocols:
                            p2p_value = addr.value_for_protocol("p2p")
                            if p2p_value:
                                addr = addr.decapsulate(
                                    multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                                )
                        # Remove /ws and add /wss
                        if "ws" in protocols:
                            addr = addr.decapsulate(multiaddr.Multiaddr("/ws"))
                        wss_addr = addr.encapsulate(multiaddr.Multiaddr("/wss"))
                        if p2p_value:
                            wss_addr = wss_addr.encapsulate(
                                multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                            )
                        wss_addrs.append(wss_addr)
                    else:
                        # Preserve /p2p component
                        p2p_value = None
                        if "p2p" in protocols:
                            p2p_value = addr.value_for_protocol("p2p")
                            if p2p_value:
                                addr = addr.decapsulate(
                                    multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                                )
                        wss_addr = addr.encapsulate(multiaddr.Multiaddr("/wss"))
                        if p2p_value:
                            wss_addr = wss_addr.encapsulate(
                                multiaddr.Multiaddr(f"/p2p/{p2p_value}")
                            )
                        wss_addrs.append(wss_addr)
                except Exception as e:
                    print(
                        f"Error converting address {addr} to WebSocket Secure: {e}",
                        file=sys.stderr,
                    )
            if wss_addrs:
                return wss_addrs
            return [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/wss")]

        return base_addrs

    def _get_peer_id(self, stream: INetStream) -> str:
        """Get peer ID from stream, suppressing warnings."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return stream.muxed_conn.peer_id
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
            # DEBUG: Print the full exception traceback
            import traceback

            error_msg = (
                str(e) if e else "Unknown error (exception object is None or empty)"
            )
            error_type = type(e).__name__ if e else "UnknownException"
            print(f"Error in ping handler: {error_type}: {error_msg}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            try:
                await stream.reset()
            except Exception:
                pass

    def log_protocols(self) -> None:
        """Log registered protocols for debugging."""
        try:
            protocols = self.host.get_mux().get_protocols()
            protocol_strs = [str(p) for p in protocols if p is not None]
            print(f"Registered protocols: {protocol_strs}", file=sys.stderr)
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
            elif self.transport == "wss" and "wss" in protocols:
                filtered.append(addr)
            elif self.transport == "quic-v1" and "quic-v1" in protocols:
                filtered.append(addr)
            elif self.transport == "tcp" and not any(
                p in protocols for p in ["ws", "wss", "quic-v1"]
            ):
                filtered.append(addr)
        return filtered if filtered else addresses

    def _replace_loopback_ip(self, addr) -> str:
        """Replace loopback IP with container IP for Docker networking."""
        ip_value = self._get_ip_value(addr)
        if ip_value not in ["127.0.0.1", "0.0.0.0", "::1", "::"]:
            return str(addr)

        actual_ip = self.get_container_ip()
        try:
            protocols = self._get_protocol_names(addr)
            is_ipv6 = "ip6" in protocols
            addr_parts = [f"/ip6/{actual_ip}" if is_ipv6 else f"/ip4/{actual_ip}"]

            found_ip = False
            for p in addr.protocols():
                if p.name in ["ip4", "ip6"]:
                    found_ip = True
                    continue
                if found_ip:
                    if p.value:
                        addr_parts.append(f"/{p.name}/{p.value}")
                    else:
                        addr_parts.append(f"/{p.name}")

            return str(multiaddr.Multiaddr("".join(addr_parts)))
        except Exception as e:
            print(
                f"Warning: Failed to replace IP using multiaddr API: {e}, "
                f"using string replacement",
                file=sys.stderr,
            )
            addr_str = str(addr)
            for old_ip in ["/ip4/0.0.0.0/", "/ip4/127.0.0.1/"]:
                if old_ip in addr_str:
                    return addr_str.replace(old_ip, f"/ip4/{actual_ip}/")
            return addr_str

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

        # Fallback: replace loopback IP
        return self._replace_loopback_ip(filtered[0])

    async def run_listener(self) -> None:
        """Run the listener role."""
        self.validate_configuration()
        await self._connect_redis_with_retry()

        # Create security and muxer options
        sec_opt, key_pair = self.create_security_options()
        muxer_opt = self.create_muxer_options()
        # CRITICAL FIX: Use create_listen_addresses() to properly handle QUIC transport
        # This converts TCP addresses to QUIC addresses when transport is "quic-v1"
        listen_addrs = self.create_listen_addresses(0)

        # Configure TLS for WSS
        tls_client_config = self.create_tls_client_config()
        tls_server_config = self.create_tls_server_config()
        if tls_client_config or tls_server_config:
            print(
                f"[DEBUG] Passing TLS config to new_host: "
                f"client={tls_client_config is not None}, "
                f"server={tls_server_config is not None}",
                file=sys.stderr,
            )

        self.host = new_host(
            key_pair=key_pair,
            sec_opt=sec_opt,
            muxer_opt=muxer_opt,
            listen_addrs=listen_addrs,
            enable_quic=(self.transport == "quic-v1"),
            tls_client_config=tls_client_config,
            tls_server_config=tls_server_config,
        )
        self.host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)
        self.log_protocols()

        async with self.host.run(listen_addrs=listen_addrs):
            all_addrs = self.host.get_addrs()
            if not all_addrs:
                raise RuntimeError("No listen addresses available")

            actual_addr = self._get_publishable_address(all_addrs)
            print(
                f"Publishing address for transport {self.transport}: {actual_addr}",
                file=sys.stderr,
            )
            self.redis_client.rpush("listenerAddr", actual_addr)
            print("Listener ready, waiting for dialer to connect...", file=sys.stderr)

            wait_timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
            check_interval = 0.5
            elapsed = 0

            while elapsed < wait_timeout:
                if self.ping_received:
                    print(
                        "Ping received and responded, listener exiting", file=sys.stderr
                    )
                    return
                await trio.sleep(check_interval)
                elapsed += check_interval

            if not self.ping_received:
                print(
                    f"Timeout: No ping received within {wait_timeout} seconds",
                    file=sys.stderr,
                )
            sys.exit(1)

    async def _connect_redis_with_retry(
        self, max_retries: int = 10, retry_delay: float = 1.0
    ) -> None:
        """Connect to Redis with retry mechanism."""
        print("Connecting to Redis...", file=sys.stderr)
        for attempt in range(max_retries):
            try:
                self.redis_client = redis.Redis(
                    host=self.redis_host, port=self.redis_port, decode_responses=True
                )
                self.redis_client.ping()
                print(
                    f"Successfully connected to Redis on attempt {attempt + 1}",
                    file=sys.stderr,
                )
                return
            except Exception as e:
                print(
                    f"Redis connection attempt {attempt + 1} failed: {e}",
                    file=sys.stderr,
                )
                if attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...", file=sys.stderr)
                    await trio.sleep(retry_delay)
        raise RuntimeError(f"Failed to connect to Redis after {max_retries} attempts")

    def _debug_connection_state(self, network, peer_id) -> None:
        """Debug connection state (only if debug logging enabled)."""
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
                            f"[DEBUG] Connection {i} muxer error: {e}", file=sys.stderr
                        )
        except Exception as e:
            print(f"[DEBUG] Error checking connections: {e}", file=sys.stderr)

    async def _create_stream_with_retry(self, peer_id) -> INetStream:
        """Create ping stream with retry mechanism for connection readiness."""
        max_retries = 3
        retry_delay = 0.5

        print("Creating ping stream", file=sys.stderr)
        print(
            f"[DEBUG] About to create stream for protocol {PING_PROTOCOL_ID}",
            file=sys.stderr,
        )

        for attempt in range(max_retries):
            try:
                stream = await self.host.new_stream(peer_id, [PING_PROTOCOL_ID])
                print("Ping stream created successfully", file=sys.stderr)
                return stream
            except Exception as e:
                if attempt < max_retries - 1:
                    print(
                        f"[DEBUG] Stream creation attempt {attempt + 1} "
                        f"failed: {e}, retrying...",
                        file=sys.stderr,
                    )
                    await trio.sleep(retry_delay)
                else:
                    print(
                        f"[DEBUG] Stream creation failed after "
                        f"{max_retries} attempts: {e}",
                        file=sys.stderr,
                    )
                    raise
        raise RuntimeError("Failed to create ping stream after retries")

    async def run_dialer(self) -> None:
        """Run the dialer role."""
        print("Running as dialer", file=sys.stderr)

        try:
            self.validate_configuration()
            await self._connect_redis_with_retry()

            print("Waiting for listener address from Redis...", file=sys.stderr)
            redis_wait_timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
            result = self.redis_client.blpop("listenerAddr", timeout=redis_wait_timeout)
            if not result:
                raise RuntimeError(
                    f"Timeout waiting for listener address after "
                    f"{redis_wait_timeout} seconds"
                )

            listener_addr = result[1]
            print(f"Got listener address: {listener_addr}", file=sys.stderr)

            # Convert /tls/ws to /wss for WSS transport
            # (Go uses /tls/ws, py-libp2p expects /wss)
            # This is needed because Go publishes /tls/ws but py-libp2p's
            # WebSocket transport expects /wss
            # Note: py-libp2p's parser can handle /tls/ws, but we convert
            # to /wss for consistency
            original_addr = listener_addr
            if "/tls/ws" in listener_addr:
                if self.transport == "wss":
                    listener_addr = listener_addr.replace("/tls/ws", "/wss")
                    print(
                        f"[DEBUG] Converted listener address from /tls/ws "
                        f"to /wss: {original_addr} -> {listener_addr}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[WARNING] Found /tls/ws in address but transport "
                        f"is {self.transport}, not converting",
                        file=sys.stderr,
                    )

            # Create security and muxer options
            sec_opt, key_pair = self.create_security_options()
            muxer_opt = self.create_muxer_options()

            # WS/WSS dialer workaround: need listen addresses to register
            # transport (py-libp2p limitation)
            # For WSS dialers, we use WS addresses for transport registration
            # (no TLS needed)
            # The actual dialing will use the converted WSS address
            if self.transport == "wss":
                # Use WS addresses for transport registration
                # (WebSocket transport handles both WS and WSS)
                # The actual connection will use WSS when dialing the
                # converted address
                temp_transport = self.transport
                # Temporarily set to "ws" to create WS listen addresses
                self.transport = "ws"
                dialer_listen_addrs = self.create_listen_addresses(0)
                self.transport = temp_transport  # Restore original transport
                if dialer_listen_addrs:
                    addr_strs = [str(addr) for addr in dialer_listen_addrs]
                    print(
                        f"WSS dialer: registering WebSocket transport with "
                        f"WS addresses for transport registration: "
                        f"{addr_strs}",
                        file=sys.stderr,
                    )
            else:
                dialer_listen_addrs = (
                    self.create_listen_addresses(0) if self.transport == "ws" else None
                )
                if dialer_listen_addrs:
                    addr_strs = [str(addr) for addr in dialer_listen_addrs]
                    print(
                        f"Registering {self.transport.upper()} transport "
                        f"for dialer with addresses: {addr_strs}",
                        file=sys.stderr,
                    )

            # Configure TLS for WSS dialers
            tls_client_config = self.create_tls_client_config()
            tls_server_config = None  # Dialers don't need server config
            if tls_client_config:
                print(
                    "[DEBUG] Passing TLS config to new_host: client=True, server=False",
                    file=sys.stderr,
                )

            host_kwargs = {
                "key_pair": key_pair,
                "sec_opt": sec_opt,
                "muxer_opt": muxer_opt,
                "enable_quic": (self.transport == "quic-v1"),
                "tls_client_config": tls_client_config,
                "tls_server_config": tls_server_config,
            }
            if dialer_listen_addrs:
                host_kwargs["listen_addrs"] = dialer_listen_addrs

            self.host = new_host(**host_kwargs)

            async with self.host.run(listen_addrs=dialer_listen_addrs or []):
                handshake_start = time.time()

                # Debug: Show the address before creating multiaddr
                print(
                    f"[DEBUG] Creating multiaddr from address: {listener_addr}",
                    file=sys.stderr,
                )
                maddr = multiaddr.Multiaddr(listener_addr)
                protocols = [p.name for p in maddr.protocols()]
                print(f"[DEBUG] Multiaddr protocols: {protocols}", file=sys.stderr)

                # Debug: Check if transport can dial this address
                try:
                    from libp2p.transport.websocket.multiaddr_utils import (
                        is_valid_websocket_multiaddr,
                    )

                    can_parse = is_valid_websocket_multiaddr(maddr)
                    print(
                        f"[DEBUG] WebSocket multiaddr validation: {can_parse}",
                        file=sys.stderr,
                    )
                except Exception as e:
                    print(
                        f"[DEBUG] Could not validate WebSocket multiaddr: {e}",
                        file=sys.stderr,
                    )

                info = info_from_p2p_addr(maddr)

                print(f"Connecting to {listener_addr}", file=sys.stderr)
                print(
                    f"[DEBUG] About to call host.connect() for {info.peer_id}",
                    file=sys.stderr,
                )
                peer_addrs = [str(addr) for addr in info.addrs]
                print(f"[DEBUG] Peer info addresses: {peer_addrs}", file=sys.stderr)

                try:
                    await self.host.connect(info)
                except Exception as e:
                    error_type = type(e).__name__
                    print(
                        f"[DEBUG] Connection error type: {error_type}", file=sys.stderr
                    )
                    print(f"[DEBUG] Connection error: {e}", file=sys.stderr)
                    # Try to get more details about the error
                    if hasattr(e, "__cause__") and e.__cause__:
                        print(
                            f"[DEBUG] Connection error cause: {e.__cause__}",
                            file=sys.stderr,
                        )
                    raise
                print("Connected successfully", file=sys.stderr)
                print(
                    "[DEBUG] host.connect() completed, checking connection state",
                    file=sys.stderr,
                )

                self._debug_connection_state(self.host.get_network(), info.peer_id)

                # Brief delay to ensure connection is fully ready for stream creation
                # This handles timing issues that can occur with some implementations
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
            import traceback

            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

    async def run(self) -> None:
        """Main run method."""
        try:
            print("Setting up Redis connection...", file=sys.stderr)
            await self._connect_redis_with_retry()

            if self.is_dialer:
                await self.run_dialer()
            else:
                await self.run_listener()

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            if self.redis_client:
                self.redis_client.close()

    def get_container_ip(self) -> str:
        """Get the container's actual IP address for Docker networking."""
        import socket
        import subprocess

        try:
            # Try hostname -I first (works in most Docker containers)
            try:
                result = subprocess.run(
                    ["hostname", "-I"], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().split()[0]
            except Exception:
                pass

            # Fallback: Connect to a remote address to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            # Fallback to a reasonable default
            return "172.17.0.1"


async def main():
    """Main entry point."""
    configure_logging()
    ping_test = PingTest()
    await ping_test.run()


if __name__ == "__main__":
    trio.run(main)
