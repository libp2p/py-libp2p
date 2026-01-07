"""
Unit tests for RelayPerformanceTracker.

Tests the core functionality of relay performance tracking including:
- Connection attempt tracking with latency
- Circuit lifecycle tracking
- Relay scoring algorithm
- Best relay selection
"""

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.performance_tracker import (
    RelayPerformanceTracker,
    RelayStats,
)


def create_test_peer_id(name: str) -> ID:
    """Create a valid peer ID for testing."""
    # Use crypto to generate valid peer IDs (following existing test patterns)
    key_pair = create_new_key_pair()
    return ID.from_pubkey(key_pair.public_key)


class TestRelayStats:
    """Test suite for RelayStats dataclass."""

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        relay_id = create_test_peer_id("test")
        stats = RelayStats(relay_id=relay_id)

        # No attempts yet - should default to 1.0
        assert stats.success_rate == 1.0

        # Add successes
        stats.success_count = 8
        stats.failure_count = 2
        assert stats.success_rate == 0.8

        # All successes
        stats.success_count = 10
        stats.failure_count = 0
        assert stats.success_rate == 1.0

        # All failures
        stats.success_count = 0
        stats.failure_count = 10
        assert stats.success_rate == 0.0

    def test_total_attempts(self):
        """Test total attempts calculation."""
        relay_id = create_test_peer_id("test")
        stats = RelayStats(relay_id=relay_id)

        assert stats.total_attempts == 0

        stats.success_count = 5
        stats.failure_count = 3
        assert stats.total_attempts == 8


