"""
Utilities for lightweight peer reputation tracking within the Kademlia DHT.

This module keeps an in-memory score per peer to help the routing layer prefer
healthier nodes when performing iterative lookups. The tracker is intentionally
simple so it can run on every host without external dependencies while still
being extensible for future ML-powered heuristics.
"""

from __future__ import annotations

import math
import time
from dataclasses import (
    dataclass,
)
from typing import (
    Iterable,
    List,
)

from libp2p.peer.id import (
    ID,
)

DEFAULT_BASE_SCORE = 0.5
DEFAULT_SUCCESS_WEIGHT = 0.75
DEFAULT_FAILURE_WEIGHT = 1.0
DEFAULT_RECENCY_HALFLIFE = 300.0  # seconds


@dataclass
class PeerReputationRecord:
    """Mutable stats we keep per peer."""

    successes: float = 0.0
    failures: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0

    def score(
        self,
        *,
        now: float,
        base_score: float,
        success_weight: float,
        failure_weight: float,
        recency_halflife: float,
    ) -> float:
        """Compute the peer score with a recency-aware component."""
        score_value = (
            base_score
            + self.successes * success_weight
            - self.failures * failure_weight
        )
        score_value += _recency_boost(
            now=now, last_event=self.last_success, halflife=recency_halflife
        )
        score_value -= _recency_boost(
            now=now, last_event=self.last_failure, halflife=recency_halflife
        )
        # Keep the score within sensible bounds for stability
        return max(0.0, min(2.0, score_value))


def _recency_boost(*, now: float, last_event: float, halflife: float) -> float:
    if not last_event:
        return 0.0
    elapsed = now - last_event
    if elapsed <= 0:
        return 1.0
    # Exponential decay: value halves every halflife seconds
    return math.exp(-elapsed * math.log(2) / max(1.0, halflife))


class PeerReputationTracker:
    """
    Keeps simple in-memory scores per peer.

    The heuristics are intentionally conservative but give us a clear hook for
    future ML-enhanced scoring (e.g. plugging in a logistic regression or
    gradient boosting model). For now, success/failure counts with recency
    weighting already help prioritize good actors when selecting query targets.
    """

    def __init__(
        self,
        *,
        base_score: float = DEFAULT_BASE_SCORE,
        success_weight: float = DEFAULT_SUCCESS_WEIGHT,
        failure_weight: float = DEFAULT_FAILURE_WEIGHT,
        recency_halflife: float = DEFAULT_RECENCY_HALFLIFE,
    ) -> None:
        self._records: dict[ID, PeerReputationRecord] = {}
        self.base_score = base_score
        self.success_weight = success_weight
        self.failure_weight = failure_weight
        self.recency_halflife = recency_halflife

    def record_success(self, peer_id: ID, weight: float = 1.0) -> None:
        record = self._records.setdefault(peer_id, PeerReputationRecord())
        record.successes += max(0.0, weight)
        record.last_success = time.monotonic()

    def record_failure(self, peer_id: ID, weight: float = 1.0) -> None:
        record = self._records.setdefault(peer_id, PeerReputationRecord())
        record.failures += max(0.0, weight)
        record.last_failure = time.monotonic()

    def get_score(self, peer_id: ID) -> float:
        record = self._records.get(peer_id)
        if not record:
            return self.base_score
        return record.score(
            now=time.monotonic(),
            base_score=self.base_score,
            success_weight=self.success_weight,
            failure_weight=self.failure_weight,
            recency_halflife=self.recency_halflife,
        )

    def rank_peers(self, peers: Iterable[ID]) -> List[ID]:
        """Return the given peers sorted by score (highest first)."""
        return sorted(peers, key=self.get_score, reverse=True)


