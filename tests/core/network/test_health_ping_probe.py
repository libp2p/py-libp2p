"""Integration tests for per-connection ping probes."""

from typing import cast

import pytest

from libp2p.network.config import ConnectionConfig
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.health.ping_probe import ping_connection
from libp2p.network.swarm import Swarm
from tests.utils.factories import host_pair_factory


@pytest.mark.trio
async def test_ping_connection_real_hosts() -> None:
    """Ping probe returns RTT over a live TCP connection."""
    async with host_pair_factory() as (host_a, host_b):
        peer_b = host_b.get_id()
        conn = cast(
            SwarmConn,
            host_a.get_network().get_connections(peer_b)[0],
        )

        result = await ping_connection(conn, ping_timeout=5.0, negotiate_timeout=10)

        assert result.success is True
        assert result.protocol_supported is True
        assert result.rtt_ms >= 0


@pytest.mark.trio
async def test_ping_connection_records_peerstore_latency() -> None:
    """Monitor records successful ping RTT into peerstore LatencyEWMA."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_warmup_window=0.0,
        record_ping_latency_in_peerstore=True,
    )
    async with host_pair_factory(connection_config=config) as (host_a, host_b):
        peer_b = host_b.get_id()
        swarm = cast(Swarm, host_a.get_network())
        conn = cast(SwarmConn, swarm.get_connections(peer_b)[0])

        swarm.initialize_connection_health(peer_b, conn)
        monitor = swarm._health_monitor
        assert monitor is not None

        await monitor._check_connection_health(peer_b, conn)

        latency = swarm.peerstore.latency_EWMA(peer_b)
        assert latency > 0