class TestRelayPerformanceTracker:
    """Test suite for RelayPerformanceTracker class."""

    def test_initialization(self):
        """Test tracker initialization with default parameters."""
        tracker = RelayPerformanceTracker()

        assert tracker.ema_alpha == 0.3
        assert tracker.max_active_circuits == 100
        assert len(tracker.get_all_relay_stats()) == 0

    def test_initialization_custom_params(self):
        """Test tracker initialization with custom parameters."""
        tracker = RelayPerformanceTracker(
            ema_alpha=0.5,
            max_active_circuits=50,
            latency_penalty_ms=20.0,
            failure_penalty=2000.0,
            min_success_rate=0.6,
        )

        assert tracker.ema_alpha == 0.5
        assert tracker.max_active_circuits == 50
        assert tracker.latency_penalty_ms == 20.0
        assert tracker.failure_penalty == 2000.0
        assert tracker.min_success_rate == 0.6

    def test_record_connection_attempt_first_measurement(self):
        """Test recording first connection attempt (should set EMA directly)."""
        tracker = RelayPerformanceTracker(ema_alpha=0.3)
        relay_id = create_test_peer_id("relay1")

        tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=True)

        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 100.0
        assert stats.success_count == 1
        assert stats.failure_count == 0

    def test_record_connection_attempt_ema_calculation(self):
        """Test EMA calculation for multiple connection attempts."""
        tracker = RelayPerformanceTracker(ema_alpha=0.5)  # 50% weight for new values
        relay_id = create_test_peer_id("relay1")

        # First measurement
        tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 100.0

        # Second measurement: EMA = 0.5 * 200 + 0.5 * 100 = 150
        tracker.record_connection_attempt(relay_id, latency_ms=200.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 150.0

        # Third measurement: EMA = 0.5 * 50 + 0.5 * 150 = 100
        tracker.record_connection_attempt(relay_id, latency_ms=50.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 100.0

    def test_record_connection_attempt_zero_latency(self):
        """Test that 0ms latency is handled correctly (not treated as sentinel)."""
        tracker = RelayPerformanceTracker(ema_alpha=0.5)
        relay_id = create_test_peer_id("relay1")

        # First measurement with 0ms latency (e.g., localhost)
        tracker.record_connection_attempt(relay_id, latency_ms=0.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 0.0

        # Second measurement with 0ms latency - should update EMA correctly
        # EMA = 0.5 * 0.0 + 0.5 * 0.0 = 0.0
        tracker.record_connection_attempt(relay_id, latency_ms=0.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 0.0

        # Third measurement with non-zero latency - should update EMA
        # EMA = 0.5 * 100.0 + 0.5 * 0.0 = 50.0
        tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=True)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == 50.0

    def test_record_connection_attempt_success_failure(self):
        """Test tracking success and failure counts."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("relay1")

        tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=True)
        tracker.record_connection_attempt(relay_id, latency_ms=150.0, success=True)
        tracker.record_connection_attempt(relay_id, latency_ms=200.0, success=False)

        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.success_count == 2
        assert stats.failure_count == 1
        assert stats.success_rate == 2 / 3

    def test_record_circuit_opened(self):
        """Test recording circuit opened events."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("relay1")

        tracker.record_circuit_opened(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 1

        tracker.record_circuit_opened(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 2

    def test_record_circuit_closed(self):
        """Test recording circuit closed events."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("relay1")

        # Open some circuits
        tracker.record_circuit_opened(relay_id)
        tracker.record_circuit_opened(relay_id)
        tracker.record_circuit_opened(relay_id)

        # Close one
        tracker.record_circuit_closed(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 2

        # Close another
        tracker.record_circuit_closed(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 1

        # Close more than exist (should not go negative)
        tracker.record_circuit_closed(relay_id)
        tracker.record_circuit_closed(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 0

    def test_record_circuit_closed_unknown_relay(self):
        """Test that closing circuit for unknown relay is ignored."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("unknown")

        # Should not raise error
        tracker.record_circuit_closed(relay_id)

        # Should not create stats entry
        stats = tracker.get_relay_stats(relay_id)
        assert stats is None

    def test_get_relay_score_unknown_relay(self):
        """Test scoring for relay with no data."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("unknown")

        score = tracker.get_relay_score(relay_id)
        assert score == tracker.unknown_relay_score  # Default score

    def test_get_relay_score_no_latency_data(self):
        """Test scoring for relay with stats but no latency data (sentinel -1.0)."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("no_latency")

        # Create stats via circuit_opened (no connection attempts = no latency data)
        tracker.record_circuit_opened(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.latency_ema_ms == -1.0  # Sentinel value

        # Should return unknown_relay_score since no latency data
        score = tracker.get_relay_score(relay_id)
        assert score == tracker.unknown_relay_score

    def test_get_relay_score_unhealthy_relay(self):
        """Test that unhealthy relays (low success rate) get infinite score."""
        tracker = RelayPerformanceTracker(min_success_rate=0.5)
        relay_id = create_test_peer_id("unhealthy")

        # Record many failures
        for _ in range(10):
            tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=False)
        tracker.record_connection_attempt(relay_id, latency_ms=100.0, success=True)

        score = tracker.get_relay_score(relay_id)
        assert score == float("inf")

    def test_get_relay_score_overloaded_relay(self):
        """Test that overloaded relays get infinite score."""
        tracker = RelayPerformanceTracker(max_active_circuits=5)
        relay_id = create_test_peer_id("overloaded")

        # Record successful connection
        tracker.record_connection_attempt(relay_id, latency_ms=50.0, success=True)

        # Open too many circuits
        for _ in range(6):  # Exceeds max of 5
            tracker.record_circuit_opened(relay_id)

        score = tracker.get_relay_score(relay_id)
        assert score == float("inf")

    def test_get_relay_score_healthy_relay(self):
        """Test scoring for healthy relay."""
        tracker = RelayPerformanceTracker(latency_penalty_ms=1.0, failure_penalty=100.0)
        relay_id = create_test_peer_id("healthy")

        # Record successful connections with low latency
        tracker.record_connection_attempt(relay_id, latency_ms=50.0, success=True)
        tracker.record_connection_attempt(relay_id, latency_ms=60.0, success=True)

        # Open a few circuits
        tracker.record_circuit_opened(relay_id)
        tracker.record_circuit_opened(relay_id)

        score = tracker.get_relay_score(relay_id)
        assert score != float("inf")
        assert score >= 0.0

    def test_select_best_relay_empty_list(self):
        """Test selection with empty relay list."""
        tracker = RelayPerformanceTracker()

        result = tracker.select_best_relay([])
        assert result is None

    def test_select_best_relay_single_relay(self):
        """Test selection with single relay."""
        tracker = RelayPerformanceTracker()
        relay_id = create_test_peer_id("relay1")

        result = tracker.select_best_relay([relay_id])
        assert result == relay_id

    def test_select_best_relay_picks_fastest(self):
        """Test that selection picks relay with lowest latency."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("fast")
        relay2 = create_test_peer_id("slow")

        # Fast relay: low latency, successful
        tracker.record_connection_attempt(relay1, latency_ms=50.0, success=True)
        tracker.record_connection_attempt(relay1, latency_ms=60.0, success=True)

        # Slow relay: high latency, successful
        tracker.record_connection_attempt(relay2, latency_ms=200.0, success=True)
        tracker.record_connection_attempt(relay2, latency_ms=250.0, success=True)

        result = tracker.select_best_relay([relay1, relay2])
        assert result == relay1

    def test_select_best_relay_avoids_overloaded(self):
        """Test that selection avoids overloaded relays."""
        tracker = RelayPerformanceTracker(max_active_circuits=5)
        relay1 = create_test_peer_id("loaded")
        relay2 = create_test_peer_id("available")

        # Relay1: successful but overloaded
        tracker.record_connection_attempt(relay1, latency_ms=50.0, success=True)
        for _ in range(6):  # Exceeds max
            tracker.record_circuit_opened(relay1)

        # Relay2: successful and available
        tracker.record_connection_attempt(relay2, latency_ms=100.0, success=True)
        tracker.record_circuit_opened(relay2)

        result = tracker.select_best_relay([relay1, relay2])
        assert result == relay2

    def test_select_best_relay_avoids_unhealthy(self):
        """Test that selection avoids unhealthy relays."""
        tracker = RelayPerformanceTracker(min_success_rate=0.5)
        relay1 = create_test_peer_id("unhealthy")
        relay2 = create_test_peer_id("healthy")

        # Relay1: many failures
        for _ in range(10):
            tracker.record_connection_attempt(relay1, latency_ms=50.0, success=False)
        tracker.record_connection_attempt(relay1, latency_ms=50.0, success=True)

        # Relay2: mostly successes
        for _ in range(10):
            tracker.record_connection_attempt(relay2, latency_ms=100.0, success=True)

        result = tracker.select_best_relay([relay1, relay2])
        assert result == relay2

    def test_select_best_relay_considers_active_circuits(self):
        """Test that selection considers active circuit count."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("busy")
        relay2 = create_test_peer_id("idle")

        # Both have similar latency and success rate
        tracker.record_connection_attempt(relay1, latency_ms=100.0, success=True)
        tracker.record_connection_attempt(relay2, latency_ms=100.0, success=True)

        # Relay1 has more active circuits
        for _ in range(5):
            tracker.record_circuit_opened(relay1)
        tracker.record_circuit_opened(relay2)

        result = tracker.select_best_relay([relay1, relay2])
        assert result == relay2  # Should prefer less loaded relay

    def test_select_best_relay_with_reservation_requirement(self):
        """Test selection with reservation requirement."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("with_reservation")
        relay2 = create_test_peer_id("without_reservation")

        # Mock relay info getter
        def get_relay_info(relay_id):
            class MockRelayInfo:
                def __init__(self, has_reservation):
                    self.has_reservation = has_reservation

            if relay_id == relay1:
                return MockRelayInfo(has_reservation=True)
            elif relay_id == relay2:
                return MockRelayInfo(has_reservation=False)
            return None

        # Both relays have good stats
        tracker.record_connection_attempt(relay1, latency_ms=100.0, success=True)
        tracker.record_connection_attempt(relay2, latency_ms=50.0, success=True)

        # With reservation requirement, should pick relay1
        result = tracker.select_best_relay(
            [relay1, relay2],
            require_reservation=True,
            relay_info_getter=get_relay_info,
        )
        assert result == relay1

        # Without reservation requirement, should pick faster relay2
        result = tracker.select_best_relay(
            [relay1, relay2],
            require_reservation=False,
            relay_info_getter=get_relay_info,
        )
        assert result == relay2

    def test_select_best_relay_fallback_when_all_unhealthy(self):
        """Test fallback when all relays are unhealthy."""
        tracker = RelayPerformanceTracker(min_success_rate=0.5)
        relay1 = create_test_peer_id("unhealthy1")
        relay2 = create_test_peer_id("unhealthy2")

        # Both are unhealthy
        for _ in range(10):
            tracker.record_connection_attempt(relay1, latency_ms=50.0, success=False)
        for _ in range(10):
            tracker.record_connection_attempt(relay2, latency_ms=50.0, success=False)

        # Should fallback to first available (new relay with no stats)
        result = tracker.select_best_relay([relay1, relay2])
        # Since both are unhealthy, it should return the first one (fallback)
        assert result in [relay1, relay2]

    def test_get_all_relay_stats(self):
        """Test getting all relay statistics."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("relay1")
        relay2 = create_test_peer_id("relay2")

        tracker.record_connection_attempt(relay1, latency_ms=100.0, success=True)
        tracker.record_connection_attempt(relay2, latency_ms=200.0, success=True)

        all_stats = tracker.get_all_relay_stats()
        assert len(all_stats) == 2
        assert relay1 in all_stats
        assert relay2 in all_stats

    def test_export_metrics(self):
        """Test metrics export functionality."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("relay1")

        tracker.record_connection_attempt(relay1, latency_ms=100.0, success=True)
        tracker.record_circuit_opened(relay1)

        metrics = tracker.export_metrics()
        assert metrics["relays_tracked"] == 1
        assert "relay_metrics" in metrics
        assert str(relay1) in metrics["relay_metrics"]

        relay_metrics = metrics["relay_metrics"][str(relay1)]
        assert relay_metrics["latency_ema_ms"] == 100.0
        assert relay_metrics["success_count"] == 1
        assert relay_metrics["failure_count"] == 0
        assert relay_metrics["active_circuits"] == 1

    def test_reset(self):
        """Test resetting all tracking data."""
        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("relay1")

        tracker.record_connection_attempt(relay1, latency_ms=100.0, success=True)
        assert len(tracker.get_all_relay_stats()) == 1

        tracker.reset()
        assert len(tracker.get_all_relay_stats()) == 0

    def test_thread_safety(self):
        """Test that tracker operations are thread-safe."""
        import threading

        tracker = RelayPerformanceTracker()
        relay1 = create_test_peer_id("relay1")
        relay2 = create_test_peer_id("relay2")

        def record_attempts(relay_id, count):
            for _ in range(count):
                tracker.record_connection_attempt(
                    relay_id, latency_ms=100.0, success=True
                )
                tracker.record_circuit_opened(relay_id)

        # Run concurrent operations
        threads = []
        threads.append(threading.Thread(target=record_attempts, args=(relay1, 100)))
        threads.append(threading.Thread(target=record_attempts, args=(relay2, 100)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all operations completed
        stats1 = tracker.get_relay_stats(relay1)
        stats2 = tracker.get_relay_stats(relay2)

        assert stats1 is not None
        assert stats2 is not None
        assert stats1.success_count == 100
        assert stats2.success_count == 100
        assert stats1.active_circuits == 100
        assert stats2.active_circuits == 100
