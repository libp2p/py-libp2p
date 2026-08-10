"""
Regression tests for connection manager bug fixes.

Each test class documents the bug it guards against (referenced by number in
the connection-manager analysis) so the commit history stays self-explanatory.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr import Multiaddr

from libp2p.network.swarm import Swarm, SwarmException
from tests.utils.factories import SwarmFactory


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
