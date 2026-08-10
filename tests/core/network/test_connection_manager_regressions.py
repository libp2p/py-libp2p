"""
Regression tests for connection manager bug fixes.

Each test class documents the bug it guards against (referenced by number in
the connection-manager analysis) so the commit history stays self-explanatory.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import ConnectionType
from libp2p.network.swarm import Swarm, SwarmException
from libp2p.tools.anyio_service import background_trio_service
from tests.utils.factories import SwarmFactory


async def _block_on_accept():
    """Muxed-conn accept stream that blocks forever (no new streams)."""
    await trio.sleep_forever()


def _established_mock_muxed_conn(peer_id) -> Mock:
    """Build a mock IMuxedConn that reports itself fully established."""
    muxed_conn = Mock()
    muxed_conn.peer_id = peer_id
    muxed_conn.is_closed = False
    muxed_conn.is_established = True
    muxed_conn.event_started = trio.Event()
    muxed_conn.event_started.set()
    muxed_conn._connected_event = trio.Event()
    muxed_conn._connected_event.set()
    muxed_conn.close = AsyncMock()
    muxed_conn.start = AsyncMock()
    muxed_conn.accept_stream = _block_on_accept
    muxed_conn.get_transport_addresses = Mock(return_value=[])
    muxed_conn.get_connection_type = Mock(return_value=ConnectionType.UNKNOWN)
    return muxed_conn


@pytest.mark.trio
class TestBug2OutboundMaxConnections:
    """Bug 2: ``max_connections`` was only enforced on inbound connections."""

    async def test_outbound_dial_respects_max_connections(self):
        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections = 1

        # Pretend we already have one live connection.
        fake_conn = Mock()
        fake_conn.is_closed = False
        swarm.connections[swarm.self_id] = [fake_conn]

        addr = Multiaddr("/ip4/127.0.0.1/tcp/9999")
        with pytest.raises(SwarmException, match="Maximum connections limit reached"):
            await swarm._dial_addr_single_attempt(addr, swarm.self_id)

    async def test_outbound_dial_allowed_below_limit(self):
        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections = 10
        # No live connections yet — the limit check must pass and the dial
        # must proceed (we mock the transport lookup to avoid real sockets).
        swarm.transport_manager.transport_for_dialing = Mock(return_value=None)

        addr = Multiaddr("/ip4/127.0.0.1/tcp/9999")
        with pytest.raises(SwarmException, match="No registered transport"):
            await swarm._dial_addr_single_attempt(addr, swarm.self_id)


@pytest.mark.trio
class TestBug3AddConnDedup:
    """Bug 3: add_conn dedup used to close the shared muxed connection."""

    async def test_add_conn_dedup_returns_existing_without_closing_shared_conn(
        self,
    ):
        swarm = SwarmFactory.build()
        muxed_conn = _established_mock_muxed_conn(swarm.self_id)

        async with background_trio_service(swarm):
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")
            # Adding the same muxed connection again must return the existing
            # SwarmConn and must NOT close the underlying muxed connection.
            conn2 = await swarm.add_conn(muxed_conn, direction="inbound")

        assert conn1 is conn2
        # The shared muxed connection must never have been closed by the dedup.
        muxed_conn.close.assert_not_awaited()
        # Only one SwarmConn is registered for the peer.
        assert len(swarm.connections[swarm.self_id]) == 1

    async def test_dedup_duplicate_wrapper_close_skips_shared_muxed_conn(self):
        """A duplicate wrapper marked shared must not close the muxed conn."""
        from libp2p.network.connection.swarm_connection import SwarmConn

        swarm = SwarmFactory.build()
        muxed_conn = _established_mock_muxed_conn(swarm.self_id)

        # Simulate the duplicate wrapper created during the add_conn race: it
        # shares the same muxed_conn and is marked _shared_muxed_conn.
        dup_wrapper = SwarmConn(muxed_conn, swarm)
        dup_wrapper._shared_muxed_conn = True
        await dup_wrapper.close()

        # Closing the duplicate must NOT close the muxed connection that the
        # surviving SwarmConn still uses.
        muxed_conn.close.assert_not_awaited()
        assert dup_wrapper.is_closed


@pytest.mark.trio
class TestBug8MaxConnectionsRegistration:
    """Bug 8: max_connections TOCTOU — the cap must be enforced atomically."""

    async def test_add_conn_enforces_max_connections_at_registration(self):
        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections = 1

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")

            # A second connection pushes the count beyond max_connections and
            # must be rejected at registration time (not pass a stale count).
            muxed_conn2 = _established_mock_muxed_conn(swarm.self_id)
            with pytest.raises(
                SwarmException, match="Maximum connections limit reached"
            ):
                await swarm.add_conn(muxed_conn2, direction="inbound")

            # The first connection survives; only the overshooting one closed.
            assert len(swarm.get_connections()) == 1
            assert not conn1.is_closed
            muxed_conn2.close.assert_awaited()


@pytest.mark.trio
class TestBug5BackgroundPrune:
    """Bug 5: pruning must not block the dial/accept hot path."""

    async def test_prune_scheduling_returns_immediately(self):
        swarm = SwarmFactory.build()
        run_count = 0

        async def fake_prune():
            nonlocal run_count
            run_count += 1
            await trio.sleep(0.05)

        swarm.connection_pruner.maybe_prune_connections = fake_prune

        async with background_trio_service(swarm):
            # _schedule_prune is synchronous — it must return immediately and
            # let the prune run in a background task.
            import time

            started = time.monotonic()
            swarm._schedule_prune()
            elapsed = time.monotonic() - started
            assert elapsed < 0.01

            await trio.sleep(0.2)
            assert run_count == 1

    async def test_prune_is_debounced(self):
        swarm = SwarmFactory.build()
        run_count = 0

        async def fake_prune():
            nonlocal run_count
            run_count += 1

        swarm.connection_pruner.maybe_prune_connections = fake_prune

        async with background_trio_service(swarm):
            # Three quick triggers within the debounce window collapse into a
            # single background prune.
            swarm._schedule_prune()
            swarm._schedule_prune()
            swarm._schedule_prune()
            await trio.sleep(0.2)
            assert run_count == 1


@pytest.mark.trio
class TestBug6AutoConnectOnDisconnect:
    """Bug 6: disconnects must trigger the auto-connector promptly."""

    async def test_disconnect_schedules_auto_connect(self):
        swarm = SwarmFactory.build()
        triggered = 0

        async def fake_maybe_connect():
            nonlocal triggered
            triggered += 1

        swarm.auto_connector.maybe_connect = fake_maybe_connect

        async with background_trio_service(swarm):
            # The periodic task fires maybe_connect once at startup — measure
            # the disconnect-triggered increment relative to that baseline.
            await trio.sleep(0.1)
            baseline = triggered
            await swarm.notify_disconnected(Mock())
            await trio.sleep(0.2)
            assert triggered == baseline + 1

    async def test_auto_connect_trigger_is_cooldown_limited(self):
        swarm = SwarmFactory.build()
        triggered = 0

        async def fake_maybe_connect():
            nonlocal triggered
            triggered += 1

        swarm.auto_connector.maybe_connect = fake_maybe_connect

        async with background_trio_service(swarm):
            await trio.sleep(0.1)
            baseline = triggered
            # Rapid disconnects within the cooldown window collapse into a
            # single auto-connect trigger.
            await swarm.notify_disconnected(Mock())
            await swarm.notify_disconnected(Mock())
            await swarm.notify_disconnected(Mock())
            await trio.sleep(0.2)
            assert triggered == baseline + 1


@pytest.mark.trio
class TestBug7NotifeeIsolation:
    """Bug 7: a failing notifee must not tear down connections."""

    class BrokenNotifee:
        """A notifee whose connected callback always raises."""

        async def connected(self, network, conn):
            raise RuntimeError("boom")

        async def disconnected(self, network, conn):
            pass

        async def opened_stream(self, network, stream):
            pass

        async def closed_stream(self, network, stream):
            pass

        async def listen(self, network, multiaddr):
            pass

        async def listen_close(self, network, multiaddr):
            pass

    async def test_failing_notifee_does_not_break_add_conn(self):
        swarm = SwarmFactory.build()
        muxed_conn = _established_mock_muxed_conn(swarm.self_id)

        async with background_trio_service(swarm):
            swarm.register_notifee(self.BrokenNotifee())
            # add_conn calls notify_connected, whose notifee raises — the
            # connection must still be established successfully.
            conn = await swarm.add_conn(muxed_conn, direction="inbound")
            assert not conn.is_closed
            assert conn in swarm.connections[swarm.self_id]


@pytest.mark.trio
class TestBug9CloseClosesConnections:
    """Bug 9: Swarm.close() must close active connections deterministically."""

    async def test_close_closes_all_active_connections(self):
        swarm = SwarmFactory.build()
        muxed_conn = _established_mock_muxed_conn(swarm.self_id)

        async with background_trio_service(swarm):
            conn = await swarm.add_conn(muxed_conn, direction="inbound")
            assert not conn.is_closed

            # close() must explicitly close the connection (releasing its
            # resource scope / socket) rather than relying on task cancel.
            await swarm.close()

        assert conn.is_closed
        muxed_conn.close.assert_awaited()
        assert swarm.get_total_connections() == 0


@pytest.mark.trio
class TestBug6DisconnectBackoff:
    """Disconnect-triggered auto-connect must not re-dial the lost peer."""

    async def test_recently_disconnected_peer_is_skipped(self):
        from libp2p.peer.id import ID

        swarm = SwarmFactory.build()
        peer_id = ID.from_string(
            "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )

        # A peer that just disconnected is skipped by the auto-connector.
        swarm.auto_connector.record_disconnect(peer_id)
        assert swarm.auto_connector._should_skip_peer(peer_id) is True

        # A successful connection clears the disconnect backoff.
        swarm.auto_connector.record_successful_connection(peer_id)
        assert swarm.auto_connector._should_skip_peer(peer_id) is False


@pytest.mark.trio
class TestBug11PerPeerDialCap:
    """Bug 11: dial_peer must not return more than max_connections_per_peer."""

    async def test_dial_peer_caps_connections_per_peer(self):
        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections_per_peer = 2
        swarm.connection_config.max_connections = 100

        # Four addresses that all succeed — more than the per-peer cap.
        addrs = [
            Multiaddr(f"/ip4/127.0.0.1/tcp/{8000 + i}") for i in range(4)
        ]
        swarm.peerstore.add_addrs(swarm.self_id, addrs, 100)

        async def fake_dial(addr, peer_id):
            muxed_conn = _established_mock_muxed_conn(peer_id)
            return await swarm.add_conn(muxed_conn, direction="outbound")

        swarm._dial_with_retry = fake_dial

        async with background_trio_service(swarm):
            conns = await swarm.dial_peer(swarm.self_id)

        # Even when several dials succeed before the happy-eyeballs cancel
        # lands, the per-peer limit must hold on the returned list and the
        # swarm's tracking.
        assert len(conns) <= 2
        assert len(swarm.connections.get(swarm.self_id, [])) <= 2


@pytest.mark.trio
class TestBug4TrimConnectionsSafeguards:
    """Bug 4: per-peer trimming must respect grace period and protection."""

    async def test_trim_skips_grace_period_and_trims_old_unprotected(self):
        import time

        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections_per_peer = 1
        swarm.connection_config.grace_period = 20.0

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")
            # Age conn1 past the grace period so it becomes trimmable.
            conn1._created_at = time.time() - 100

            muxed_conn2 = _established_mock_muxed_conn(swarm.self_id)
            conn2 = await swarm.add_conn(muxed_conn2, direction="inbound")
            # conn2 is brand new — within the grace period, so it must survive.

            # The add_conn above already triggered a trim (2 > 1). Give the
            # tracked background close a moment to run.
            await trio.sleep(0.3)

            assert conn1.is_closed
            assert not conn2.is_closed
            assert conn2 in swarm.connections[swarm.self_id]

    async def test_trim_skips_protected_peers(self):
        import time

        swarm = SwarmFactory.build()
        swarm.connection_config.max_connections_per_peer = 1
        swarm.connection_config.grace_period = 0.0
        swarm.protect(swarm.self_id, "test-protection")

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")
            conn1._created_at = time.time() - 100

            muxed_conn2 = _established_mock_muxed_conn(swarm.self_id)
            conn2 = await swarm.add_conn(muxed_conn2, direction="inbound")
            conn2._created_at = time.time() - 100

            await trio.sleep(0.3)

            # The protected peer's connections must all survive the trim.
            assert not conn1.is_closed
            assert not conn2.is_closed
            assert len(swarm.connections[swarm.self_id]) == 2


@pytest.mark.trio
class TestBug10NegativePeerCache:
    """Bug 10: negative peer cache must be short-lived and evictable."""

    async def test_default_ttl_is_short(self):
        from libp2p.network.swarm import _NegativePeerCache

        cache = _NegativePeerCache()
        assert cache._ttl <= 60.0

    async def test_unblock_peer_lifts_the_block(self):
        swarm = SwarmFactory.build()
        peer_id = swarm.self_id

        swarm._negative_peer_cache.mark_failed(str(peer_id))
        assert swarm._negative_peer_cache.is_blocked(str(peer_id))

        # dial_peer refuses while blocked.
        with pytest.raises(SwarmException, match="recently failed"):
            await swarm.dial_peer(peer_id)

        # The public unblock API lifts the block immediately.
        swarm.unblock_peer(peer_id)
        assert not swarm._negative_peer_cache.is_blocked(str(peer_id))
