"""Integration tests for per-connection ping probes."""

from collections.abc import Callable
from typing import cast

import pytest
import trio

from libp2p.network.config import ConnectionConfig
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.health.ping_probe import ping_connection
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from tests.utils.factories import host_pair_factory


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.01,
) -> None:
    """Poll until ``predicate`` is true (event-driven readiness)."""
    deadline = trio.current_time() + timeout
    while trio.current_time() < deadline:
        if predicate():
            return
        await trio.sleep(poll_interval)
    raise TimeoutError(f"Condition not met within {timeout}s")


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
    """
    Monitor records a successful ping RTT into peerstore LatencyEWMA.

    Waits for health metrics and ``record_latency`` rather than asserting
    ``EWMA > 0``: on fast CI, integer-ms RTT can be ``0``, which is still a
    valid recorded sample.
    """
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_warmup_window=0.0,
        # Keep the background monitor from racing this explicit check.
        health_initial_delay=3600.0,
        record_ping_latency_in_peerstore=True,
    )
    async with host_pair_factory(connection_config=config) as (host_a, host_b):
        peer_b = host_b.get_id()
        swarm = cast(Swarm, host_a.get_network())
        conn = cast(SwarmConn, swarm.get_connections(peer_b)[0])

        swarm.initialize_connection_health(peer_b, conn)
        monitor = swarm._health_monitor
        assert monitor is not None

        health = swarm.health_data[peer_b][conn]
        initial_last_ping = health.last_ping

        recorded: list[tuple[ID, float]] = []
        original_record = swarm.peerstore.record_latency

        def spy_record_latency(peer_id: ID, rtt: float) -> None:
            recorded.append((peer_id, rtt))
            original_record(peer_id, rtt)

        swarm.peerstore.record_latency = spy_record_latency  # type: ignore[method-assign]

        await monitor._check_connection_health(peer_b, conn)

        await _wait_until(
            lambda: health.last_ping > initial_last_ping
            and health.ping_success_rate > 0
        )
        await _wait_until(lambda: len(recorded) > 0)

        peer_id, rtt_seconds = recorded[0]
        assert peer_id == peer_b
        assert rtt_seconds >= 0.0
        # First sample seeds EWMA (may be 0.0s when RTT rounds down to 0 ms).
        assert swarm.peerstore.latency_EWMA(peer_b) == rtt_seconds
