"""Real-network integration tests for connection health monitoring."""

from typing import Any, cast

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.host.basic_host import BasicHost
from libp2p.network.config import ConnectionConfig
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.tools.anyio_service import background_trio_service
from libp2p.tools.utils import connect
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)
from tests.utils.factories import SwarmFactory


def _is_loopback_only() -> bool:
    addrs = get_available_interfaces(0, "tcp")
    if not addrs:
        return True
    return all("/ip4/127." in str(addr) or "/ip6/::1" in str(addr) for addr in addrs)


def _health_config() -> ConnectionConfig:
    return ConnectionConfig(
        enable_health_monitoring=True,
        health_initial_delay=0.0,
        health_warmup_window=0.0,
        health_check_interval=1.0,
        ping_timeout=5.0,
        skip_ping_when_streams_open=False,
        min_connections_per_peer=1,
        unhealthy_grace_period=1,
    )


@pytest.mark.trio
async def test_health_monitor_updates_rtt_on_real_network() -> None:
    """Health monitor records ping RTT over a non-loopback path when available."""
    if _is_loopback_only():
        pytest.skip("No non-loopback interfaces available for real-network test")

    bind_addr = get_optimal_binding_address(0, "tcp")
    bind_str = str(bind_addr)
    assert "/ip4/127." not in bind_str and "/ip6/::1" not in bind_str

    config = _health_config()
    swarm_factory = cast(Any, SwarmFactory)
    swarm_a = swarm_factory(connection_config=config)
    swarm_b = swarm_factory(connection_config=config)
    host_a = BasicHost(swarm_a)
    host_b = BasicHost(swarm_b)

    async with background_trio_service(swarm_a):
        async with background_trio_service(swarm_b):
            await swarm_a.listen(bind_addr)
            await swarm_b.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            await connect(host_a, host_b)

            peer_a = host_a.get_id()
            conn = cast(SwarmConn, swarm_b.get_connections(peer_a)[0])
            swarm_b.initialize_connection_health(peer_a, conn)

            monitor = swarm_b._health_monitor
            assert monitor is not None
            await monitor._check_connection_health(peer_a, conn)

            summary = host_b.get_connection_health(peer_a)
            assert summary["average_latency_ms"] >= 0
            assert summary["average_health_score"] > 0


@pytest.mark.trio
async def test_health_monitor_detects_failed_ping_on_real_network() -> None:
    """A closed connection yields failed ping metrics on the next probe."""
    if _is_loopback_only():
        pytest.skip("No non-loopback interfaces available for real-network test")

    config = _health_config()
    bind_addr = get_optimal_binding_address(0, "tcp")
    swarm_factory = cast(Any, SwarmFactory)
    swarm_a = swarm_factory(connection_config=config)
    swarm_b = swarm_factory(connection_config=config)
    host_a = BasicHost(swarm_a)
    host_b = BasicHost(swarm_b)

    async with background_trio_service(swarm_a):
        async with background_trio_service(swarm_b):
            await swarm_a.listen(bind_addr)
            await swarm_b.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            await connect(host_a, host_b)

            peer_a = host_a.get_id()
            conn = cast(SwarmConn, swarm_b.get_connections(peer_a)[0])
            swarm_b.initialize_connection_health(peer_a, conn)

            monitor = swarm_b._health_monitor
            assert monitor is not None

            await monitor._check_connection_health(peer_a, conn)
            health = swarm_b.health_data[peer_a][conn]
            assert health.ping_success_rate > 0.5

            await conn.close()
            await trio.sleep(0.05)

            result = await monitor._ping_connection(conn)
            assert result.success is False
            health.update_ping_metrics(0.0, False)
            assert health.ping_success_rate < 1.0
