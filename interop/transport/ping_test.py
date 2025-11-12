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

import json
import logging
import os
import sys
import time
from typing import Optional

import redis
import trio
import multiaddr
from libp2p import new_host, create_yamux_muxer_option, create_mplex_muxer_option
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID, Transport as NoiseTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.utils.address_validation import get_available_interfaces
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
MAX_TEST_TIMEOUT = 300  # Max timeout (default Docker timeout is 600s)

# Get logger for this module - will automatically use py-libp2p's logging system
# when "debug" environment variable is set, otherwise will be disabled
logger = logging.getLogger("libp2p.ping_test")

# Configure logging for TCP tests
def configure_logging():
    """Configure logging based on debug environment variable."""
    debug_enabled = os.getenv("debug", "false").upper() in ["DEBUG", "1", "TRUE", "YES"]
    logging.getLogger().setLevel(logging.INFO)
    
    if debug_enabled:
        for logger_name in ["", "libp2p.ping_test", "libp2p", "libp2p.transport", "libp2p.network", "libp2p.protocol_muxer"]:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
        print("Debug logging enabled via \"debug\" environment variable", file=sys.stderr)
    else:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("libp2p.ping_test").setLevel(logging.INFO)
        for logger_name in ["multiaddr", "multiaddr.transforms", "multiaddr.codecs", "libp2p", "libp2p.transport"]:
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
        self.redis_client: Optional[redis.Redis] = None
        self.ping_received = False

    def setup_redis(self) -> None:
        """Set up Redis connection."""
        self.redis_client = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            decode_responses=True
        )
        self.redis_client.ping()
        print(f"Connected to Redis at {self.redis_host}:{self.redis_port}", file=sys.stderr)

    def validate_configuration(self) -> None:
        """Validate configuration parameters."""
        valid_transports = ["tcp", "ws", "quic-v1"]
        valid_security = ["noise", "plaintext"]
        valid_muxers = ["mplex", "yamux"]
        
        if self.transport not in valid_transports:
            msg = f"Unsupported transport: {self.transport}. Supported: {valid_transports}"
            raise ValueError(msg)
        if self.security not in valid_security:
            msg = f"Unsupported security: {self.security}. Supported: {valid_security}"
            raise ValueError(msg)
        if self.muxer not in valid_muxers:
            msg = f"Unsupported muxer: {self.muxer}. Supported: {valid_muxers}"
            raise ValueError(msg)

    def create_security_options(self):
        """Create security options based on configuration."""
        # Create key pair for libp2p identity
        key_pair = create_new_key_pair()
        
        if self.security == "noise":
            # Create X25519 key pair for Noise
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
            msg = f"Unsupported security: {self.security}"
            raise ValueError(msg)

    def create_muxer_options(self):
        """Create muxer options based on configuration."""
        if self.muxer == "yamux":
            return create_yamux_muxer_option()
        elif self.muxer == "mplex":
            return create_mplex_muxer_option()
        else:
            msg = f"Unsupported muxer: {self.muxer}"
            raise ValueError(msg)

    def _get_ip_value(self, addr) -> Optional[str]:
        """Extract IP value from multiaddr (IPv4 or IPv6)."""
        return addr.value_for_protocol("ip4") or addr.value_for_protocol("ip6")
    
    def _get_protocol_names(self, addr) -> list:
        """Get protocol names from multiaddr."""
        return [p.name for p in addr.protocols()]
    
    def _build_quic_addr(self, ip_value: str, port: int) -> multiaddr.Multiaddr:
        """Build QUIC address from IP and port."""
        is_ipv6 = ":" in ip_value
        base = multiaddr.Multiaddr(f"/ip6/{ip_value}/udp/{port}" if is_ipv6 else f"/ip4/{ip_value}/udp/{port}")
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
                                quic_addr = quic_addr.encapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
                        quic_addrs.append(quic_addr)
                except Exception as e:
                    print(f"Error converting address {addr} to QUIC: {e}", file=sys.stderr)
            return quic_addrs if quic_addrs else [self._build_quic_addr("0.0.0.0", port)]
        
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
                                addr = addr.decapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
                        ws_addr = addr.encapsulate(multiaddr.Multiaddr("/ws"))
                        if p2p_value:
                            ws_addr = ws_addr.encapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
                        ws_addrs.append(ws_addr)
                except Exception as e:
                    print(f"Error converting address {addr} to WebSocket: {e}", file=sys.stderr)
            return ws_addrs if ws_addrs else [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/ws")]
        
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
            # Only process one ping request to avoid excessive pong responses
            payload = await stream.read(PING_LENGTH)
            if payload is not None:
                peer_id = self._get_peer_id(stream)
                print(f"received ping from {peer_id}", file=sys.stderr)
                await stream.write(payload)
                print(f"responded with pong to {peer_id}", file=sys.stderr)
                self.ping_received = True
        except Exception as e:
            print(f"Error in ping handler: {e}", file=sys.stderr)
            await stream.reset()
    
    def log_protocols(self) -> None:
        """Log registered protocols for debugging."""
        try:
            protocols = self.host.get_mux().get_protocols()
            print(f"Registered protocols: {[str(p) for p in protocols if p is not None]}", file=sys.stderr)
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
            elif self.transport == "tcp" and not any(p in protocols for p in ["ws", "wss", "quic-v1"]):
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
                    addr_parts.append(f"/{p.name}/{p.value}" if p.value else f"/{p.name}")
            
            return str(multiaddr.Multiaddr("".join(addr_parts)))
        except Exception as e:
            print(f"Warning: Failed to replace IP using multiaddr API: {e}, using string replacement", file=sys.stderr)
            addr_str = str(addr)
            for old_ip in ["/ip4/0.0.0.0/", "/ip4/127.0.0.1/"]:
                if old_ip in addr_str:
                    return addr_str.replace(old_ip, f"/ip4/{actual_ip}/")
            return addr_str
    
    def _get_publishable_address(self, addresses: list) -> str:
        """Get the best address to publish, preferring non-loopback."""
        filtered = self._filter_addresses_by_transport(addresses)
        if not filtered:
            print(f"Warning: No addresses matched transport {self.transport}, using all addresses", file=sys.stderr)
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
        
        security_options, key_pair = self.create_security_options()
        muxer_options = self.create_muxer_options()
        listen_addrs = self.create_listen_addresses(0)
        
        # Use get_available_interfaces() for proper address handling (current best practice)
        port = 0  # Let OS assign a free port
        listen_addrs = get_available_interfaces(port, protocol="tcp")
        
        # Create host with proper configuration
        self.host = new_host(
            key_pair=key_pair,
            sec_opt=security_options,
            muxer_opt=muxer_options,
            listen_addrs=listen_addrs,
            enable_quic=(self.transport == "quic-v1")
        )
        self.host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)
        self.log_protocols()
        
        async with self.host.run(listen_addrs=listen_addrs):
            all_addrs = self.host.get_addrs()
            if not all_addrs:
                raise RuntimeError("No listen addresses available")
            
            actual_addr = self._get_publishable_address(all_addrs)
            print(f"Publishing address for transport {self.transport}: {actual_addr}", file=sys.stderr)
            self.redis_client.rpush("listenerAddr", actual_addr)
            print("Listener ready, waiting for dialer to connect...", file=sys.stderr)
            
            wait_timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
            check_interval = 0.5
            elapsed = 0
            
            while elapsed < wait_timeout:
                if self.ping_received:
                    print("Ping received and responded, listener exiting", file=sys.stderr)
                    return
                await trio.sleep(check_interval)
                elapsed += check_interval
            
            if not self.ping_received:
                print(f"Timeout: No ping received within {wait_timeout} seconds", file=sys.stderr)

            sys.exit(1)

    async def _connect_redis_with_retry(self, max_retries: int = 10, retry_delay: float = 1.0) -> None:
        """Connect to Redis with retry mechanism."""
        print("Connecting to Redis...", file=sys.stderr)
        for attempt in range(max_retries):
            try:
                self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)
                self.redis_client.ping()
                print(f"Successfully connected to Redis on attempt {attempt + 1}", file=sys.stderr)
                return
            except Exception as e:
                print(f"Redis connection attempt {attempt + 1} failed: {e}", file=sys.stderr)
                if attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...", file=sys.stderr)
                    await trio.sleep(retry_delay)
        msg = f"Failed to connect to Redis after {max_retries} attempts"
        raise RuntimeError(msg)
    
    def _debug_connection_state(self, network, peer_id) -> None:
        """Debug connection state (only if debug logging enabled)."""
        try:
            if hasattr(network, 'get_connections_to_peer'):
                connections = network.get_connections_to_peer(peer_id)
            elif hasattr(network, 'connections'):
                connections = [c for c in network.connections.values() if c.get_peer_id() == peer_id]
            else:
                connections = []
            print(f"[DEBUG] Found {len(connections)} connections to peer {peer_id}", file=sys.stderr)
            for i, conn in enumerate(connections):
                muxed = hasattr(conn, 'get_muxer')
                print(f"[DEBUG] Connection {i}: {type(conn).__name__}, muxed: {muxed}", file=sys.stderr)
                if muxed:
                    try:
                        print(f"[DEBUG] Connection {i} muxer: {type(conn.get_muxer()).__name__}", file=sys.stderr)
                    except Exception as e:
                        print(f"[DEBUG] Connection {i} muxer error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[DEBUG] Error checking connections: {e}", file=sys.stderr)
    
    async def _create_stream_with_retry(self, peer_id) -> INetStream:
        """Create ping stream with retry mechanism for connection readiness."""
        max_retries = 3
        retry_delay = 0.5
        
        print("Creating ping stream", file=sys.stderr)
        print(f"[DEBUG] About to create stream for protocol {PING_PROTOCOL_ID}", file=sys.stderr)
        
        for attempt in range(max_retries):
            try:
                stream = await self.host.new_stream(peer_id, [PING_PROTOCOL_ID])
                print("Ping stream created successfully", file=sys.stderr)
                return stream
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[DEBUG] Stream creation attempt {attempt + 1} failed: {e}, retrying...", file=sys.stderr)
                    await trio.sleep(retry_delay)
                else:
                    print(f"[DEBUG] Stream creation failed after {max_retries} attempts: {e}", file=sys.stderr)
                    raise
        raise RuntimeError("Failed to create ping stream after retries")
    
    async def run_dialer(self) -> None:
        """Run the dialer role."""
        print("Running as dialer", file=sys.stderr)
        
        try:
            self.validate_configuration()
            await self._connect_redis_with_retry()
            
            # Get the listener's address from Redis
            print("Waiting for listener address from Redis...", file=sys.stderr)
            redis_wait_timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
            result = self.redis_client.blpop("listenerAddr", timeout=redis_wait_timeout)
            if not result:
                msg = f"Timeout waiting for listener address after {redis_wait_timeout} seconds"
                raise RuntimeError(msg)
            
            listener_addr = result[1]
            print(f"Got listener address: {listener_addr}", file=sys.stderr)
            
            # Create security and muxer options
            sec_opt, key_pair = self.create_security_options()
            muxer_opt = self.create_muxer_options()
            
            # WS dialer workaround: need listen addresses to register transport (py-libp2p limitation)
            dialer_listen_addrs = self.create_listen_addresses(0) if self.transport == "ws" else None
            if dialer_listen_addrs:
                print(f"Registering WS transport for dialer with addresses: {[str(addr) for addr in dialer_listen_addrs]}", file=sys.stderr)
            
            # Create host with proper configuration
            host_kwargs = {
                "key_pair": key_pair,
                "sec_opt": sec_opt,
                "muxer_opt": muxer_opt,
                "enable_quic": (self.transport == "quic-v1")
            }
            if dialer_listen_addrs:
                host_kwargs["listen_addrs"] = dialer_listen_addrs
            self.host = new_host(**host_kwargs)
            
            # Start the host
            async with self.host.run(listen_addrs=dialer_listen_addrs or []):
                # Record handshake start time
                handshake_start = time.time()
                
                # Parse the multiaddr and connect
                maddr = multiaddr.Multiaddr(listener_addr)
                info = info_from_p2p_addr(maddr)
                
                print(f"Connecting to {listener_addr}", file=sys.stderr)
                await self.host.connect(info)
                print("Connected successfully", file=sys.stderr)
                
                self._debug_connection_state(self.host.get_network(), info.peer_id)
                
                # Brief delay to ensure connection is fully ready for stream creation
                # This handles timing issues that can occur with some implementations
                await trio.sleep(0.1)
                
                # Retry stream creation to handle cases where connection needs more time
                stream = await self._create_stream_with_retry(info.peer_id)
                
                # Perform ping and measure RTT
                print("Performing ping test", file=sys.stderr)
                ping_rtt = await self.send_ping(stream)
                print(f"Ping test completed, RTT: {ping_rtt}ms", file=sys.stderr)
                
                # Calculate handshake plus one RTT
                handshake_plus_one_rtt = (time.time() - handshake_start) * 1000
                
                # Output results in JSON format
                result = {
                    "handshakePlusOneRTTMillis": handshake_plus_one_rtt,
                    "pingRTTMilllis": ping_rtt
                }
                print(f"Outputting results: {result}", file=sys.stderr)
                print(json.dumps(result))
                
                # Close stream
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
            
            # Run the appropriate role
            if self.is_dialer:
                await self.run_dialer()
            else:
                await self.run_listener()
                
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            # Cleanup
            if self.redis_client:
                self.redis_client.close()

    def get_container_ip(self) -> str:
        """Get container IP address for Docker networking."""
        import socket
        import subprocess
        try:
            # Try hostname -I first (works in most Docker containers)
            result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split()[0]
        except Exception:
            pass
        
        try:
            # Fallback: Connect to a remote address to determin local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            # Fallback to a reasonable default
            return "172.17.0.1"


async def main():
    """Main entry point."""
    # Configure logging to reduce debug output
    configure_logging()
    ping_test = PingTest()
    await ping_test.run()

if __name__ == "__main__":
    trio.run(main)
