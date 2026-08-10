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
