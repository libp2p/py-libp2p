"""
Tests for RoutingTableDiagnostics.

We build synthetic routing tables (without a live network) so the tests run
fast and deterministically, exercising every dimension of the diagnostics.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from unittest.mock import MagicMock

import pytest

from libp2p.kad_dht.diagnostics import (
    BucketStat,
    CoverageGap,
    FreshnessDistribution,
    RoutingTableDiagnostics,
    RoutingTableReport,
)
from libp2p.kad_dht.routing_table import KBucket, RoutingTable, peer_id_to_key
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_peer_id(seed: int) -> ID:
    """Create a deterministic peer ID from an integer seed."""
    raw = seed.to_bytes(32, "big")
    return ID(b"\x00\x25\x08\x02\x12\x20" + raw[:32])


def _make_peer_info(seed: int) -> PeerInfo:
    return PeerInfo(_make_peer_id(seed), [])


def _host_stub() -> MagicMock:
    host = MagicMock()
    peerstore = MagicMock()
    peerstore.addrs.return_value = []
    host.get_peerstore.return_value = peerstore
    return host


def _make_routing_table(n_peers: int = 0, last_seen_offset: float = 0.0) -> RoutingTable:
    """
    Build a RoutingTable backed by a mock host and populate it with
    *n_peers* synthetic peers whose last_seen timestamp is (now - last_seen_offset).
    """
    local_id = _make_peer_id(0)
    host = _host_stub()
    rt = RoutingTable(local_id, host)

    now = time.time()
    for i in range(1, n_peers + 1):
        peer_info = _make_peer_info(i)
        bucket = rt.find_bucket(peer_info.peer_id)
        bucket.peers[peer_info.peer_id] = (peer_info, now - last_seen_offset)

    return rt


# ── BucketStat ────────────────────────────────────────────────────────────


class TestBucketStat:
    def test_is_full_when_at_capacity(self):
        stat = BucketStat(
            index=0,
            peer_count=20,
            capacity=20,
            fill_rate=1.0,
            stale_peer_count=0,
            min_range_hex="0" * 64,
            max_range_hex="f" * 64,
        )
        assert stat.is_full

    def test_is_empty(self):
        stat = BucketStat(
            index=0,
            peer_count=0,
            capacity=20,
            fill_rate=0.0,
            stale_peer_count=0,
            min_range_hex="0" * 64,
            max_range_hex="f" * 64,
        )
        assert stat.is_empty

    def test_health_healthy(self):
        stat = BucketStat(0, 18, 20, 0.9, 0, "0" * 64, "f" * 64)
        assert stat.health == "healthy"

    def test_health_degraded(self):
        stat = BucketStat(0, 10, 20, 0.5, 0, "0" * 64, "f" * 64)
        assert stat.health == "degraded"

    def test_health_starved(self):
        stat = BucketStat(0, 2, 20, 0.1, 0, "0" * 64, "f" * 64)
        assert stat.health == "starved"


# ── FreshnessDistribution ─────────────────────────────────────────────────


class TestFreshnessDistribution:
    def test_fresh_ratio_with_all_fresh(self):
        fd = FreshnessDistribution(fresh=10, aging=0, stale=0, very_stale=0)
        assert fd.fresh_ratio == pytest.approx(1.0)

    def test_fresh_ratio_mixed(self):
        fd = FreshnessDistribution(fresh=5, aging=5, stale=0, very_stale=0)
        assert fd.fresh_ratio == pytest.approx(0.5)

    def test_fresh_ratio_empty(self):
        fd = FreshnessDistribution()
        assert fd.fresh_ratio == pytest.approx(0.0)

    def test_total(self):
        fd = FreshnessDistribution(fresh=1, aging=2, stale=3, very_stale=4)
        assert fd.total == 10


# ── RoutingTableDiagnostics ───────────────────────────────────────────────


class TestRoutingTableDiagnosticsEmpty:
    """Tests against an empty routing table (single bucket, zero peers)."""

    def setup_method(self):
        self.rt = _make_routing_table(n_peers=0)
        self.diag = RoutingTableDiagnostics(self.rt)

    def test_analyse_returns_report(self):
        report = self.diag.analyse()
        assert isinstance(report, RoutingTableReport)

    def test_total_peers_is_zero(self):
        report = self.diag.analyse()
        assert report.total_peers == 0

    def test_health_score_is_zero_for_empty_table(self):
        score = self.diag.get_health_score()
        assert score == pytest.approx(0.0)

    def test_verdict_is_critical_for_zero_score(self):
        report = self.diag.analyse()
        assert report.verdict == "critical"

    def test_single_bucket_all_gap(self):
        gaps = self.diag.get_coverage_gaps()
        assert len(gaps) == 1
        assert gaps[0].peer_count == 0

    def test_keyspace_coverage_is_zero(self):
        report = self.diag.analyse()
        assert report.keyspace_coverage == pytest.approx(0.0)


class TestRoutingTableDiagnosticsPopulated:
    """Tests against a routing table with several fresh peers."""

    def setup_method(self):
        # 10 peers all seen < 1 hour ago
        self.rt = _make_routing_table(n_peers=10, last_seen_offset=100)
        self.diag = RoutingTableDiagnostics(self.rt)

    def test_total_peers(self):
        assert self.diag.analyse().total_peers == 10

    def test_freshness_all_fresh(self):
        fd = self.diag.get_freshness_distribution()
        assert fd.fresh == 10
        assert fd.aging == 0
        assert fd.stale == 0
        assert fd.very_stale == 0

    def test_health_score_positive(self):
        score = self.diag.get_health_score()
        assert score > 0

    def test_bucket_stats_returns_list(self):
        stats = self.diag.get_bucket_stats()
        assert isinstance(stats, list)
        assert len(stats) >= 1

    def test_keyspace_coverage_positive(self):
        report = self.diag.analyse()
        assert report.keyspace_coverage > 0.0


class TestRoutingTableDiagnosticsStalePeers:
    """Tests against a routing table with only very stale peers."""

    def setup_method(self):
        # peers last seen 30 hours ago
        self.rt = _make_routing_table(n_peers=5, last_seen_offset=30 * 3600)
        self.diag = RoutingTableDiagnostics(self.rt)

    def test_freshness_all_very_stale(self):
        fd = self.diag.get_freshness_distribution()
        assert fd.very_stale == 5
        assert fd.fresh == 0

    def test_health_score_penalised_for_stale_peers(self):
        # A table with only very stale peers should score lower than fresh peers
        fresh_rt = _make_routing_table(n_peers=5, last_seen_offset=60)
        fresh_score = RoutingTableDiagnostics(fresh_rt).get_health_score()
        stale_score = self.diag.get_health_score()
        assert stale_score < fresh_score


class TestHealthScoreMonotonicity:
    """More peers should yield a higher (or equal) health score, all else equal."""

    def test_more_fresh_peers_score_higher_or_equal(self):
        scores = []
        for n in [0, 5, 10, 15, 20]:
            rt = _make_routing_table(n_peers=n, last_seen_offset=60)
            scores.append(RoutingTableDiagnostics(rt).get_health_score())

        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"Score dropped from {scores[i]} to {scores[i+1]} "
                f"when going from {[0,5,10,15,20][i]} to {[0,5,10,15,20][i+1]} peers"
            )


class TestSummary:
    def test_summary_is_non_empty_string(self):
        rt = _make_routing_table(n_peers=3, last_seen_offset=200)
        report = RoutingTableDiagnostics(rt).analyse()
        summary = report.summary()
        assert isinstance(summary, str)
        assert len(summary) > 50

    def test_summary_contains_score(self):
        rt = _make_routing_table(n_peers=3, last_seen_offset=200)
        report = RoutingTableDiagnostics(rt).analyse()
        assert "Health score" in report.summary()


class TestGetDiagnosticsShortcut:
    """RoutingTable.get_diagnostics() convenience method."""

    def test_returns_diagnostics_instance(self):
        rt = _make_routing_table(n_peers=0)
        diag = rt.get_diagnostics()
        assert isinstance(diag, RoutingTableDiagnostics)

    def test_analyse_via_shortcut(self):
        rt = _make_routing_table(n_peers=4, last_seen_offset=60)
        report = rt.get_diagnostics().analyse()
        assert report.total_peers == 4
