"""
Monitoring demo: exposes py-libp2p ResourceManager metrics at a configurable port
(default 8000) and emits sample activity to visualize in Prometheus/Grafana.
Production-ready improvements:
- Graceful shutdown on SIGINT/SIGTERM
- CLI flags for duration/iterations and log level
- Robust port selection and health logging
"""

from argparse import ArgumentParser
import logging
import os
import random
import signal
import socket
import sys
import threading
import time

from libp2p.rcmgr import Direction
from libp2p.rcmgr.manager import ResourceLimits, ResourceManager
from libp2p.rcmgr.monitoring import Monitor


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int) -> int:
    if _is_port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 101):
        if _is_port_free(p):
            return p
    return preferred  # fallback


def _setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("DEMO_EXPORTER_PORT", 8000)),
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Run duration in seconds (0 = unlimited)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Max iterations to execute (0 = unlimited)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.getenv("DEMO_LOG_LEVEL", "INFO"),
    )
    args = parser.parse_args()

    _setup_logging(args.log_level)

    port = _pick_port(args.port)

    limits = ResourceLimits(
        max_connections=10,
        max_streams=20,
        max_memory_mb=32,
    )

    monitor = Monitor(
        enable_prometheus=True,
        prometheus_port=port,
        enable_connection_tracking=True,
        enable_protocol_metrics=True,
    )

    rcmgr = ResourceManager(
        limits=limits,
        enable_prometheus=True,
        prometheus_port=port,
        enable_metrics=True,
    )

    logging.info("Resource Manager initialized on port %s", port)

    connection_count = 0
    blocked_connections = 0
    stream_count = 0
    memory_used = 0
    fd_count = 0

    peer_connections: dict[str, int] = {}
    peer_streams: dict[str, int] = {}
    peer_memory: dict[str, int] = {}

    stop_event = threading.Event()

    def _handle_signal(signum: int, _: object) -> None:
        logging.info("Received signal %s; shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    start_ts = time.monotonic()
    iteration = 0

    while not stop_event.is_set():
        if args.iterations and iteration >= args.iterations:
            break
        if args.duration and (time.monotonic() - start_ts) >= args.duration:
            break
        logging.debug("--- Iteration %s ---", iteration + 1)

        peer_id = f"peer_{random.randint(1000, 9999)}"

        if rcmgr.acquire_connection(peer_id):
            old_count = peer_connections.get(peer_id, 0)
            connection_count += 1
            peer_connections[peer_id] = peer_connections.get(peer_id, 0) + 1
            fd_count += 1

            logging.debug(
                "Connection acquired for %s (total: %s)",
                peer_id,
                connection_count,
            )

            monitor.record_connection_establishment(
                connection_id=f"conn_{connection_count}",
                peer_id=peer_id,
                protocol="tcp",
                direction="inbound",
            )

            monitor.record_peer_resource_change(
                peer_id=peer_id,
                resource_type="connection",
                direction="inbound",
                old_value=old_count,
                new_value=peer_connections[peer_id],
            )
        else:
            blocked_connections += 1
            logging.debug(
                "Connection blocked for %s (blocked: %s)",
                peer_id,
                blocked_connections,
            )
            monitor.record_blocked_resource(
                resource_type="connection",
                direction="inbound",
                scope="system",
            )

        if connection_count > 0:
            old_stream_count = peer_streams.get(peer_id, 0)
            success = rcmgr.acquire_stream(peer_id, Direction.INBOUND)
            if success:
                stream_count += 1
                peer_streams[peer_id] = peer_streams.get(peer_id, 0) + 1
                logging.debug(
                    "Stream acquired for %s (total streams: %s)",
                    peer_id,
                    stream_count,
                )

                monitor.record_peer_resource_change(
                    peer_id=peer_id,
                    resource_type="stream",
                    direction="inbound",
                    old_value=old_stream_count,
                    new_value=peer_streams[peer_id],
                )
            else:
                logging.debug("Stream blocked for %s", peer_id)
                monitor.record_blocked_resource(
                    resource_type="stream",
                    direction="inbound",
                    scope="system",
                )

        memory_size = random.randint(100_000, 500_000)  # 100KB - 500KB
        old_peer_memory = peer_memory.get(peer_id, 0)
        if rcmgr.acquire_memory(memory_size):
            memory_used += memory_size
            peer_memory[peer_id] = peer_memory.get(peer_id, 0) + memory_size

            monitor.record_peer_resource_change(
                peer_id=peer_id,
                resource_type="memory",
                direction="",
                old_value=old_peer_memory,
                new_value=peer_memory[peer_id],
            )
        else:
            logging.debug("Memory blocked: %.1fKB", memory_size / 1024)
            monitor.record_blocked_resource(
                resource_type="memory",
                direction="",
                scope="system",
            )

        monitor.record_resource_usage(
            resource_type="connection",
            current_value=connection_count,
            limit_value=limits.max_connections,
            labels={"scope": "system"},
        )
        monitor.record_resource_usage(
            resource_type="stream",
            current_value=stream_count,
            limit_value=limits.max_streams,
            labels={"scope": "system"},
        )
        monitor.record_resource_usage(
            resource_type="memory",
            current_value=memory_used,
            limit_value=limits.max_memory_bytes,
            labels={"scope": "system"},
        )
        monitor.record_resource_usage(
            resource_type="fd",
            current_value=fd_count,
            limit_value=1000,
            labels={"scope": "system"},
        )

        if rcmgr.metrics:
            summary = rcmgr.metrics.get_summary()
            logging.info(
                "Current: %s conns, %s streams, %s bytes memory",
                summary["connections"]["total"],
                summary["streams"]["total"],
                summary["memory"]["current"],
            )
            logging.info(
                "Blocked: %s conns, %s streams, %s memory",
                summary["blocks"]["connections"],
                summary["blocks"]["streams"],
                summary["blocks"]["memory"],
            )

            monitor.record_resource_usage(
                resource_type="connection",
                current_value=summary["connections"]["total"],
                limit_value=limits.max_connections,
                labels={"scope": "system"},
            )
            monitor.record_resource_usage(
                resource_type="memory",
                current_value=summary["memory"]["current"],
                limit_value=limits.max_memory_bytes,
                labels={"scope": "system"},
            )
            if monitor.prometheus_exporter:
                monitor.prometheus_exporter.update_from_metrics(rcmgr.metrics)

        iteration += 1
        time.sleep(1)

    logging.info(
        "%s active connections, %s blocked",
        connection_count,
        blocked_connections,
    )

    # Keep exporter alive for manual inspection if unlimited duration/iterations
    # and not signaled
    if not args.duration and not args.iterations and not stop_event.is_set():
        logging.info("Exporter running on port %s. Press Ctrl+C to stop.", port)
        try:
            while not stop_event.wait(1):
                pass
        except KeyboardInterrupt:
            stop_event.set()
    sys.exit(0)


if __name__ == "__main__":
    main()
