"""
Tests for Phase 4 — CMInfo unified connection manager snapshot.

Covers:
  - CMInfo dataclass fields and defaults
  - Swarm.get_conn_mgr_info() returns correct watermark/grace/count values
  - last_trim is None before any prune and a float after a prune cycle
  - ConnectionPruner._last_trim_time stamped only when connections are closed
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from libp2p.abc import CMInfo
from libp2p.network.config import ConnectionConfig
from libp2p.network.connection_pruner import ConnectionPruner
from libp2p.network.tag_store import TagStore

# ── CMInfo dataclass tests ─────────────────────────────────────────────────────


class TestCMInfo:
    """Test CMInfo dataclass construction and fields."""

    def test_cminfo_fields(self):
        """CMInfo stores all five fields correctly."""
        ts = time.time()
        info = CMInfo(
            low_watermark=100,
            high_watermark=200,
            connected_count=50,
            grace_period=30.0,
            last_trim=ts,
        )
        assert info.low_watermark == 100
        assert info.high_watermark == 200
        assert info.connected_count == 50
        assert info.grace_period == 30.0
        assert info.last_trim == ts

    def test_cminfo_last_trim_none(self):
        """CMInfo last_trim can be None when never trimmed."""
        info = CMInfo(
            low_watermark=10,
            high_watermark=20,
            connected_count=5,
            grace_period=60.0,
            last_trim=None,
        )
        assert info.last_trim is None

    def test_cminfo_is_dataclass(self):
        """CMInfo is a proper dataclass with equality semantics."""
        a = CMInfo(10, 20, 5, 60.0, None)
        b = CMInfo(10, 20, 5, 60.0, None)
        assert a == b

    def test_cminfo_inequality(self):
        """CMInfo instances with different fields are not equal."""
        a = CMInfo(10, 20, 5, 60.0, None)
        b = CMInfo(10, 20, 6, 60.0, None)  # different connected_count
        assert a != b


# ── ConnectionPruner._last_trim_time tests ─────────────────────────────────────


class TestPrunerLastTrimTime:
    """Test that ConnectionPruner._last_trim_time is stamped correctly."""

    def _make_pruner(self):
        """Build a minimal ConnectionPruner with a mocked swarm."""
        swarm = MagicMock()
        # Use valid ConnectionConfig values:
        # min_connections=50, low_watermark>=50, high_watermark>=low, max>=high
        swarm.connection_config = ConnectionConfig(
            low_watermark=100,
            high_watermark=200,
            grace_period=30.0,
        )
        swarm.tag_store = TagStore()
        return ConnectionPruner(swarm)

    def test_last_trim_time_starts_none(self):
        """_last_trim_time is None before any prune runs."""
        pruner = self._make_pruner()
        assert pruner._last_trim_time is None

    @pytest.mark.trio
    async def test_last_trim_time_set_after_prune(self):
        """_last_trim_time is set after connections are closed in a prune cycle."""
        pruner = self._make_pruner()

        # Build enough mock connections to trigger pruning (> high_watermark=200)
        mock_conn = MagicMock()
        mock_conn.muxed_conn.peer_id = MagicMock()
        mock_conn.is_closed = False
        mock_conn.close = AsyncMock()
        # _created_at far in the past so grace period doesn't protect it
        mock_conn._created_at = time.time() - 9999

        connections = [mock_conn] * 210  # 210 > high_watermark=200
        # Override with MagicMock so return_value works correctly
        pruner.swarm.get_connections = MagicMock(return_value=connections)
        pruner.swarm.peerstore.addrs.return_value = []
        pruner.swarm.connection_gate.is_in_allow_list.return_value = False

        # Patch tag store — use the real TagStore, no mock needed (no peers tagged)
        # just ensure is_protected returns False
        pruner.swarm.tag_store.is_protected = MagicMock(return_value=False)

        before = time.time()
        pruner._started = True
        await pruner._maybe_prune_connections()
        after = time.time()

        assert pruner._last_trim_time is not None
        assert before <= pruner._last_trim_time <= after

    @pytest.mark.trio
    async def test_last_trim_time_not_set_below_watermark(self):
        # _last_trim_time stays None when connection count is
        # at or below high_watermark.
        pruner = self._make_pruner()

        # Fewer connections than high_watermark=200 — no pruning needed
        connections = [MagicMock()] * 5  # 5 <= 200
        pruner.swarm.get_connections = MagicMock(return_value=connections)

        pruner._started = True
        await pruner._maybe_prune_connections()

        assert pruner._last_trim_time is None


# ── Swarm.get_conn_mgr_info() tests ───────────────────────────────────────────


class TestSwarmGetConnMgrInfo:
    """Test Swarm.get_conn_mgr_info() builds a correct CMInfo snapshot."""

    def _make_swarm_stub(
        self,
        low: int = 100,
        high: int = 200,
        grace: float = 30.0,
        connected: int = 15,
        last_trim: float | None = None,
    ):
        # Build a minimal Swarm stub with just the attributes
        # get_conn_mgr_info needs.
        swarm = MagicMock()
        # Use valid ConnectionConfig values: min_connections default is 50
        swarm.connection_config = ConnectionConfig(
            low_watermark=low,
            high_watermark=high,
            grace_period=grace,
        )
        swarm.get_total_connections.return_value = connected
        swarm.connection_pruner._last_trim_time = last_trim

        # Import and patch the real method directly for testing
        from libp2p.network.swarm import Swarm

        swarm.get_conn_mgr_info = lambda: Swarm.get_conn_mgr_info(swarm)
        return swarm

    def test_get_conn_mgr_info_fields(self):
        """get_conn_mgr_info returns correct watermarks, count, grace, and last_trim."""
        swarm = self._make_swarm_stub(
            low=100, high=200, grace=30.0, connected=15, last_trim=None
        )
        info = swarm.get_conn_mgr_info()
        assert isinstance(info, CMInfo)
        assert info.low_watermark == 100
        assert info.high_watermark == 200
        assert info.connected_count == 15
        assert info.grace_period == 30.0
        assert info.last_trim is None

    def test_get_conn_mgr_info_with_last_trim(self):
        """get_conn_mgr_info reflects last_trim from the pruner."""
        ts = time.time() - 60.0
        swarm = self._make_swarm_stub(last_trim=ts)
        info = swarm.get_conn_mgr_info()
        assert info.last_trim == ts

    def test_get_conn_mgr_info_connected_count_live(self):
        """connected_count is read fresh each call — not cached."""
        swarm = self._make_swarm_stub(connected=5)

        info_first = swarm.get_conn_mgr_info()
        assert info_first.connected_count == 5

        swarm.get_total_connections.return_value = 20
        info_second = swarm.get_conn_mgr_info()
        assert info_second.connected_count == 20
