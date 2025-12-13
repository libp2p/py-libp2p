"""
Unit tests for connection pruner implementation.

Tests for connection pruning logic, sorting, allow list handling,
and tag value calculation.
"""

import time
from unittest.mock import Mock

import pytest
from multiaddr import Multiaddr

from libp2p.network.config import ConnectionConfig
from libp2p.network.connection_pruner import (
    ConnectionPruner,
    get_peer_tag_value,
    is_connection_in_allow_list,
)
from libp2p.peer.id import ID


class TestGetPeerTagValue:
    """Test peer tag value calculation."""

    def test_get_peer_tag_value_no_peer(self):
        """Test tag value when peer not found."""
        peer_store = Mock()
        peer_store.peer_data_map = {}
        peer_id = ID(b"QmTest")

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 0

    def test_get_peer_tag_value_no_metadata(self):
        """Test tag value when peer has no metadata."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = None

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 0

    def test_get_peer_tag_value_empty_metadata(self):
        """Test tag value when metadata is empty."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = {}

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 0

    def test_get_peer_tag_value_with_numeric_tags(self):
        """Test tag value with numeric tag values."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = {
            "tag_importance": 50,
            "tag_reliability": 30,
        }

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 80  # 50 + 30

    def test_get_peer_tag_value_with_dict_tags(self):
        """Test tag value with dictionary tag values."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = {
            "tag_importance": {"value": 50},
            "tag_reliability": {"value": 25},
        }

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 75  # 50 + 25

    def test_get_peer_tag_value_ignores_non_tag_keys(self):
        """Test that non-tag_ prefixed keys are ignored."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = {
            "tag_importance": 50,
            "other_key": 1000,  # Should be ignored
            "random": 500,  # Should be ignored
        }

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 50

    def test_get_peer_tag_value_no_peer_data_map(self):
        """Test tag value when peer_data_map doesn't exist."""
        peer_store = Mock(spec=[])  # No attributes
        peer_id = ID(b"QmTest")

        value = get_peer_tag_value(peer_store, peer_id)
        assert value == 0


class TestIsConnectionInAllowList:
    """Test allow list checking for connections."""

    def test_connection_in_allow_list(self):
        """Test connection that is in allow list."""
        peer_id = ID(b"QmTest")
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")

        # Create mock connection
        connection = Mock()
        connection.muxed_conn = Mock()
        connection.muxed_conn.peer_id = peer_id

        # Create mock swarm with connection gate
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.addrs = Mock(return_value=[addr])
        swarm.connection_gate = Mock()
        swarm.connection_gate.is_in_allow_list = Mock(return_value=True)

        result = is_connection_in_allow_list(connection, swarm)
        assert result is True

    def test_connection_not_in_allow_list(self):
        """Test connection that is not in allow list."""
        peer_id = ID(b"QmTest")
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")

        connection = Mock()
        connection.muxed_conn = Mock()
        connection.muxed_conn.peer_id = peer_id

        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.addrs = Mock(return_value=[addr])
        swarm.connection_gate = Mock()
        swarm.connection_gate.is_in_allow_list = Mock(return_value=False)

        result = is_connection_in_allow_list(connection, swarm)
        assert result is False

    def test_connection_check_error_returns_false(self):
        """Test that errors return False."""
        connection = Mock()
        connection.muxed_conn = Mock()
        connection.muxed_conn.peer_id = Mock(side_effect=Exception("Error"))

        swarm = Mock()

        result = is_connection_in_allow_list(connection, swarm)
        assert result is False


class TestConnectionPrunerInitialization:
    """Test ConnectionPruner initialization."""

    def test_connection_pruner_defaults(self):
        """Test ConnectionPruner default configuration."""
        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        assert pruner.swarm is swarm
        assert pruner.allow_list == []
        assert pruner._started is False

    def test_connection_pruner_with_allow_list(self):
        """Test ConnectionPruner with allow list."""
        swarm = Mock()
        allow_list = ["192.168.1.1", "10.0.0.0/8"]

        pruner = ConnectionPruner(swarm, allow_list=allow_list)
        assert pruner.allow_list == allow_list


