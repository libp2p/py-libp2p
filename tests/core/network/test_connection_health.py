"""
Tests for connection health monitoring functionality.
"""

import time
from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.network.connection_health import (
    HealthConfig,
    create_default_connection_health,
)
from libp2p.network.swarm import ConnectionConfig, Swarm
from libp2p.peer.id import ID


class TestConnectionHealth:
    """Test ConnectionHealth dataclass functionality."""

    def test_create_default_connection_health(self):
        """Test creating default connection health."""
        health = create_default_connection_health()

        assert health.health_score == 1.0
        assert health.ping_success_rate == 1.0
        assert health.connection_stability == 1.0
        assert health.stream_count == 0
        assert health.failed_streams == 0

    def test_update_health_score(self):
        """Test health score calculation."""
        health = create_default_connection_health()

        # Simulate poor performance
        health.ping_latency = 500.0  # 500ms
        health.ping_success_rate = 0.5
        health.connection_stability = 0.3

        health.update_health_score()

        # Score should be lower due to poor metrics
        assert health.health_score < 1.0
        assert health.health_score > 0.0

    def test_update_ping_metrics(self):
        """Test ping metrics updates."""
        health = create_default_connection_health()

        # Update with successful ping
        health.update_ping_metrics(100.0, True)
        assert health.ping_latency == 100.0
        assert health.ping_success_rate > 0.5  # Should increase

        # Update with failed ping
        health.update_ping_metrics(200.0, False)
        assert health.ping_latency == 200.0
        assert health.ping_success_rate < 0.5  # Should decrease

    def test_update_stream_metrics(self):
        """Test stream metrics updates."""
        health = create_default_connection_health()

        # Update with successful stream creation
        health.update_stream_metrics(5, False)
        assert health.stream_count == 5
        assert health.failed_streams == 0

        # Update with failed stream
        health.update_stream_metrics(5, True)
        assert health.failed_streams == 1

    def test_is_healthy(self):
        """Test health threshold checking."""
        health = create_default_connection_health()

        # Default should be healthy
        assert health.is_healthy(0.3)

        # Make it unhealthy
        health.health_score = 0.2
        assert not health.is_healthy(0.3)

    def test_get_age_and_idle_time(self):
        """Test age and idle time calculations."""
        health = create_default_connection_health()

        # Wait a bit
        time.sleep(0.1)

        age = health.get_age()
        idle_time = health.get_idle_time()

        assert age > 0
        assert idle_time > 0
        assert abs(age - idle_time) < 0.01


class TestHealthConfig:
    """Test HealthConfig dataclass functionality."""

    def test_default_values(self):
        """Test default configuration values."""
        config = HealthConfig()

        assert config.health_check_interval == 60.0
        assert config.ping_timeout == 5.0
        assert config.min_health_threshold == 0.3
        assert config.min_connections_per_peer == 1

    def test_validation_errors(self):
        """Test configuration validation."""
        with pytest.raises(ValueError, match="must be positive"):
            HealthConfig(health_check_interval=-1)

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            HealthConfig(min_health_threshold=1.5)

        with pytest.raises(ValueError, match="at least 1"):
            HealthConfig(min_connections_per_peer=0)


class TestSwarmHealthMonitoring:
    """Test Swarm health monitoring integration."""

    @pytest.mark.trio
    async def test_health_monitoring_enabled(self):
        """Test that health monitoring can be enabled."""
        # Create mock dependencies
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        # Create connection config with health monitoring enabled
        connection_config = ConnectionConfig(
            enable_health_monitoring=True,
            health_check_interval=0.1,  # Fast for testing
            min_health_threshold=0.5,
        )

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Verify health monitoring infrastructure is initialized
        assert hasattr(swarm, "health_data")
        assert hasattr(swarm, "health_config")
        assert swarm.health_data == {}

        await swarm.close()

    @pytest.mark.trio
    async def test_health_monitoring_disabled(self):
        """Test that health monitoring can be disabled."""
        # Create mock dependencies
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        # Create connection config with health monitoring disabled
        connection_config = ConnectionConfig(enable_health_monitoring=False)

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Verify health monitoring is not initialized
        assert not hasattr(swarm, "health_data")

        await swarm.close()

    @pytest.mark.trio
    async def test_health_based_load_balancing(self):
        """Test health-based connection selection."""
        # Create mock dependencies
        peer_id = ID(b"QmTest")
        peerstore = Mock()
        upgrader = Mock()
        transport = AsyncMock()

        # Create connection config with health-based load balancing
        connection_config = ConnectionConfig(
            enable_health_monitoring=True, load_balancing_strategy="health_based"
        )

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, connection_config=connection_config
        )

        # Verify the strategy is set
        assert swarm.connection_config.load_balancing_strategy == "health_based"

        await swarm.close()
