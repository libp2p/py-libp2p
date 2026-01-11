"""
AutoNAT predictive helper.

Stores recent dial outcomes and produces a probability that the local node is
publicly reachable. This is intentionally simple and dependency-free while
still providing a clearer signal than raw success counts.
"""

from __future__ import annotations

from collections import (
    deque,
)
from dataclasses import (
    dataclass,
)
import time
from typing import (
    Deque,
    Tuple,
)

from .autonat import (
    AutoNATStatus,
)


@dataclass
class ProbeResult:
    timestamp: float
    success: bool


class AutoNATDecisionModel:
    def __init__(self, history_size: int = 20) -> None:
        self.history: Deque[ProbeResult] = deque(maxlen=history_size)

    def record_probe(self, *, success: bool) -> None:
        self.history.append(ProbeResult(time.monotonic(), success))

    def probability_public(self) -> float:
        if not self.history:
            return 0.5
        weighted_success = 0.0
        weighted_total = 0.0
        now = time.monotonic()
        for probe in self.history:
            age = max(1.0, now - probe.timestamp)
            weight = 1.0 / age  # newer samples have higher weight
            weighted_total += weight
            if probe.success:
                weighted_success += weight
        if weighted_total == 0:
            return 0.5
        return weighted_success / weighted_total

    def classify(self) -> Tuple[int, float]:
        probability = self.probability_public()
        if probability >= 0.65:
            status = AutoNATStatus.PUBLIC
        elif probability <= 0.35:
            status = AutoNATStatus.PRIVATE
        else:
            status = AutoNATStatus.UNKNOWN
        return status, probability


