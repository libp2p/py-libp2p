"""
Generic anomaly detection helpers for per-peer metrics.

The detector is deliberately simple and dependency-free while still providing
useful signals (moving rate window + adaptive z-score). Other subsystems can
plug in more sophisticated models later without changing the interface.
"""

from __future__ import annotations

from collections import (
    defaultdict,
    deque,
)
from dataclasses import (
    dataclass,
)
import math
import time
from typing import (
    Deque,
    Dict,
    Tuple,
)

from libp2p.peer.id import (
    ID,
)


class RunningStats:
    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)


class SlidingWindowRate:
    def __init__(self, window_seconds: float) -> None:
        self.window = window_seconds
        self.samples: Deque[Tuple[float, float]] = deque()

    def add(self, amount: float) -> None:
        now = time.monotonic()
        self.samples.append((now, amount))
        self._trim(now)

    def rate(self) -> float:
        now = time.monotonic()
        self._trim(now)
        total = sum(amount for _, amount in self.samples)
        return total / max(self.window, 1.0)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()


@dataclass
class AnomalyReport:
    peer_id: ID
    metric: str
    rate: float
    mean: float
    stddev: float
    z_score: float


class PeerAnomalyDetector:
    def __init__(
        self,
        *,
        window_seconds: float = 120.0,
        std_threshold: float = 3.0,
        min_samples: int = 30,
        cooldown: float = 60.0,
    ) -> None:
        self.window_seconds = window_seconds
        self.std_threshold = std_threshold
        self.min_samples = min_samples
        self.cooldown = cooldown
        self._peer_metrics: Dict[ID, Dict[str, SlidingWindowRate]] = defaultdict(dict)
        self._baselines: Dict[str, RunningStats] = defaultdict(RunningStats)
        self._last_alert: Dict[Tuple[ID, str], float] = {}

    def record(self, peer_id: ID, metric: str, amount: float) -> AnomalyReport | None:
        tracker = self._peer_metrics[peer_id].setdefault(
            metric, SlidingWindowRate(self.window_seconds)
        )
        tracker.add(amount)
        current_rate = tracker.rate()

        stats = self._baselines[metric]
        report = self._detect(peer_id, metric, current_rate, stats)
        stats.update(current_rate)
        return report

    def _detect(
        self,
        peer_id: ID,
        metric: str,
        rate: float,
        stats: RunningStats,
    ) -> AnomalyReport | None:
        key = (peer_id, metric)
        now = time.monotonic()
        last_alert = self._last_alert.get(key, 0.0)
        if now - last_alert < self.cooldown:
            return None

        if stats.count < self.min_samples:
            return None

        stddev = math.sqrt(stats.variance)
        mean = stats.mean
        if stddev == 0.0:
            threshold = mean * 2.5
            if rate <= threshold:
                return None
            z_score = float("inf")
        else:
            z_score = (rate - mean) / stddev
            if z_score < self.std_threshold:
                return None

        self._last_alert[key] = now
        return AnomalyReport(
            peer_id=peer_id,
            metric=metric,
            rate=rate,
            mean=mean,
            stddev=stddev,
            z_score=z_score,
        )


