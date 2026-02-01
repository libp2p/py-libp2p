#!/usr/bin/env python3
"""
Python libp2p perf test implementation for test-plans perf.

Follows docs/write-a-perf-test-app.md:
- Reads configuration from environment variables
- Connects to Redis for coordination (SET/GET to match Rust)
- Implements both listener and dialer roles
- Measures upload/download throughput and latency
- Outputs results in YAML format to stdout (stderr for logs)
"""

from datetime import datetime, timedelta, timezone
import ipaddress
import logging
import os
import ssl
import sys
import tempfile
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import multiaddr
import redis
import trio

try:
    ExceptionGroup  # noqa: B018
except NameError:
    from exceptiongroup import ExceptionGroup  # type: ignore[no-redef]

from libp2p import create_mplex_muxer_option, create_yamux_muxer_option, new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.security.tls.transport import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)
from libp2p.utils.address_validation import get_available_interfaces
from libp2p.perf import PerfService, PROTOCOL_NAME

MAX_TEST_TIMEOUT = 300
logger = logging.getLogger("libp2p.perf_test")


def configure_logging() -> None:
    """Configure logging based on DEBUG environment variable."""
    debug_value = os.getenv("DEBUG") or "false"
    debug_enabled = debug_value.upper() in ["DEBUG", "1", "TRUE", "YES"]

    for logger_name in ["multiaddr", "multiaddr.transforms", "multiaddr.codecs", "multiaddr.codecs.cid"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if debug_enabled:
        for name in ["", "libp2p.perf_test", "libp2p", "libp2p.perf"]:
            logging.getLogger(name).setLevel(logging.DEBUG)
        print("Debug logging enabled", file=sys.stderr)
    else:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("libp2p.perf_test").setLevel(logging.INFO)
        for name in ["libp2p", "libp2p.transport"]:
            logging.getLogger(name).setLevel(logging.WARNING)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation percentile."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_values[0]
    index = (p / 100.0) * (n - 1)
    lower = int(index)
    upper = min(lower + 1, n - 1)
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _is_connection_closed_error(exc: BaseException) -> bool:
    """True if this is the expected 'Connection closed' from swarm/mplex on shutdown."""
    msg = str(exc).lower()
    if "connection closed" in msg:
        return True
    if isinstance(exc, ExceptionGroup):
        return all(_is_connection_closed_error(e) for e in exc.exceptions)
    return False


def _compute_stats(samples: list[float], is_latency: bool = False) -> dict[str, Any]:
    """Compute min, q1, median, q3, max, outliers, samples (IQR-based)."""
    if not samples:
        return {
            "min": 0.0, "q1": 0.0, "median": 0.0, "q3": 0.0, "max": 0.0,
            "outliers": [], "samples": [],
        }
    sorted_vals = sorted(samples)
    n = len(sorted_vals)
    q1 = _percentile(sorted_vals, 25.0)
    median = _percentile(sorted_vals, 50.0)
    q3 = _percentile(sorted_vals, 75.0)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    outliers = [v for v in sorted_vals if v < lower_fence or v > upper_fence]
    non_outliers = [v for v in sorted_vals if lower_fence <= v <= upper_fence]
    if non_outliers:
        min_val, max_val = non_outliers[0], non_outliers[-1]
    else:
        min_val, max_val = sorted_vals[0], sorted_vals[-1]
    fmt = "{:.3f}" if is_latency else "{:.2f}"
    return {
        "min": min_val, "q1": q1, "median": median, "q3": q3, "max": max_val,
        "outliers": [float(fmt.format(x)) for x in outliers],
        "samples": [float(fmt.format(x)) for x in sorted_vals],
    }


class PerfTest:
    def __init__(self) -> None:
        self.transport = os.getenv("TRANSPORT")
        if not self.transport:
            raise ValueError("TRANSPORT environment variable is required")
        standalone = ["quic-v1"]
        self.muxer: str | None = None
        self.security: str | None = None
        if self.transport not in standalone:
            self.muxer = os.getenv("MUXER") or ""
            self.security = os.getenv("SECURE_CHANNEL") or ""
            if not self.muxer or not self.security:
                raise ValueError("MUXER and SECURE_CHANNEL required for non-standalone transport")
        else:
            self.muxer = os.getenv("MUXER")
            self.security = os.getenv("SECURE_CHANNEL")

        is_dialer_val = os.getenv("IS_DIALER")
        if is_dialer_val is None:
            raise ValueError("IS_DIALER environment variable is required")
        self.is_dialer = is_dialer_val == "true"

        self.ip = os.getenv("LISTENER_IP") or "0.0.0.0"
        self.redis_addr = os.getenv("REDIS_ADDR")
        if not self.redis_addr:
            raise ValueError("REDIS_ADDR environment variable is required")
        if ":" in self.redis_addr:
            self.redis_host, port = self.redis_addr.split(":", 1)
            self.redis_port = int(port)
        else:
            self.redis_host = self.redis_addr
            self.redis_port = 6379

        self.test_key = os.getenv("TEST_KEY")
        if not self.test_key:
            raise ValueError("TEST_KEY environment variable is required")

        self.upload_bytes = int(os.getenv("UPLOAD_BYTES") or "1073741824")
        self.download_bytes = int(os.getenv("DOWNLOAD_BYTES") or "1073741824")
        self.upload_iterations = int(os.getenv("UPLOAD_ITERATIONS") or "10")
        self.download_iterations = int(os.getenv("DOWNLOAD_ITERATIONS") or "10")
        self.latency_iterations = int(os.getenv("LATENCY_ITERATIONS") or "100")

        timeout_val = os.getenv("TEST_TIMEOUT_SECS") or "180"
        self.test_timeout_seconds = min(int(timeout_val), MAX_TEST_TIMEOUT)

        self.host: Any = None
        self.redis_client: redis.Redis[str] | None = None
        self.perf_service: PerfService | None = None

    def validate_configuration(self) -> None:
        valid_transports = ["tcp", "ws", "wss", "quic-v1"]
        valid_security = ["noise", "plaintext", "tls"]
        valid_muxers = ["mplex", "yamux"]
        standalone = ["quic-v1"]
        if self.transport not in valid_transports:
            raise ValueError(f"Unsupported transport: {self.transport}. Supported: {valid_transports}")
        if self.transport not in standalone:
            if self.security not in valid_security:
                raise ValueError(f"Unsupported security: {self.security}. Supported: {valid_security}")
            if self.muxer not in valid_muxers:
                raise ValueError(f"Unsupported muxer: {self.muxer}. Supported: {valid_muxers}")

    def create_security_options(self) -> tuple[dict[TProtocol, Any], Any]:
        standalone = ["quic-v1"]
        if self.transport in standalone:
            return {}, create_new_key_pair()
        key_pair = create_new_key_pair()
        if self.security == "noise":
            noise_kp = create_new_x25519_key_pair()
            noise_transport = NoiseTransport(
                libp2p_keypair=key_pair,
                noise_privkey=noise_kp.private_key,
                early_data=None,
            )
            return {NOISE_PROTOCOL_ID: noise_transport}, key_pair
        if self.security == "tls":
            tls_transport = TLSTransport(
                libp2p_keypair=key_pair,
                early_data=None,
                muxers=None,
            )
            return {TLS_PROTOCOL_ID: tls_transport}, key_pair
        if self.security == "plaintext":
            pt = InsecureTransport(
                local_key_pair=key_pair,
                secure_bytes_provider=None,
                peerstore=None,
            )
            return {PLAINTEXT_PROTOCOL_ID: pt}, key_pair
        raise ValueError(f"Unsupported security: {self.security}")

    def create_muxer_options(self) -> Any:
        if self.transport in ["quic-v1"]:
            return None
        if self.muxer == "yamux":
            return create_yamux_muxer_option()
        if self.muxer == "mplex":
            return create_mplex_muxer_option()
        raise ValueError(f"Unsupported muxer: {self.muxer}")

    def create_tls_client_config(self) -> ssl.SSLContext | None:
        if self.transport == "wss":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    def create_tls_server_config(self) -> ssl.SSLContext | None:
        if self.transport == "wss":
            try:
                pk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                subject = issuer = x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, "libp2p.local"),
                ])
                cert = (
                    x509.CertificateBuilder()
                    .subject_name(subject)
                    .issuer_name(issuer)
                    .public_key(pk.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(datetime.now(timezone.utc))
                    .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
                    .sign(pk, hashes.SHA256())
                )
                ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with tempfile.NamedTemporaryFile(mode="wb", delete=False) as cf, \
                     tempfile.NamedTemporaryFile(mode="wb", delete=False) as kf:
                    cf.write(cert.public_bytes(serialization.Encoding.PEM))
                    kf.write(pk.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    ))
                    ctx.load_cert_chain(cf.name, kf.name)
                    try:
                        os.unlink(cf.name)
                        os.unlink(kf.name)
                    except Exception:
                        pass
                return ctx
            except Exception as e:
                print(f"WARNING: TLS server config failed: {e}", file=sys.stderr)
                return None
        return None

    def _get_ip_value(self, addr: multiaddr.Multiaddr) -> str | None:
        return addr.value_for_protocol("ip4") or addr.value_for_protocol("ip6")

    def _get_protocol_names(self, addr: multiaddr.Multiaddr) -> list[str]:
        return [p.name for p in addr.protocols()]

    def _extract_and_preserve_p2p(self, addr: multiaddr.Multiaddr) -> tuple[multiaddr.Multiaddr, str | None]:
        p2p_value = None
        if "p2p" in self._get_protocol_names(addr):
            p2p_value = addr.value_for_protocol("p2p")
            if p2p_value:
                addr = addr.decapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
        return addr, p2p_value

    def _encapsulate_with_p2p(self, addr: multiaddr.Multiaddr, p2p_value: str | None) -> multiaddr.Multiaddr:
        if p2p_value:
            return addr.encapsulate(multiaddr.Multiaddr(f"/p2p/{p2p_value}"))
        return addr

    def _build_quic_addr(self, ip_value: str, port: int) -> multiaddr.Multiaddr:
        if ":" in ip_value:
            base = multiaddr.Multiaddr(f"/ip6/{ip_value}/udp/{port}")
        else:
            base = multiaddr.Multiaddr(f"/ip4/{ip_value}/udp/{port}")
        return base.encapsulate(multiaddr.Multiaddr("/quic-v1"))

    def create_listen_addresses(self, port: int = 0) -> list[multiaddr.Multiaddr]:
        base_addrs = get_available_interfaces(port, protocol="tcp")
        if self.transport == "quic-v1":
            out = []
            for addr in base_addrs:
                ip_value = self._get_ip_value(addr)
                tcp_port = addr.value_for_protocol("tcp") or port
                if ip_value:
                    qa = self._build_quic_addr(ip_value, tcp_port)
                    _, p2p = self._extract_and_preserve_p2p(addr)
                    qa = self._encapsulate_with_p2p(qa, p2p)
                    out.append(qa)
            return out if out else [self._build_quic_addr("0.0.0.0", port)]
        if self.transport == "ws":
            out = []
            for addr in base_addrs:
                try:
                    names = self._get_protocol_names(addr)
                    if "ws" in names or "wss" in names:
                        out.append(addr)
                    else:
                        a, p2p = self._extract_and_preserve_p2p(addr)
                        wa = a.encapsulate(multiaddr.Multiaddr("/ws"))
                        out.append(self._encapsulate_with_p2p(wa, p2p))
                except Exception:
                    pass
            return out if out else [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/ws")]
        if self.transport == "wss":
            out = []
            for addr in base_addrs:
                try:
                    names = self._get_protocol_names(addr)
                    a, p2p = self._extract_and_preserve_p2p(addr)
                    if "wss" in names:
                        out.append(addr)
                    elif "ws" in names:
                        a_ = a.decapsulate(multiaddr.Multiaddr("/ws"))
                        wss = a_.encapsulate(multiaddr.Multiaddr("/wss"))
                        out.append(self._encapsulate_with_p2p(wss, p2p))
                    else:
                        wss = a.encapsulate(multiaddr.Multiaddr("/wss"))
                        out.append(self._encapsulate_with_p2p(wss, p2p))
                except Exception:
                    pass
            return out if out else [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/wss")]
        return base_addrs

    def _filter_addresses_by_transport(self, addresses: list[multiaddr.Multiaddr]) -> list[multiaddr.Multiaddr]:
        out = []
        for addr in addresses:
            names = self._get_protocol_names(addr)
            if self.transport == "ws" and ("ws" in names or "wss" in names):
                out.append(addr)
            elif self.transport == "wss" and "wss" in names:
                out.append(addr)
            elif self.transport == "quic-v1" and "quic-v1" in names:
                out.append(addr)
            elif self.transport == "tcp" and not any(p in names for p in ["ws", "wss", "quic-v1"]):
                out.append(addr)
        return out if out else addresses

    def get_container_ip(self) -> str:
        import socket
        import subprocess
        try:
            r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split()[0]
        except Exception:
            pass
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "172.17.0.1"

    def _replace_loopback_ip(self, addr: multiaddr.Multiaddr) -> str:
        ip_value = self._get_ip_value(addr)
        if ip_value not in ["127.0.0.1", "0.0.0.0", "::1", "::"]:
            return str(addr)
        actual = self.get_container_ip()
        names = self._get_protocol_names(addr)
        is_ipv6 = "ip6" in names
        parts = [f"/ip6/{actual}" if is_ipv6 else f"/ip4/{actual}"]
        found = False
        for p in addr.protocols():
            if p.name in ["ip4", "ip6"]:
                found = True
                continue
            if found:
                parts.append(f"/{p.name}/{p.value}" if p.value else f"/{p.name}")
        return str(multiaddr.Multiaddr("".join(parts)))

    def _get_publishable_address(self, addresses: list[multiaddr.Multiaddr]) -> str:
        filtered = self._filter_addresses_by_transport(addresses)
        if not filtered:
            filtered = addresses
        for addr in filtered:
            ip_value = self._get_ip_value(addr)
            if ip_value and ip_value not in ["127.0.0.1", "0.0.0.0", "::1", "::"]:
                return str(addr)
        return self._replace_loopback_ip(filtered[0])

    async def _connect_redis_with_retry(self, max_retries: int = 10, retry_delay: float = 1.0) -> None:
        print("Connecting to Redis...", file=sys.stderr)
        for attempt in range(max_retries):
            try:
                self.redis_client = redis.Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    decode_responses=True,
                )
                self.redis_client.ping()
                print(f"Connected to Redis on attempt {attempt + 1}", file=sys.stderr)
                return
            except Exception as e:
                print(f"Redis attempt {attempt + 1} failed: {e}", file=sys.stderr)
                if attempt < max_retries - 1:
                    await trio.sleep(retry_delay)
        raise RuntimeError(f"Failed to connect to Redis after {max_retries} attempts")

    async def run_listener(self) -> None:
        self.validate_configuration()
        await self._connect_redis_with_retry()

        sec_opt, key_pair = self.create_security_options()
        muxer_opt = self.create_muxer_options()
        listen_addrs = self.create_listen_addresses(0)
        tls_client = self.create_tls_client_config()
        tls_server = self.create_tls_server_config()

        self.host = new_host(
            key_pair=key_pair,
            sec_opt=sec_opt,
            muxer_opt=muxer_opt,
            listen_addrs=listen_addrs,
            enable_quic=(self.transport == "quic-v1"),
            tls_client_config=tls_client,
            tls_server_config=tls_server,
        )
        self.perf_service = PerfService(self.host)
        await self.perf_service.start()
        print(f"Perf service started (protocol {PROTOCOL_NAME})", file=sys.stderr)

        async with self.host.run(listen_addrs=listen_addrs):
            all_addrs = self.host.get_addrs()
            if not all_addrs:
                raise RuntimeError("No listen addresses available")
            actual_addr = self._get_publishable_address(all_addrs)
            print(f"Publishing address: {actual_addr}", file=sys.stderr)
            redis_key = f"{self.test_key}_listener_multiaddr"
            assert self.redis_client is not None
            self.redis_client.set(redis_key, actual_addr)
            print("Listener ready, waiting for dialer...", file=sys.stderr)
            await trio.sleep_forever()

    async def _wait_for_listener_addr(self) -> str:
        redis_key = f"{self.test_key}_listener_multiaddr"
        timeout = min(self.test_timeout_seconds, MAX_TEST_TIMEOUT)
        deadline = time.monotonic() + timeout
        assert self.redis_client is not None
        while time.monotonic() < deadline:
            addr = self.redis_client.get(redis_key)
            if addr:
                return addr
            await trio.sleep(0.5)
        raise RuntimeError(f"Timeout waiting for listener address (key {redis_key}) after {timeout}s")

    async def _one_measurement(
        self,
        send_bytes: int,
        recv_bytes: int,
    ) -> float:
        """Run one measure_performance call and return elapsed time in seconds."""
        assert self.host is not None
        assert self.perf_service is not None
        maddr = multiaddr.Multiaddr(self.listener_addr)
        start = time.monotonic()
        async for _ in self.perf_service.measure_performance(maddr, send_bytes, recv_bytes):
            pass
        return time.monotonic() - start

    async def run_dialer(self) -> None:
        self.validate_configuration()
        await self._connect_redis_with_retry()
        print("Waiting for listener address...", file=sys.stderr)
        self.listener_addr = await self._wait_for_listener_addr()
        print(f"Got listener address: {self.listener_addr}", file=sys.stderr)

        sec_opt, key_pair = self.create_security_options()
        muxer_opt = self.create_muxer_options()
        # Dialer needs listen_addrs for ws/wss so transport is registered; for quic/tcp pass [] (host.run still starts swarm/nursery)
        dialer_listen_addrs = self.create_listen_addresses(0) if self.transport in ["ws", "wss"] else None
        tls_client = self.create_tls_client_config()
        tls_server = None

        kw: dict[str, Any] = {
            "key_pair": key_pair,
            "sec_opt": sec_opt,
            "muxer_opt": muxer_opt,
            "enable_quic": (self.transport == "quic-v1"),
            "tls_client_config": tls_client,
            "tls_server_config": tls_server,
        }
        if dialer_listen_addrs:
            kw["listen_addrs"] = dialer_listen_addrs
        self.host = new_host(**kw)
        self.perf_service = PerfService(self.host)
        await self.perf_service.start()

        # Must run host inside host.run() so swarm/nursery are active (required for connect and QUIC)
        try:
            async with self.host.run(listen_addrs=dialer_listen_addrs or []):
                # Brief delay so listener is fully listening before we dial
                await trio.sleep(1.0)

                maddr = multiaddr.Multiaddr(self.listener_addr)
                info = info_from_p2p_addr(maddr)
                listener_peer_id = info.peer_id
                await self.host.connect(info)
                print("Connected to listener", file=sys.stderr)

                upload_samples: list[float] = []
                for i in range(self.upload_iterations):
                    elapsed = await self._one_measurement(self.upload_bytes, 0)
                    gbps = (self.upload_bytes * 8.0) / elapsed / 1e9 if elapsed > 0 else 0.0
                    upload_samples.append(gbps)
                    print(f"Upload iteration {i+1}/{self.upload_iterations}: {gbps:.2f} Gbps", file=sys.stderr)

                download_samples: list[float] = []
                for i in range(self.download_iterations):
                    elapsed = await self._one_measurement(0, self.download_bytes)
                    gbps = (self.download_bytes * 8.0) / elapsed / 1e9 if elapsed > 0 else 0.0
                    download_samples.append(gbps)
                    print(f"Download iteration {i+1}/{self.download_iterations}: {gbps:.2f} Gbps", file=sys.stderr)

                latency_samples: list[float] = []
                for i in range(self.latency_iterations):
                    elapsed = await self._one_measurement(1, 1)
                    latency_samples.append(elapsed * 1000.0)
                print("Latency iterations done", file=sys.stderr)

                u = _compute_stats(upload_samples, is_latency=False)
                d = _compute_stats(download_samples, is_latency=False)
                l = _compute_stats(latency_samples, is_latency=True)

                # YAML to stdout only (per write-a-perf-test-app.md)
                print("upload:")
                print(f"  iterations: {self.upload_iterations}")
                print(f"  min: {u['min']:.2f}")
                print(f"  q1: {u['q1']:.2f}")
                print(f"  median: {u['median']:.2f}")
                print(f"  q3: {u['q3']:.2f}")
                print(f"  max: {u['max']:.2f}")
                print(f"  outliers: {u['outliers']}")
                print(f"  samples: {u['samples']}")
                print("  unit: Gbps")
                print("download:")
                print(f"  iterations: {self.download_iterations}")
                print(f"  min: {d['min']:.2f}")
                print(f"  q1: {d['q1']:.2f}")
                print(f"  median: {d['median']:.2f}")
                print(f"  q3: {d['q3']:.2f}")
                print(f"  max: {d['max']:.2f}")
                print(f"  outliers: {d['outliers']}")
                print(f"  samples: {d['samples']}")
                print("  unit: Gbps")
                print("latency:")
                print(f"  iterations: {self.latency_iterations}")
                print(f"  min: {l['min']:.3f}")
                print(f"  q1: {l['q1']:.3f}")
                print(f"  median: {l['median']:.3f}")
                print(f"  q3: {l['q3']:.3f}")
                print(f"  max: {l['max']:.3f}")
                print(f"  outliers: {l['outliers']}")
                print(f"  samples: {l['samples']}")
                print("  unit: ms")

                # Graceful close: disconnect listener so it sees a clean close, then stop services
                try:
                    await self.host.disconnect(listener_peer_id)
                    await trio.sleep(0.5)
                except Exception as e:
                    logger.debug("Disconnect: %s", e)
                try:
                    await self.perf_service.stop()
                except Exception as e:
                    logger.debug("PerfService.stop: %s", e)
                if self.redis_client:
                    try:
                        self.redis_client.close()
                    except Exception:
                        pass
        except BaseException as e:
            # Swarm/mplex may raise "Connection closed" when we disconnect; treat as success
            if not _is_connection_closed_error(e):
                raise

    async def run(self) -> None:
        try:
            await self._connect_redis_with_retry()
            if self.is_dialer:
                await self.run_dialer()
            else:
                await self.run_listener()
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            if self.redis_client:
                self.redis_client.close()
            sys.exit(1)


async def main() -> None:
    configure_logging()
    test = PerfTest()
    await test.run()


if __name__ == "__main__":
    trio.run(main)
