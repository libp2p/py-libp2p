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
from libp2p.network.swarm import SwarmException
from libp2p.tools.anyio_service import background_trio_service
from tests.utils.factories import SwarmFactory


def swarm_peer_id():
    """A deterministic peer ID for tests that don't need a full swarm."""
    from libp2p.peer.id import ID

    return ID.from_string("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")


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
        setattr(dup_wrapper, "_shared_muxed_conn", True)
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
        run_count: list[int] = []

        async def fake_prune():
            run_count.append(1)
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
            assert len(run_count) == 1

    async def test_prune_is_debounced(self):
        swarm = SwarmFactory.build()
        run_count: list[int] = []

        async def fake_prune():
            run_count.append(1)

        swarm.connection_pruner.maybe_prune_connections = fake_prune

        async with background_trio_service(swarm):
            # Three quick triggers within the debounce window collapse into a
            # single background prune.
            swarm._schedule_prune()
            swarm._schedule_prune()
            swarm._schedule_prune()
            await trio.sleep(0.2)
            assert len(run_count) == 1


@pytest.mark.trio
class TestBug6AutoConnectOnDisconnect:
    """Bug 6: disconnects must trigger the auto-connector promptly."""

    async def test_disconnect_schedules_auto_connect(self):
        swarm = SwarmFactory.build()
        triggered: list[int] = []

        async def fake_maybe_connect():
            triggered.append(1)

        swarm.auto_connector.maybe_connect = fake_maybe_connect

        async with background_trio_service(swarm):
            # The periodic task fires maybe_connect once at startup — measure
            # the disconnect-triggered increment relative to that baseline.
            await trio.sleep(0.1)
            baseline = len(triggered)
            await swarm.notify_disconnected(Mock())
            await trio.sleep(0.2)
            assert len(triggered) == baseline + 1

    async def test_auto_connect_trigger_is_cooldown_limited(self):
        swarm = SwarmFactory.build()
        triggered: list[int] = []

        async def fake_maybe_connect():
            triggered.append(1)

        swarm.auto_connector.maybe_connect = fake_maybe_connect

        async with background_trio_service(swarm):
            await trio.sleep(0.1)
            baseline = len(triggered)
            # Rapid disconnects within the cooldown window collapse into a
            # single auto-connect trigger.
            await swarm.notify_disconnected(Mock())
            await swarm.notify_disconnected(Mock())
            await swarm.notify_disconnected(Mock())
            await trio.sleep(0.2)
            assert len(triggered) == baseline + 1


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
        peer_id = ID.from_string("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")

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
        addrs = [Multiaddr(f"/ip4/127.0.0.1/tcp/{8000 + i}") for i in range(4)]
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


@pytest.mark.trio
class TestBug13DefensiveCopies:
    """Bug 13: get_connections/get_connections_map must not expose internals."""

    async def test_getters_return_defensive_copies(self):
        swarm = SwarmFactory.build()

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            await swarm.add_conn(muxed_conn, direction="inbound")

            # Mutating the returned list must not affect internal tracking.
            conns = swarm.get_connections(swarm.self_id)
            conns.clear()
            assert len(swarm.connections[swarm.self_id]) == 1

            conn_map = swarm.get_connections_map()
            conn_map[swarm.self_id].clear()
            conn_map.clear()
            assert len(swarm.connections[swarm.self_id]) == 1


@pytest.mark.trio
class TestBug14PrunerAllowListRemoteAddr:
    """Bug 14: pruner allow-list must use the connection's real remote IP."""

    async def test_allow_list_uses_connection_remote_address(self):
        from libp2p.network.connection.swarm_connection import SwarmConn
        from libp2p.network.connection_pruner import is_connection_in_allow_list

        swarm = SwarmFactory.build()
        # Only 10.0.0.1 is allow-listed by the gate.
        swarm.connection_gate.add_to_allow_list("10.0.0.1")

        muxed_conn = _established_mock_muxed_conn(swarm.self_id)
        # The actual connection is from a non-allow-listed IP, even though the
        # peerstore could claim an allow-listed address.
        muxed_conn.get_remote_address = Mock(return_value=("10.0.0.2", 4001))
        conn = SwarmConn(muxed_conn, swarm)
        assert is_connection_in_allow_list(conn, swarm) is False

        # A connection genuinely from the allow-listed IP is exempt.
        muxed_conn.get_remote_address = Mock(return_value=("10.0.0.1", 4001))
        assert is_connection_in_allow_list(conn, swarm) is True


@pytest.mark.trio
class TestBug15MinConnectionsFunctional:
    """Bug 15: min_connections must drive behavior, not just logging."""

    async def test_below_min_connections_triggers_critical_state(self):
        swarm = SwarmFactory.build()
        connector = swarm.auto_connector
        # No connections yet → critically below the floor.
        assert connector._below_min_connections() is True

        # Above the floor → normal state.
        fake_conn = Mock()
        fake_conn.is_closed = False
        for _ in range(swarm.connection_config.min_connections):
            swarm.connections.setdefault(swarm.self_id, []).append(fake_conn)
        assert connector._below_min_connections() is False

    async def test_critical_check_interval_is_shorter(self):
        swarm = SwarmFactory.build()
        connector = swarm.auto_connector
        assert connector._critical_check_interval < connector.auto_connect_interval


