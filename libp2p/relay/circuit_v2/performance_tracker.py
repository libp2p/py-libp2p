"""
Relay performance tracker for intelligent relay selection.

This module provides per-relay performance tracking including latency,
success rates, and active circuit counts to enable intelligent relay selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any

from libp2p.peer.id import ID

# Default scoring constants
DEFAULT_UNKNOWN_RELAY_SCORE = 1000.0
DEFAULT_CIRCUIT_PENALTY_MULTIPLIER = 5.0
DEFAULT_SUCCESS_BONUS_MULTIPLIER = 100.0


@dataclass
class RelayStats:
    """Performance statistics for a single relay."""

    relay_id: ID
    # Exponential moving average latency (-1.0 = no data yet)
    latency_ema_ms: float = -1.0
    success_count: int = 0
    failure_count: int = 0
    active_circuits: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0  # Default to 100% if no attempts yet
        return self.success_count / total

    @property
    def total_attempts(self) -> int:
        """Total connection attempts."""
        return self.success_count + self.failure_count


class RelayPerformanceTracker:
    """
    Tracks performance metrics per relay for intelligent selection.

    This tracker maintains per-relay statistics including:
    - Connection latency (exponential moving average)
    - Success/failure rates
    - Active circuit counts

    It provides methods to score and select the best relay based on these metrics.
    """

    def __init__(
        self,
        ema_alpha: float = 0.3,
        max_active_circuits: int = 100,
        latency_penalty_ms: float = 10.0,
        failure_penalty: float = 1000.0,
        min_success_rate: float = 0.5,
        circuit_penalty_multiplier: float = DEFAULT_CIRCUIT_PENALTY_MULTIPLIER,
        success_bonus_multiplier: float = DEFAULT_SUCCESS_BONUS_MULTIPLIER,
        unknown_relay_score: float = DEFAULT_UNKNOWN_RELAY_SCORE,
    ) -> None:
        """
        Initialize the relay performance tracker.

        Args:
            ema_alpha: Smoothing factor for exponential moving average (0-1).
                      Higher values give more weight to recent measurements.
            max_active_circuits: Maximum active circuits before a relay is
                considered overloaded.
            latency_penalty_ms: Penalty per millisecond of latency in scoring.
            failure_penalty: Penalty for failed connections in scoring.
            min_success_rate: Minimum success rate (0-1) for a relay to be
                considered healthy.
            circuit_penalty_multiplier: Multiplier for active circuit count in scoring.
            success_bonus_multiplier: Multiplier for success rate bonus in scoring.
            unknown_relay_score: Default score for relays with no performance data.

        """
        self.ema_alpha = ema_alpha
        self.max_active_circuits = max_active_circuits
        self.latency_penalty_ms = latency_penalty_ms
        self.failure_penalty = failure_penalty
        self.min_success_rate = min_success_rate
        self.circuit_penalty_multiplier = circuit_penalty_multiplier
        self.success_bonus_multiplier = success_bonus_multiplier
        self.unknown_relay_score = unknown_relay_score

        # Per-relay statistics
        self._relay_stats: dict[ID, RelayStats] = {}
        self._lock = threading.RLock()

    def record_connection_attempt(
        self,
        relay_id: ID,
        latency_ms: float,
        success: bool,
    ) -> None:
        """
        Record a connection attempt to a relay.

        Args:
            relay_id: The relay's peer ID
            latency_ms: Connection latency in milliseconds
            success: Whether the connection succeeded

        """
        with self._lock:
            if relay_id not in self._relay_stats:
                self._relay_stats[relay_id] = RelayStats(relay_id=relay_id)

            stats = self._relay_stats[relay_id]

            # Update latency EMA
            if stats.latency_ema_ms < 0.0:
                # First measurement - use it directly (sentinel value -1.0)
                stats.latency_ema_ms = latency_ms
            else:
                # Update EMA: new = alpha * current + (1 - alpha) * old
                stats.latency_ema_ms = (
                    self.ema_alpha * latency_ms
                    + (1 - self.ema_alpha) * stats.latency_ema_ms
                )

            # Update success/failure counts
            if success:
                stats.success_count += 1
            else:
                stats.failure_count += 1

            stats.last_updated = time.time()

    def record_circuit_opened(self, relay_id: ID) -> None:
        """
        Record that a circuit was opened through a relay.

        Args:
            relay_id: The relay's peer ID

        """
        with self._lock:
            if relay_id not in self._relay_stats:
                self._relay_stats[relay_id] = RelayStats(relay_id=relay_id)

            self._relay_stats[relay_id].active_circuits += 1
            self._relay_stats[relay_id].last_updated = time.time()

    def record_circuit_closed(self, relay_id: ID) -> None:
        """
        Record that a circuit was closed through a relay.

        Args:
            relay_id: The relay's peer ID

        """
        with self._lock:
            if relay_id not in self._relay_stats:
                # Circuit closed for unknown relay - ignore
                return

            stats = self._relay_stats[relay_id]
            stats.active_circuits = max(0, stats.active_circuits - 1)
            stats.last_updated = time.time()

    def get_relay_score(self, relay_id: ID) -> float:
        """
        Calculate a score for a relay (lower is better).

        The score is based on:
        - Latency (lower is better)
        - Active circuits (fewer is better)
        - Success rate (higher is better)

        Args:
            relay_id: The relay's peer ID

        Returns:
            Score for the relay (lower is better), or float('inf') if unhealthy

        """
        with self._lock:
            if relay_id not in self._relay_stats:
                # No data yet - return neutral score
                return self.unknown_relay_score

            stats = self._relay_stats[relay_id]

            # Check if relay is healthy
            if stats.success_rate < self.min_success_rate:
                return float("inf")  # Unhealthy relay

            # Check if relay is overloaded
            if stats.active_circuits >= self.max_active_circuits:
                return float("inf")  # Overloaded relay

            # Calculate base score from latency
            # If no latency data yet (sentinel -1.0), use unknown_relay_score
            if stats.latency_ema_ms < 0.0:
                return self.unknown_relay_score

            latency_score = stats.latency_ema_ms * self.latency_penalty_ms

            # Add penalty for active circuits (load balancing)
            circuit_penalty = stats.active_circuits * self.circuit_penalty_multiplier

            # Add penalty for failures (reliability)
            failure_penalty = stats.failure_count * self.failure_penalty

            # Subtract bonus for success rate (higher is better)
            success_bonus = stats.success_rate * self.success_bonus_multiplier

            total_score = (
                latency_score + circuit_penalty + failure_penalty - success_bonus
            )

            return max(0.0, total_score)  # Ensure non-negative

    def select_best_relay(
        self,
        available_relays: list[ID],
        *,
        require_reservation: bool = False,
        relay_info_getter: Any = None,
    ) -> ID | None:
        """
        Select the best relay from available options.

        Args:
            available_relays: List of relay peer IDs to choose from
            require_reservation: If True, only consider relays with active reservations
            relay_info_getter: Optional callable to get relay info for reservation check

        Returns:
            Selected relay ID, or None if no suitable relay found

        """
        if not available_relays:
            return None

        with self._lock:
            # Filter relays based on requirements
            candidates = []
            for relay_id in available_relays:
                # Check reservation requirement if needed
                if require_reservation and relay_info_getter:
                    relay_info = relay_info_getter(relay_id)
                    if not (
                        relay_info and getattr(relay_info, "has_reservation", False)
                    ):
                        continue

                # Check if relay is healthy
                score = self.get_relay_score(relay_id)
                if score == float("inf"):
                    continue  # Skip unhealthy/overloaded relays

                candidates.append((relay_id, score))

            if not candidates:
                # No healthy relays found - fallback to first available
                # (might be a new relay with no stats yet)
                return available_relays[0] if available_relays else None

            # Sort by score (lower is better)
            candidates.sort(key=lambda x: x[1])

            # Return the best relay
            return candidates[0][0]

    def get_relay_stats(self, relay_id: ID) -> RelayStats | None:
        """
        Get statistics for a specific relay.

        Args:
            relay_id: The relay's peer ID

        Returns:
            RelayStats object, or None if relay not found

        """
        with self._lock:
            return self._relay_stats.get(relay_id)

    def get_all_relay_stats(self) -> dict[ID, RelayStats]:
        """
        Get statistics for all tracked relays.

        Returns:
            Dictionary mapping relay IDs to their stats

        """
        with self._lock:
            return dict(self._relay_stats)

    def export_metrics(self) -> dict[str, Any]:
        """
        Export metrics for Prometheus/monitoring.

        Returns:
            Dictionary with metrics data

        """
        with self._lock:
            relay_metrics: dict[str, dict[str, Any]] = {}

            for relay_id, stats in self._relay_stats.items():
                relay_metrics[str(relay_id)] = {
                    "latency_ema_ms": stats.latency_ema_ms,
                    "success_count": stats.success_count,
                    "failure_count": stats.failure_count,
                    "success_rate": stats.success_rate,
                    "active_circuits": stats.active_circuits,
                    "total_attempts": stats.total_attempts,
                    "last_updated": stats.last_updated,
                }

            return {
                "relays_tracked": len(self._relay_stats),
                "relay_metrics": relay_metrics,
            }

    def reset(self) -> None:
        """Reset all tracking data."""
        with self._lock:
            self._relay_stats.clear()
