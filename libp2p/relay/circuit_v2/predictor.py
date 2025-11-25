"""
Predictive heuristics for relay vs. direct connectivity decisions.

The implementation intentionally stays lightweight (no external ML deps) yet
provides a clear API for recording observations and retrieving probability
estimates. It can be swapped out for a more sophisticated model later.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)
import math
import time
from typing import (
    Iterable,
    Sequence,
)

from multiaddr import (
    Multiaddr,
)

from libp2p.peer.id import (
    ID,
)

from .nat import (
    extract_ip_from_multiaddr,
    is_private_ip,
)


@dataclass
class PeerConnectionStats:
    successes: int = 0
    failures: int = 0
    relay_successes: int = 0
    direct_successes: int = 0
    avg_latency: float = 0.0
    last_failure: float = 0.0

    def record(self, *, success: bool, via_relay: bool, latency: float | None) -> None:
        if success:
            self.successes += 1
            if via_relay:
                self.relay_successes += 1
            else:
                self.direct_successes += 1
            if latency is not None:
                if self.avg_latency == 0.0:
                    self.avg_latency = latency
                else:
                    self.avg_latency = (self.avg_latency * 0.7) + (latency * 0.3)
        else:
            self.failures += 1
            self.last_failure = time.monotonic()

    @property
    def failure_rate(self) -> float:
        attempts = self.successes + self.failures
        if attempts == 0:
            return 0.0
        return self.failures / attempts


@dataclass
class RelayDecision:
    probability: float
    recommendation: str
    rationale: dict[str, float]


class RelayDecisionPredictor:
    """
    Simple scoring model that estimates how likely a peer requires relay support.
    """

    def __init__(self) -> None:
        self._stats: dict[ID, PeerConnectionStats] = {}

    def record_observation(
        self,
        peer_id: ID,
        *,
        success: bool,
        via_relay: bool,
        latency: float | None = None,
    ) -> None:
        stats = self._stats.setdefault(peer_id, PeerConnectionStats())
        stats.record(success=success, via_relay=via_relay, latency=latency)

    def predict(
        self,
        peer_id: ID,
        *,
        addrs: Sequence[Multiaddr] | None = None,
    ) -> RelayDecision:
        stats = self._stats.get(peer_id, PeerConnectionStats())
        rationale: dict[str, float] = {}
        score = 0.25  # base prior that NAT/relay may be required

        addr_score = self._score_addresses(addrs)
        score += addr_score
        if addr_score:
            rationale["addr_score"] = addr_score

        failure_penalty = stats.failure_rate * 0.5
        score += failure_penalty
        if failure_penalty:
            rationale["failure_penalty"] = failure_penalty

        if stats.direct_successes == 0 and stats.relay_successes > 0:
            score += 0.2
            rationale["relay_bias"] = 0.2

        if stats.avg_latency and stats.avg_latency > 0.75:
            score += 0.1
            rationale["latency_penalty"] = 0.1

        # decay penalty for stale failures
        if stats.last_failure:
            age = time.monotonic() - stats.last_failure
            if age > 120:
                decay = min(0.15, math.log(age / 60) / 20)
                score -= decay
                rationale["failure_decay"] = -decay

        score = max(0.0, min(0.95, score))

        if score >= 0.7:
            recommendation = "prefer_relay"
        elif score >= 0.45:
            recommendation = "hole_punch"
        else:
            recommendation = "direct_ok"

        rationale["score"] = score
        return RelayDecision(probability=score, recommendation=recommendation, rationale=rationale)

    def _score_addresses(self, addrs: Sequence[Multiaddr] | None) -> float:
        if not addrs:
            return 0.0
        total = len(addrs)
        private = 0
        for addr in addrs:
            ip = extract_ip_from_multiaddr(addr)
            if ip and is_private_ip(ip):
                private += 1
        if total == 0:
            return 0.0
        private_ratio = private / total
        if private_ratio == 0:
            return -0.1  # reward public peers slightly
        if private_ratio > 0.75:
            return 0.35
        if private_ratio > 0.4:
            return 0.2
        return 0.05

    def observed_peers(self) -> Iterable[ID]:
        return self._stats.keys()