class TestBug12ConnectionPoolOptIn:
    """Bug 12: the dead connection pool must be off by default."""

    def test_connection_pool_off_by_default(self):
        from libp2p.rcmgr.manager import new_resource_manager

        rm = new_resource_manager()
        assert rm.connection_pool is None

    def test_connection_pool_can_be_opted_in(self):
        from libp2p.rcmgr.manager import new_resource_manager

        rm = new_resource_manager(enable_connection_pooling=True)
        assert rm.connection_pool is not None

    def test_config_default_is_false(self):
        from libp2p.rcmgr.config import PerformanceConfig

        assert PerformanceConfig().enable_connection_pooling is False


@pytest.mark.trio
class TestBug1LifecycleLimits:
    """Bug 1: Rust-style connection limits must actually be enforced."""

    async def test_lifecycle_manager_enforces_per_peer_limit(self):
        from libp2p.rcmgr.connection_lifecycle import ConnectionLifecycleManager
        from libp2p.rcmgr.connection_limits import ConnectionLimits
        from libp2p.rcmgr.connection_tracker import ConnectionTracker
        from libp2p.rcmgr.exceptions import ResourceLimitExceeded

        limits = ConnectionLimits().with_max_established_per_peer(1)
        mgr = ConnectionLifecycleManager(ConnectionTracker(limits), limits)
        peer_id = swarm_peer_id()
        addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

        await mgr.handle_established_inbound_connection("c1", peer_id, addr, addr)
        # Second connection to the same peer exceeds the per-peer limit.
        with pytest.raises(ResourceLimitExceeded):
            await mgr.handle_established_inbound_connection("c2", peer_id, addr, addr)

        # Closing the first connection frees the slot.
        mgr.notify_connection_closed("c1", peer_id)
        await mgr.handle_established_inbound_connection("c3", peer_id, addr, addr)

    async def test_add_conn_enforces_lifecycle_per_peer_limit(self):
        from libp2p.rcmgr import new_resource_manager
        from libp2p.rcmgr.connection_limits import ConnectionLimits

        limits = ConnectionLimits().with_max_established_per_peer(1)
        rm = new_resource_manager(connection_limits=limits)
        swarm = SwarmFactory.build()
        swarm.set_resource_manager(rm, enable_stream_semaphore=False)

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")

            # Second connection to the same peer must be rejected.
            muxed_conn2 = _established_mock_muxed_conn(swarm.self_id)
            with pytest.raises(SwarmException, match="denied by connection limits"):
                await swarm.add_conn(muxed_conn2, direction="inbound")
            assert len(swarm.connections[swarm.self_id]) == 1

            # Closing the admitted connection frees the per-peer slot.
            await conn1.close()
            muxed_conn3 = _established_mock_muxed_conn(swarm.self_id)
            conn3 = await swarm.add_conn(muxed_conn3, direction="inbound")
            assert not conn3.is_closed

    async def test_lifecycle_tracker_returns_to_zero_after_full_cycle(self):
        """
        The lifecycle tracker must balance across admit → close cycles.

        Guards the invariant that every admitted connection is decremented
        exactly once when it is torn down — including the dedup race path
        where a duplicate wrapper shares the muxed connection (Bug 1 + 3).
        """
        from libp2p.rcmgr import new_resource_manager

        rm = new_resource_manager()
        lifecycle = rm.connection_lifecycle
        assert lifecycle is not None
        swarm = SwarmFactory.build()
        swarm.set_resource_manager(rm, enable_stream_semaphore=False)

        async with background_trio_service(swarm):
            muxed_conn = _established_mock_muxed_conn(swarm.self_id)
            conn1 = await swarm.add_conn(muxed_conn, direction="inbound")

            # Closing the connection must release its tracker slot.
            await conn1.close()
            assert lifecycle.get_connection_stats()["current_established_total"] == 0

            # Full admit → dedup-race → close cycle stays balanced.
            muxed_conn2 = _established_mock_muxed_conn(swarm.self_id)
            conn_a = await swarm.add_conn(muxed_conn2, direction="inbound")
            conn_b = await swarm.add_conn(muxed_conn2, direction="inbound")
            # Duplicate add returns the surviving wrapper.
            assert conn_a is conn_b
            assert lifecycle.get_connection_stats()["current_established_total"] == 1

            # Simulate the race-window duplicate wrapper: it shares the same
            # muxed_conn (same tracker id) and is marked shared.  Closing it
            # must NOT decrement the slot held by the surviving connection.
            from libp2p.network.connection.swarm_connection import SwarmConn

            dup_wrapper = SwarmConn(muxed_conn2, swarm)
            setattr(dup_wrapper, "_shared_muxed_conn", True)
            await dup_wrapper.close()
            assert lifecycle.get_connection_stats()["current_established_total"] == 1

            # Closing the surviving connection releases the slot.
            await conn_a.close()
            assert lifecycle.get_connection_stats()["current_established_total"] == 0
            assert (
                lifecycle.get_connection_stats()["current_peers_with_connections"] == 0
            )
