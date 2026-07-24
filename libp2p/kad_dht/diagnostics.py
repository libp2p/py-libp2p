"""
Routing table diagnostics for the Kademlia DHT.

When a KadDHT node misbehaves — slow lookups, unreachable keys, bootstrap
failures — operators have historically had to instrument the code by hand.
This module gives them a first-class diagnostic surface without any changes
to their application code.

Key questions answered:
  • Which k-buckets are under-populated or empty?
  • Where are the keyspace coverage gaps?
  • How fresh are my known peers?
  • What is the overall routing-table health as a single score?
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .common import BUCKET_SIZE, STALE_PEER_THRESHOLD
from .routing_table import RoutingTable, key_to_int, peer_id_to_key

if TYPE_CHECKING:
    pass


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class BucketStat:
    """Statistics for a single k-bucket."""

    index: int
    peer_count: int
    capacity: int
    fill_rate: float  # 0.0 – 1.0
    stale_peer_count: int
    min_range_hex: str
    max_range_hex: str

    @property
    def is_full(self) -> bool:
        return self.peer_count >= self.capacity

    @property
    def is_empty(self) -> bool:
        return self.peer_count == 0

    @property
    def health(self) -> str:
        if self.fill_rate >= 0.8:
            return "healthy"
        if self.fill_rate >= 0.4:
            return "degraded"
        return "starved"


@dataclass
class CoverageGap:
    """A contiguous keyspace range that has insufficient peer coverage."""

    min_range_hex: str
    max_range_hex: str
    peer_count: int
    bucket_index: int


@dataclass
class FreshnessDistribution:
    """How old the known peers are, bucketed by age band."""

    fresh: int = 0       # seen in the last hour
    aging: int = 0       # seen 1–12 hours ago
    stale: int = 0       # seen 12–24 hours ago
    very_stale: int = 0  # not seen for > 24 hours

    @property
    def total(self) -> int:
        return self.fresh + self.aging + self.stale + self.very_stale

    @property
    def fresh_ratio(self) -> float:
        if self.total == 0:
            return 0.0
        return self.fresh / self.total


@dataclass
class RoutingTableReport:
    """Complete snapshot of routing-table health."""

    timestamp: float
    local_peer_id_hex: str

    total_peers: int
    total_buckets: int
    populated_buckets: int

    bucket_stats: list[BucketStat]
    coverage_gaps: list[CoverageGap]
    freshness: FreshnessDistribution

    # 0–100 composite score; higher is better
    health_score: float

    # Human-readable verdict
    verdict: str

    # Raw keyspace coverage fraction (populated ranges / total ranges)
    keyspace_coverage: float

    extra: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"=== KadDHT Routing Table Report ===",
            f"Timestamp       : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}",
            f"Local peer      : {self.local_peer_id_hex[:16]}…",
            f"Health score    : {self.health_score:.1f}/100  ({self.verdict})",
            f"",
            f"Peers           : {self.total_peers}",
            f"Buckets         : {self.populated_buckets}/{self.total_buckets} populated",
            f"Keyspace cover  : {self.keyspace_coverage * 100:.1f}%",
            f"Coverage gaps   : {len(self.coverage_gaps)}",
            f"",
            f"Peer freshness",
            f"  Fresh  (<1 h) : {self.freshness.fresh}",
            f"  Aging (1–12 h): {self.freshness.aging}",
            f"  Stale (12–24h): {self.freshness.stale}",
            f"  Very stale    : {self.freshness.very_stale}",
        ]
        if self.coverage_gaps:
            lines.append(f"")
            lines.append(f"Top coverage gaps (first 3):")
            for gap in self.coverage_gaps[:3]:
                lines.append(
                    f"  bucket #{gap.bucket_index}: {gap.min_range_hex[:8]}…"
                    f"–{gap.max_range_hex[:8]}… ({gap.peer_count} peers)"
                )
        return "\n".join(lines)


# ── Diagnostics engine ────────────────────────────────────────────────────────


class RoutingTableDiagnostics:
    """
    Inspect and score a live KadDHT routing table.

    Usage::

        from libp2p.kad_dht.diagnostics import RoutingTableDiagnostics

        diag = RoutingTableDiagnostics(dht.routing_table)
        report = diag.analyse()
        print(report.summary())

    The analyser is read-only and does not modify the routing table.
    """

    #: Threshold below which a bucket is flagged as a coverage gap (peer count)
    GAP_THRESHOLD: int = BUCKET_SIZE // 4

    def __init__(
        self,
        routing_table: RoutingTable,
        stale_threshold_seconds: int = STALE_PEER_THRESHOLD,
    ) -> None:
        self._rt = routing_table
        self._stale_threshold = stale_threshold_seconds

    # ── Public API ──────────────────────────────────────────────────────────

    def analyse(self) -> RoutingTableReport:
        """Run a full diagnostic pass and return a :class:`RoutingTableReport`."""
        now = time.time()
        bucket_stats = self._collect_bucket_stats(now)
        freshness = self._collect_freshness(now)
        gaps = self._find_coverage_gaps(bucket_stats)
        keyspace_coverage = self._calc_keyspace_coverage(bucket_stats)
        health_score = self._calc_health_score(
            bucket_stats, freshness, keyspace_coverage
        )
        verdict = self._verdict(health_score)

        populated = sum(1 for b in bucket_stats if not b.is_empty)

        local_hex = self._rt.local_id.to_bytes().hex()

        return RoutingTableReport(
            timestamp=now,
            local_peer_id_hex=local_hex,
            total_peers=self._rt.size(),
            total_buckets=len(bucket_stats),
            populated_buckets=populated,
            bucket_stats=bucket_stats,
            coverage_gaps=gaps,
            freshness=freshness,
            health_score=health_score,
            verdict=verdict,
            keyspace_coverage=keyspace_coverage,
        )

    def get_bucket_stats(self) -> list[BucketStat]:
        """Return per-bucket statistics without building a full report."""
        return self._collect_bucket_stats(time.time())

    def get_freshness_distribution(self) -> FreshnessDistribution:
        """Return the peer-age distribution without building a full report."""
        return self._collect_freshness(time.time())

    def get_coverage_gaps(self) -> list[CoverageGap]:
        """Return buckets with peer counts below :attr:`GAP_THRESHOLD`."""
        return self._find_coverage_gaps(self._collect_bucket_stats(time.time()))

    def get_health_score(self) -> float:
        """Return the composite health score (0–100) without a full report."""
        now = time.time()
        stats = self._collect_bucket_stats(now)
        freshness = self._collect_freshness(now)
        coverage = self._calc_keyspace_coverage(stats)
        return self._calc_health_score(stats, freshness, coverage)

    # ── Private helpers ─────────────────────────────────────────────────────

    def _collect_bucket_stats(self, now: float) -> list[BucketStat]:
        stats: list[BucketStat] = []
        for idx, bucket in enumerate(self._rt.buckets):
            peer_count = bucket.size()
            stale = len(bucket.get_stale_peers(self._stale_threshold))
            fill_rate = peer_count / bucket.bucket_size if bucket.bucket_size else 0.0
            stats.append(
                BucketStat(
                    index=idx,
                    peer_count=peer_count,
                    capacity=bucket.bucket_size,
                    fill_rate=fill_rate,
                    stale_peer_count=stale,
                    min_range_hex=format(bucket.min_range, "064x"),
                    max_range_hex=format(bucket.max_range, "064x"),
                )
            )
        return stats

    def _collect_freshness(self, now: float) -> FreshnessDistribution:
        dist = FreshnessDistribution()
        ONE_HOUR = 3600
        TWELVE_HOURS = 12 * ONE_HOUR
        TWENTY_FOUR_HOURS = 24 * ONE_HOUR

        for bucket in self._rt.buckets:
            for _peer_id, (_info, last_seen) in bucket.peers.items():
                age = now - last_seen
                if age < ONE_HOUR:
                    dist.fresh += 1
                elif age < TWELVE_HOURS:
                    dist.aging += 1
                elif age < TWENTY_FOUR_HOURS:
                    dist.stale += 1
                else:
                    dist.very_stale += 1
        return dist

    def _find_coverage_gaps(self, stats: list[BucketStat]) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        for stat in stats:
            if stat.peer_count < self.GAP_THRESHOLD:
                gaps.append(
                    CoverageGap(
                        min_range_hex=stat.min_range_hex,
                        max_range_hex=stat.max_range_hex,
                        peer_count=stat.peer_count,
                        bucket_index=stat.index,
                    )
                )
        # Sort: emptiest buckets first (most urgent)
        gaps.sort(key=lambda g: g.peer_count)
        return gaps

    def _calc_keyspace_coverage(self, stats: list[BucketStat]) -> float:
        """
        Fraction of the full 256-bit keyspace that is *covered*.

        A bucket is considered covered when it has at least one peer.
        We weight each bucket by the fraction of the keyspace it represents.
        """
        FULL_SPACE = 2**256
        covered = 0
        for stat in stats:
            if stat.peer_count > 0:
                # Width of this bucket's range in key-space units
                lo = int(stat.min_range_hex, 16)
                hi = int(stat.max_range_hex, 16)
                covered += hi - lo
        return covered / FULL_SPACE

    def _calc_health_score(
        self,
        stats: list[BucketStat],
        freshness: FreshnessDistribution,
        keyspace_coverage: float,
    ) -> float:
        """
        Composite 0–100 score built from three sub-scores:

        * **Fill score** (40 pts) – average bucket fill rate across all buckets.
          Buckets closest to the local node matter most in Kademlia, so we
          weight by proximity (index 0 = closest = highest weight).
        * **Freshness score** (35 pts) – ratio of fresh (< 1 h) peers to total.
        * **Coverage score** (25 pts) – keyspace coverage fraction.
        """
        if not stats:
            return 0.0

        # ── fill score ──────────────────────────────────────────────────────
        # Kademlia property: buckets near the local node are the most important
        # for routing. We give them exponentially higher weight.
        total_weight = 0.0
        weighted_fill = 0.0
        n = len(stats)
        for stat in stats:
            # bucket 0 is closest to local node (after split operations)
            # weight decays as we move to far-away buckets
            weight = 2 ** max(0, n - 1 - stat.index)
            total_weight += weight
            weighted_fill += weight * stat.fill_rate

        fill_score = (weighted_fill / total_weight) * 40.0 if total_weight else 0.0

        # ── freshness score ─────────────────────────────────────────────────
        freshness_score = freshness.fresh_ratio * 35.0

        # ── coverage score ──────────────────────────────────────────────────
        coverage_score = keyspace_coverage * 25.0

        return round(fill_score + freshness_score + coverage_score, 2)

    @staticmethod
    def _verdict(score: float) -> str:
        if score >= 80:
            return "excellent"
        if score >= 60:
            return "good"
        if score >= 40:
            return "degraded"
        if score >= 20:
            return "poor"
        return "critical"
