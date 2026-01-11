"""
Adaptive tuning helpers for GossipSub.

This module provides a lightweight controller that watches heartbeat metrics and
nudges mesh parameters toward healthier values. It is intentionally simple so it
can run in every node without external dependencies while remaining extensible
for future ML-based strategies.
"""

from __future__ import annotations

from collections import (
    deque,
)
from dataclasses import (
    dataclass,
)
import logging
from typing import (
    Deque,
    Dict,
    TYPE_CHECKING,
)

if TYPE_CHECKING:  # pragma: no cover - avoid importing GossipSub at runtime
    from .gossipsub import (
        GossipSub,
    )

logger = logging.getLogger("libp2p.pubsub.gossipsub.adaptive")


@dataclass(slots=True)
class AdaptiveTuningConfig:
    """Configurable knobs for the adaptive tuner."""

    window_size: int = 6
    min_degree: int = 3
    max_degree: int = 32
    min_heartbeat_interval: int = 20
    max_heartbeat_interval: int = 240
    high_gossip_threshold: int = 120
    low_gossip_threshold: int = 8
    max_px_peers: int = 32
    min_px_peers: int = 4


class GossipSubAdaptiveTuner:
    """Simple moving-average controller for GossipSub runtime parameters."""

    def __init__(
        self,
        router: GossipSub,
        config: AdaptiveTuningConfig | None = None,
    ) -> None:
        self.router = router
        self.config = config or AdaptiveTuningConfig()
        self._history: Deque[Dict[str, float]] = deque(maxlen=self.config.window_size)

    def record_heartbeat(
        self,
        *,
        mesh_sizes: dict[str, int],
        fanout_sizes: dict[str, int],
        graft_total: int,
        prune_total: int,
        gossip_total: int,
    ) -> None:
        mesh_avg = (
            sum(mesh_sizes.values()) / len(mesh_sizes) if mesh_sizes else 0.0
        )
        fanout_avg = (
            sum(fanout_sizes.values()) / len(fanout_sizes) if fanout_sizes else 0.0
        )
        snapshot = {
            "mesh_avg": mesh_avg,
            "fanout_avg": fanout_avg,
            "graft": float(graft_total),
            "prune": float(prune_total),
            "gossip": float(gossip_total),
        }
        self._history.append(snapshot)
        self._maybe_adjust()

    def _maybe_adjust(self) -> None:
        if len(self._history) < 2:
            return
        avg_mesh = sum(item["mesh_avg"] for item in self._history) / len(self._history)
        avg_graft = sum(item["graft"] for item in self._history) / len(self._history)
        avg_prune = sum(item["prune"] for item in self._history) / len(self._history)
        avg_gossip = sum(item["gossip"] for item in self._history) / len(
            self._history
        )
        self._adjust_degrees(avg_mesh, avg_graft, avg_prune)
        self._adjust_heartbeat(avg_gossip)
        self._adjust_px(avg_mesh)

    def _adjust_degrees(self, avg_mesh: float, avg_graft: float, avg_prune: float) -> None:
        router = self.router
        increased = False
        decreased = False
        low_target = max(self.config.min_degree, router.degree_low)
        high_target = max(router.degree, min(self.config.max_degree, router.degree_high))

        if avg_mesh < low_target * 0.9 and avg_graft >= avg_prune:
            new_degree = min(self.config.max_degree, router.degree + 1)
            if new_degree != router.degree:
                router.degree = new_degree
                router.degree_low = min(new_degree - 1, max(self.config.min_degree, router.degree_low + 1))
                router.degree_high = max(router.degree_high, new_degree + 1)
                increased = True

        elif avg_mesh > high_target * 1.1 and avg_prune > avg_graft:
            new_degree = max(self.config.min_degree, router.degree - 1)
            if new_degree != router.degree:
                router.degree = new_degree
                router.degree_high = max(router.degree + 1, min(router.degree_high - 1, self.config.max_degree))
                router.degree_low = max(self.config.min_degree, min(router.degree_low, router.degree - 1))
                decreased = True

        if increased or decreased:
            router.degree_low = max(self.config.min_degree, min(router.degree_low, router.degree))
            router.degree_high = max(router.degree + 1, min(router.degree_high, self.config.max_degree))
            logger.debug(
                "Adaptive tuning updated mesh degree bounds: degree=%s, low=%s, high=%s",
                router.degree,
                router.degree_low,
                router.degree_high,
            )

    def _adjust_heartbeat(self, avg_gossip: float) -> None:
        router = self.router
        if avg_gossip > self.config.high_gossip_threshold:
            new_interval = max(
                self.config.min_heartbeat_interval,
                int(router.heartbeat_interval * 0.8),
            )
            if new_interval != router.heartbeat_interval:
                logger.debug(
                    "Adaptive tuning: lowering heartbeat interval %s -> %s due to high gossip load",
                    router.heartbeat_interval,
                    new_interval,
                )
                router.heartbeat_interval = new_interval
        elif avg_gossip < self.config.low_gossip_threshold:
            new_interval = min(
                self.config.max_heartbeat_interval,
                int(router.heartbeat_interval * 1.15) + 1,
            )
            if new_interval != router.heartbeat_interval:
                logger.debug(
                    "Adaptive tuning: increasing heartbeat interval %s -> %s due to low gossip load",
                    router.heartbeat_interval,
                    new_interval,
                )
                router.heartbeat_interval = new_interval

    def _adjust_px(self, avg_mesh: float) -> None:
        router = self.router
        if not router.do_px:
            return
        if avg_mesh < max(1.0, router.degree_low * 0.9):
            new_px = min(self.config.max_px_peers, router.px_peers_count + 1)
            if new_px != router.px_peers_count:
                router.px_peers_count = new_px
                logger.debug(
                    "Adaptive tuning: increasing PX peers to %s to improve connectivity",
                    new_px,
                )
        elif avg_mesh > router.degree * 1.2:
            new_px = max(self.config.min_px_peers, router.px_peers_count - 1)
            if new_px != router.px_peers_count:
                router.px_peers_count = new_px
                logger.debug(
                    "Adaptive tuning: decreasing PX peers to %s to reduce overhead",
                    new_px,
                )