class TestConnectionPrunerLifecycle:
    """Test ConnectionPruner start/stop lifecycle."""

    @pytest.mark.trio
    async def test_connection_pruner_start(self):
        """Test starting the connection pruner."""
        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        assert pruner._started is False
        await pruner.start()
        assert pruner._started is True

    @pytest.mark.trio
    async def test_connection_pruner_stop(self):
        """Test stopping the connection pruner."""
        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        await pruner.start()
        assert pruner._started is True

        await pruner.stop()
        assert pruner._started is False


class TestConnectionPrunerPruning:
    """Test connection pruning logic."""

    @pytest.mark.trio
    async def test_maybe_prune_not_started(self):
        """Test that pruning is skipped when not started."""
        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        # Should not raise
        await pruner.maybe_prune_connections()

    @pytest.mark.trio
    async def test_maybe_prune_under_limit(self):
        """Test that no pruning occurs when under limit."""
        swarm = Mock()
        swarm.connection_config = ConnectionConfig(max_connections=10)
        swarm.get_connections = Mock(return_value=[])

        pruner = ConnectionPruner(swarm)
        await pruner.start()

        # Should not prune anything
        await pruner.maybe_prune_connections()

    @pytest.mark.trio
    async def test_maybe_prune_at_limit(self):
        """Test that no pruning occurs at exactly the limit."""
        swarm = Mock()
        swarm.connection_config = ConnectionConfig(max_connections=2)

        # Create 2 mock connections
        conn1 = Mock()
        conn1.muxed_conn = Mock()
        conn1.muxed_conn.peer_id = ID(b"QmTest1")

        conn2 = Mock()
        conn2.muxed_conn = Mock()
        conn2.muxed_conn.peer_id = ID(b"QmTest2")

        swarm.get_connections = Mock(return_value=[conn1, conn2])

        pruner = ConnectionPruner(swarm)
        await pruner.start()

        # Should not prune
        await pruner.maybe_prune_connections()


class TestConnectionSorting:
    """Test connection sorting for pruning priority."""

    def test_sort_connections_by_tag_value(self):
        """Test that connections are sorted by peer tag value."""
        peer_id_low = ID(b"QmLow")
        peer_id_high = ID(b"QmHigh")

        # Create mock connections
        conn_low = Mock()
        conn_low.muxed_conn = Mock()
        conn_low.muxed_conn.peer_id = peer_id_low
        conn_low.get_streams = Mock(return_value=[])

        conn_high = Mock()
        conn_high.muxed_conn = Mock()
        conn_high.muxed_conn.peer_id = peer_id_high
        conn_high.get_streams = Mock(return_value=[])

        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        peer_values = {
            peer_id_low: 10,
            peer_id_high: 100,
        }

        sorted_conns = pruner.sort_connections([conn_high, conn_low], peer_values)

        # Lower value should be first (pruned first)
        assert sorted_conns[0] is conn_low
        assert sorted_conns[1] is conn_high

    def test_sort_connections_by_stream_count(self):
        """Test that connections are sorted by stream count."""
        peer_id1 = ID(b"QmTest1")
        peer_id2 = ID(b"QmTest2")

        # Connection with fewer streams
        conn_few = Mock()
        conn_few.muxed_conn = Mock()
        conn_few.muxed_conn.peer_id = peer_id1
        conn_few.get_streams = Mock(return_value=[Mock()])  # 1 stream

        # Connection with more streams
        conn_many = Mock()
        conn_many.muxed_conn = Mock()
        conn_many.muxed_conn.peer_id = peer_id2
        conn_many.get_streams = Mock(return_value=[Mock(), Mock(), Mock()])  # 3 streams

        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        # Same tag values
        peer_values = {
            peer_id1: 50,
            peer_id2: 50,
        }

        sorted_conns = pruner.sort_connections([conn_many, conn_few], peer_values)

        # Fewer streams should be first (pruned first)
        assert sorted_conns[0] is conn_few
        assert sorted_conns[1] is conn_many

    def test_sort_connections_empty_list(self):
        """Test sorting empty connection list."""
        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        sorted_conns = pruner.sort_connections([], {})
        assert sorted_conns == []

    def test_sort_connections_single_connection(self):
        """Test sorting single connection."""
        peer_id = ID(b"QmTest")

        conn = Mock()
        conn.muxed_conn = Mock()
        conn.muxed_conn.peer_id = peer_id
        conn.get_streams = Mock(return_value=[])

        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        sorted_conns = pruner.sort_connections([conn], {peer_id: 50})
        assert len(sorted_conns) == 1
        assert sorted_conns[0] is conn


