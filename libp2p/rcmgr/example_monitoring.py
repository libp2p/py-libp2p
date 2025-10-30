"""
Example to demonstrate the monitoring capabilities of the py-libp2p Resource Manager
"""

import random
import time

from libp2p.rcmgr import Direction
from libp2p.rcmgr.manager import ResourceLimits, ResourceManager
from libp2p.rcmgr.monitoring import Monitor


def main() -> None:
    """Demonstrate resource manager with Prometheus monitoring."""
    limits = ResourceLimits(
        max_connections=10,
        max_streams=20,
        max_memory_mb=5 * 1024 * 1024,
    )

    monitor = Monitor(
        enable_prometheus=True,
        prometheus_port=8000,
        enable_connection_tracking=True,
        enable_protocol_metrics=True,
    )

    rcmgr = ResourceManager(
        limits=limits,
        enable_prometheus=True,
        prometheus_port=8000,
        enable_metrics=True,
    )

    print(" Resource Manager initialized")

    connection_count = 0
    blocked_connections = 0
    stream_count = 0
    memory_used = 0
    fd_count = 0

    peer_connections: dict[str, int] = {}
    peer_streams: dict[str, int] = {}
    peer_memory: dict[str, int] = {}

    for iteration in range(100):
        print(f"--- Iteration {iteration + 1} ---")

        peer_id = f"peer_{random.randint(1000, 9999)}"

        if rcmgr.acquire_connection(peer_id):
            old_count = peer_connections.get(peer_id, 0)
            connection_count += 1
            peer_connections[peer_id] = peer_connections.get(peer_id, 0) + 1
            fd_count += 1

            print(f"Connection acquired for {peer_id} (total: {connection_count})")

            # Record in monitoring system
            monitor.record_connection_establishment(
                connection_id=f"conn_{connection_count}",
                peer_id=peer_id,
                protocol="tcp",
                direction="inbound",
            )

            # Record peer-level connection change for histogram metrics
            monitor.record_peer_resource_change(
                peer_id=peer_id,
                resource_type="connection",
                direction="inbound",
                old_value=old_count,
                new_value=peer_connections[peer_id],
            )

        else:
            blocked_connections += 1
            print(f"Connection blocked for {peer_id} (blocked: {blocked_connections})")

            # Record blocked resource
            monitor.record_blocked_resource(
                resource_type="connection",
                direction="inbound",
                scope="system",
            )

        # Simulate stream usage
        if connection_count > 0:
            old_stream_count = peer_streams.get(peer_id, 0)
            success = rcmgr.acquire_stream(peer_id, Direction.INBOUND)
            if success:
                stream_count += 1
                peer_streams[peer_id] = peer_streams.get(peer_id, 0) + 1
                print(f" Stream acquired for {peer_id} (total streams: {stream_count})")

                # Record peer-level stream change for histogram metrics
                monitor.record_peer_resource_change(
                    peer_id=peer_id,
                    resource_type="stream",
                    direction="inbound",
                    old_value=old_stream_count,
                    new_value=peer_streams[peer_id],
                )
            else:
                print(f"Stream blocked for {peer_id}")
                monitor.record_blocked_resource(
                    resource_type="stream",
                    direction="inbound",
                    scope="system",
                )

        # Simulate memory usage
        memory_size = random.randint(100000, 500000)  # 100KB - 500KB
        old_peer_memory = peer_memory.get(peer_id, 0)
        if rcmgr.acquire_memory(memory_size):
            memory_used += memory_size
            peer_memory[peer_id] = peer_memory.get(peer_id, 0) + memory_size

            # Record peer-level memory change for histogram metrics
            monitor.record_peer_resource_change(
                peer_id=peer_id,
                resource_type="memory",
                direction="",
                old_value=old_peer_memory,
                new_value=peer_memory[peer_id],
            )
        else:
            print(f"Memory blocked: {memory_size / 1024:.1f}KB")
            monitor.record_blocked_resource(
                resource_type="memory",
                direction="",
                scope="system",
            )

        # Update system-level resource usage metrics for Prometheus
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

        # Simulate file descriptor usage
        monitor.record_resource_usage(
            resource_type="fd",
            current_value=fd_count,
            limit_value=1000,  # Simulate FD limit
            labels={"scope": "system"},
        )

        # Show current metrics summary
        if rcmgr.metrics:
            summary = rcmgr.metrics.get_summary()
            print(
                f"Current: {summary['connections']['total']} conns, "
                f"{summary['streams']['total']} streams, "
                f"{summary['memory']['current']} bytes memory"
            )
            print(
                f"Blocked: {summary['blocks']['connections']} conns, "
                f"{summary['blocks']['streams']} streams, "
                f"{summary['blocks']['memory']} memory"
            )

        # Record resource usage metrics
        if rcmgr.metrics:
            summary = rcmgr.metrics.get_summary()
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

        print()
        time.sleep(1)

        if iteration % 10 == 9:
            print("Current Prometheus metrics sample:")
            if monitor.prometheus_exporter:
                metrics_text = monitor.get_prometheus_metrics()
                if metrics_text:
                    # Show just a few key metrics
                    for line in metrics_text.split("\n"):
                        if (
                            "libp2p_rcmgr_connections" in line
                            or "libp2p_rcmgr_blocked_resources" in line
                        ):
                            if not line.startswith("#"):
                                print(f"  {line}")
            print()

    print(f" {connection_count} active connections, {blocked_connections} blocked")

    time.sleep(300)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDemo stopped by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
