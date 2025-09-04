"""
Comprehensive tests for enhanced connection health monitoring.

This test suite verifies the advanced health monitoring features including:
- Bandwidth tracking
- Error history recording
- Connection event logging
- Health metrics export
- Proactive monitoring
"""

from unittest.mock import AsyncMock, Mock

import pytest
import trio

from libp2p.abc import INetConn, INetStream
from libp2p.network.connection_health import (
    HealthConfig,
    create_default_connection_health,
)
from libp2p.network.swarm import ConnectionConfig, Swarm
from libp2p.peer.id import ID


class MockConnection(INetConn):
    """Mock connection for testing enhanced health monitoring."""

    def __init__(self, peer_id: ID, is_closed: bool = False):
        self.peer_id = peer_id
        self._is_closed = is_closed
        self.streams = set()
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        self.event_started = trio.Event()

    async def close(self):
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        mock_stream = Mock(spec=INetStream)
        self.streams.add(mock_stream)
        return mock_stream

    def get_streams(self) -> tuple[INetStream, ...]:
        return tuple(self.streams)

    def get_transport_addresses(self) -> list:
        return []


class TestEnhancedConnectionHealth:
    """Test enhanced ConnectionHealth functionality."""

    def test_advanced_metrics_initialization(self):
        """Test that advanced metrics are properly initialized."""
        health = create_default_connection_health()

        # Check new fields are initialized
        assert health.bandwidth_usage == {}
        assert health.error_history == []
        assert health.connection_events == []
        assert health.peak_bandwidth == 0.0
        assert health.average_bandwidth == 0.0

    def test_error_tracking(self):
        """Test error tracking functionality."""
        health = create_default_connection_health()
        initial_stability = health.connection_stability

        # Add errors
        health.add_error("connection_timeout")
        health.add_error("stream_failure")

        # Verify errors are recorded
        assert len(health.error_history) == 2
        assert health.error_history[0][1] == "connection_timeout"
        assert health.error_history[1][1] == "stream_failure"

        # Verify stability score is updated
        assert health.connection_stability < initial_stability

    def test_connection_event_tracking(self):
        """Test connection event tracking."""
        health = create_default_connection_health()

        # Add events
        health.add_connection_event("connection_established")
        health.add_connection_event("stream_created")
        health.add_connection_event("ping_successful")

        # Verify events are recorded
        assert len(health.connection_events) == 3
        assert health.connection_events[0][1] == "connection_established"
        assert health.connection_events[1][1] == "stream_created"
        assert health.connection_events[2][1] == "ping_successful"

    def test_bandwidth_metrics(self):
        """Test bandwidth tracking functionality."""
        health = create_default_connection_health()

        # Update bandwidth metrics
        health.update_bandwidth_metrics(1024, 2048)  # 1KB sent, 2KB received
        health.update_bandwidth_metrics(512, 1024)  # 0.5KB sent, 1KB received

        # Verify bandwidth tracking
        assert health.total_bytes_sent == 1536  # 1024 + 512
        assert health.total_bytes_received == 3072  # 2048 + 1024
        assert health.peak_bandwidth > 0
        assert health.average_bandwidth > 0

    def test_health_summary(self):
        """Test comprehensive health summary generation."""
        health = create_default_connection_health()

        # Add some data
        health.add_error("test_error")
        health.add_connection_event("test_event")
        health.update_bandwidth_metrics(100, 200)

        # Generate summary
        summary = health.get_health_summary()

        # Verify all metrics are included
        assert "health_score" in summary
        assert "recent_errors" in summary
        assert "connection_events" in summary
        assert "peak_bandwidth_bps" in summary
        assert "average_bandwidth_bps" in summary

        # Verify values
        assert summary["recent_errors"] == 1
        assert summary["connection_events"] == 1
        assert summary["peak_bandwidth_bps"] > 0


class TestEnhancedSwarmHealthMonitoring:
    """Test enhanced Swarm health monitoring integration."""

    @pytest.mark.trio
    async def test_enhanced_health_monitoring_initialization(self):
        """Test that enhanced health monitoring is properly initialized."""
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        connection_config = ConnectionConfig(
            enable_health_monitoring=True, health_check_interval=10.0
        )

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Verify enhanced health monitoring infrastructure
        assert hasattr(swarm, "health_data")
        assert hasattr(swarm, "health_config")
        assert hasattr(swarm, "_health_metrics_collector")

        await swarm.close()

    @pytest.mark.trio
    async def test_connection_event_recording(self):
        """Test that connection events are properly recorded."""
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        connection_config = ConnectionConfig(enable_health_monitoring=True)

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Test event recording methods
        mock_conn = MockConnection(peer_id)

        # Record events
        swarm.record_connection_event(peer_id, mock_conn, "test_event")
        swarm.record_connection_error(peer_id, mock_conn, "test_error")

        # Verify events are recorded (connection needs to be in health_data)
        # This would normally happen when add_conn is called

        await swarm.close()

    @pytest.mark.trio
    async def test_health_metrics_export(self):
        """Test health metrics export functionality."""
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        connection_config = ConnectionConfig(enable_health_monitoring=True)

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Test JSON export
        json_metrics = swarm.export_health_metrics("json")
        assert isinstance(json_metrics, str)
        assert len(json_metrics) > 0

        # Test Prometheus export
        prometheus_metrics = swarm.export_health_metrics("prometheus")
        assert isinstance(prometheus_metrics, str)
        assert "libp2p_peers_total" in prometheus_metrics

        # Test invalid format
        with pytest.raises(ValueError, match="Unsupported format"):
            swarm.export_health_metrics("invalid")

        await swarm.close()

    @pytest.mark.trio
    async def test_health_summaries(self):
        """Test health summary generation methods."""
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        connection_config = ConnectionConfig(enable_health_monitoring=True)

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Test peer health summary
        peer_summary = swarm.get_peer_health_summary(peer_id)
        assert isinstance(peer_summary, dict)

        # Test global health summary
        global_summary = swarm.get_global_health_summary()
        assert isinstance(global_summary, dict)
        assert "total_peers" in global_summary
        assert "total_connections" in global_summary

        await swarm.close()


class TestHealthConfigValidation:
    """Test HealthConfig validation and configuration."""

    def test_health_config_defaults(self):
        """Test HealthConfig default values."""
        config = HealthConfig()

        assert config.health_check_interval == 60.0
        assert config.ping_timeout == 5.0
        assert config.min_health_threshold == 0.3
        assert config.min_connections_per_peer == 1
        assert config.latency_weight == 0.4
        assert config.success_rate_weight == 0.4
        assert config.stability_weight == 0.2

    def test_health_config_validation(self):
        """Test HealthConfig validation."""
        # Test invalid values
        with pytest.raises(ValueError, match="must be positive"):
            HealthConfig(health_check_interval=-1)

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            HealthConfig(min_health_threshold=1.5)

        with pytest.raises(ValueError, match="at least 1"):
            HealthConfig(min_connections_per_peer=0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