class TestConnectionAgeTracking:
    """Test connection age tracking in sorting."""

    def test_sort_by_age_when_other_factors_equal(self):
        """Test that older connections are pruned first when other factors equal."""
        peer_id1 = ID(b"QmTest1")
        peer_id2 = ID(b"QmTest2")

        # Older connection
        conn_old = Mock()
        conn_old.muxed_conn = Mock()
        conn_old.muxed_conn.peer_id = peer_id1
        conn_old.get_streams = Mock(return_value=[])
        conn_old._created_at = time.time() - 100  # 100 seconds ago

        # Newer connection
        conn_new = Mock()
        conn_new.muxed_conn = Mock()
        conn_new.muxed_conn.peer_id = peer_id2
        conn_new.get_streams = Mock(return_value=[])
        conn_new._created_at = time.time() - 10  # 10 seconds ago

        swarm = Mock()
        pruner = ConnectionPruner(swarm)

        # Same tag values
        peer_values = {
            peer_id1: 50,
            peer_id2: 50,
        }

        sorted_conns = pruner.sort_connections([conn_new, conn_old], peer_values)

        # Older connection should be first (pruned first)
        assert sorted_conns[0] is conn_old
        assert sorted_conns[1] is conn_new


class TestPrunerAllowListProtection:
    """Test that allow list connections are protected from pruning."""

    @pytest.mark.trio
    async def test_allow_list_connections_not_pruned(self):
        """Test that connections in allow list are not selected for pruning."""
        peer_id = ID(b"QmTest")
        addr = Multiaddr("/ip4/192.168.1.1/tcp/1234")

        # Create mock connection
        conn = Mock()
        conn.muxed_conn = Mock()
        conn.muxed_conn.peer_id = peer_id
        conn.get_streams = Mock(return_value=[])

        # Create many connections to exceed limit
        swarm = Mock()
        swarm.connection_config = ConnectionConfig(max_connections=1)  # Valid value
        swarm.get_connections = Mock(return_value=[conn, conn])  # 2 connections > limit
        swarm.peerstore = Mock()
        swarm.peerstore.addrs = Mock(return_value=[addr])
        swarm.peerstore.peer_data_map = {}
        swarm.connection_gate = Mock()
        swarm.connection_gate.is_in_allow_list = Mock(return_value=True)

        pruner = ConnectionPruner(swarm)
        await pruner.start()

        # The _maybe_prune_connections should skip allow list connections
        await pruner.maybe_prune_connections()

        # Connection should NOT have been closed (it's in allow list)
        conn.close.assert_not_called()


class TestPrunerIntegration:
    """Integration tests for connection pruner."""

    @pytest.mark.trio
    async def test_full_lifecycle(self):
        """Test full pruner lifecycle."""
        swarm = Mock()
        swarm.connection_config = ConnectionConfig(max_connections=10)
        swarm.get_connections = Mock(return_value=[])

        pruner = ConnectionPruner(swarm)

        # Start
        await pruner.start()
        assert pruner._started is True

        # Prune (no connections)
        await pruner.maybe_prune_connections()

        # Stop
        await pruner.stop()
        assert pruner._started is False
