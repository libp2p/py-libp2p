"""
Tests for host-level health monitoring API.

Tests the API consistency fix that allows new_host() to accept
connection_config and provides health monitoring through the host interface.
"""

from typing import cast

import pytest

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.network.config import ConnectionConfig
from libp2p.network.swarm import Swarm
from libp2p.transport.quic.config import QUICTransportConfig


@pytest.mark.trio
async def test_new_host_with_connection_config() -> None:
    """Test new_host() accepts connection_config parameter."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=60.0,
        load_balancing_strategy="health_based",
        max_connections_per_peer=3,
    )

    # Create host with connection config
    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    # Verify host created successfully
    assert host is not None

    # Verify swarm has correct config
    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm.connection_config.health_check_interval == 60.0
    assert swarm.connection_config.load_balancing_strategy == "health_based"
    assert swarm.connection_config.max_connections_per_peer == 3

    await host.close()


@pytest.mark.trio
async def test_new_host_backward_compatibility() -> None:
    """Test new_host() still works without connection_config."""
    # Create host without connection_config (old API)
    host = new_host(key_pair=create_new_key_pair())

    # Verify host created with defaults
    assert host is not None

    # Verify default config applied
    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.enable_health_monitoring is False  # Default
    assert swarm.connection_config.load_balancing_strategy == "round_robin"  # Default

    await host.close()


@pytest.mark.trio
async def test_new_host_health_monitoring_disabled_explicitly() -> None:
    """Test new_host() with explicitly disabled health monitoring."""
    config = ConnectionConfig(
        enable_health_monitoring=False, load_balancing_strategy="least_loaded"
    )

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    # Verify health monitoring disabled
    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.enable_health_monitoring is False
    assert swarm._is_health_monitoring_enabled is False

    await host.close()


@pytest.mark.trio
async def test_new_host_health_based_strategy() -> None:
    """Test new_host() with health-based load balancing."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        load_balancing_strategy="health_based",
        min_health_threshold=0.4,
    )

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.load_balancing_strategy == "health_based"
    assert swarm.connection_config.min_health_threshold == 0.4
    assert swarm._is_health_monitoring_enabled is True

    await host.close()


@pytest.mark.trio
async def test_new_host_latency_based_strategy() -> None:
    """Test new_host() with latency-based load balancing."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        load_balancing_strategy="latency_based",
        max_ping_latency=500.0,
    )

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.load_balancing_strategy == "latency_based"
    assert swarm.connection_config.max_ping_latency == 500.0

    await host.close()


@pytest.mark.trio
async def test_new_host_custom_health_parameters() -> None:
    """Test new_host() with custom health monitoring parameters."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        health_initial_delay=5.0,
        health_warmup_window=10.0,
        ping_timeout=3.0,
        min_health_threshold=0.5,
        min_connections_per_peer=2,
        latency_weight=0.5,
        success_rate_weight=0.3,
        stability_weight=0.2,
        max_ping_latency=1000.0,
        min_ping_success_rate=0.8,
        max_failed_streams=10,
        unhealthy_grace_period=5,
    )

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())

    # Verify all custom parameters applied
    assert swarm.connection_config.health_check_interval == 30.0
    assert swarm.connection_config.health_initial_delay == 5.0
    assert swarm.connection_config.health_warmup_window == 10.0
    assert swarm.connection_config.ping_timeout == 3.0
    assert swarm.connection_config.min_health_threshold == 0.5
    assert swarm.connection_config.min_connections_per_peer == 2
    assert swarm.connection_config.latency_weight == 0.5
    assert swarm.connection_config.success_rate_weight == 0.3
    assert swarm.connection_config.stability_weight == 0.2
    assert swarm.connection_config.max_ping_latency == 1000.0
    assert swarm.connection_config.min_ping_success_rate == 0.8
    assert swarm.connection_config.max_failed_streams == 10
    assert swarm.connection_config.unhealthy_grace_period == 5

    await host.close()


@pytest.mark.trio
async def test_new_host_quic_without_connection_config() -> None:
    """Test new_host() with QUIC but no additional connection_config."""
    quic_config = QUICTransportConfig(
        enable_health_monitoring=True, health_check_interval=45.0
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
    )

    # Verify QUIC config used
    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm.connection_config.health_check_interval == 45.0

    await host.close()


@pytest.mark.trio
async def test_new_host_quic_config_merge() -> None:
    """Test connection_config merged with QUIC config when both provided."""
    quic_config = QUICTransportConfig(
        enable_health_monitoring=False, health_check_interval=30.0
    )

    connection_config = ConnectionConfig(
        enable_health_monitoring=True,  # Should override QUIC config
        health_check_interval=60.0,  # Should override QUIC config
        load_balancing_strategy="health_based",
        max_connections_per_peer=5,
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
        connection_config=connection_config,
    )

    swarm = cast(Swarm, host.get_network())

    # Verify health settings from connection_config merged into QUIC config
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm.connection_config.health_check_interval == 60.0
    assert swarm.connection_config.load_balancing_strategy == "health_based"
    assert swarm.connection_config.max_connections_per_peer == 5

    await host.close()


@pytest.mark.trio
async def test_new_host_quic_config_merge_all_attributes() -> None:
    """Test ALL ConnectionConfig attributes are merged when both configs provided."""
    # Create QUIC config with default ConnectionConfig values
    quic_config = QUICTransportConfig()

    # Create connection_config with ALL custom values (different from defaults)
    connection_config = ConnectionConfig(
        max_connections_per_peer=7,
        connection_timeout=45.0,
        load_balancing_strategy="latency_based",
        enable_health_monitoring=True,
        health_initial_delay=15.0,
        health_warmup_window=10.0,
        health_check_interval=45.0,
        ping_timeout=3.0,
        min_health_threshold=0.5,
        min_connections_per_peer=2,
        latency_weight=0.5,
        success_rate_weight=0.3,
        stability_weight=0.2,
        max_ping_latency=800.0,
        min_ping_success_rate=0.8,
        max_failed_streams=10,
        unhealthy_grace_period=5,
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
        connection_config=connection_config,
    )

    swarm = cast(Swarm, host.get_network())
    cfg = swarm.connection_config

    # Verify ALL 17 ConnectionConfig attributes were merged
    assert cfg.max_connections_per_peer == 7
    assert cfg.connection_timeout == 45.0
    assert cfg.load_balancing_strategy == "latency_based"
    assert cfg.enable_health_monitoring is True
    assert cfg.health_initial_delay == 15.0
    assert cfg.health_warmup_window == 10.0
    assert cfg.health_check_interval == 45.0
    assert cfg.ping_timeout == 3.0
    assert cfg.min_health_threshold == 0.5
    assert cfg.min_connections_per_peer == 2
    assert cfg.latency_weight == 0.5
    assert cfg.success_rate_weight == 0.3
    assert cfg.stability_weight == 0.2
    assert cfg.max_ping_latency == 800.0
    assert cfg.min_ping_success_rate == 0.8
    assert cfg.max_failed_streams == 10
    assert cfg.unhealthy_grace_period == 5

    await host.close()


@pytest.mark.trio
async def test_new_host_non_quic_with_connection_config() -> None:
    """Test new_host() with connection_config but QUIC disabled."""
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=60.0,
        load_balancing_strategy="latency_based",
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=False,
        connection_config=connection_config,
    )

    swarm = cast(Swarm, host.get_network())

    # Verify connection_config used directly
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm.connection_config.health_check_interval == 60.0
    assert swarm.connection_config.load_balancing_strategy == "latency_based"

    await host.close()


@pytest.mark.trio
async def test_new_host_health_monitoring_with_multiple_strategies() -> None:
    """Test different load balancing strategies can be configured."""
    strategies = ["round_robin", "least_loaded", "health_based", "latency_based"]

    for strategy in strategies:
        config = ConnectionConfig(
            enable_health_monitoring=(
                True if strategy in ["health_based", "latency_based"] else False
            ),
            load_balancing_strategy=strategy,
        )

        host = new_host(key_pair=create_new_key_pair(), connection_config=config)

        swarm = cast(Swarm, host.get_network())
        assert swarm.connection_config.load_balancing_strategy == strategy

        await host.close()


@pytest.mark.trio
async def test_new_host_config_none_uses_defaults() -> None:
    """Test new_host() with connection_config=None uses defaults."""
    host = new_host(key_pair=create_new_key_pair(), connection_config=None)

    swarm = cast(Swarm, host.get_network())

    # Verify default config created
    assert swarm.connection_config is not None
    assert swarm.connection_config.enable_health_monitoring is False
    assert swarm.connection_config.max_connections_per_peer == 3
    assert swarm.connection_config.load_balancing_strategy == "round_robin"

    await host.close()


@pytest.mark.trio
async def test_new_host_preserves_other_parameters() -> None:
    """Test new_host() preserves other parameters when connection_config added."""
    config = ConnectionConfig(enable_health_monitoring=True)

    # Test with various other parameters
    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=config,
        enable_mDNS=False,
        bootstrap=None,
        negotiate_timeout=60,
    )

    # Verify host created successfully with all parameters
    assert host is not None
    swarm = cast(Swarm, host.get_network())
    assert swarm.connection_config.enable_health_monitoring is True

    await host.close()


@pytest.mark.trio
async def test_new_host_health_config_independent_per_host() -> None:
    """Test each host can have independent health monitoring configuration."""
    config1 = ConnectionConfig(
        enable_health_monitoring=True, health_check_interval=30.0
    )

    config2 = ConnectionConfig(
        enable_health_monitoring=True, health_check_interval=60.0
    )

    host1 = new_host(key_pair=create_new_key_pair(), connection_config=config1)
    host2 = new_host(key_pair=create_new_key_pair(), connection_config=config2)

    swarm1 = cast(Swarm, host1.get_network())
    swarm2 = cast(Swarm, host2.get_network())

    # Verify independent configurations
    assert swarm1.connection_config.health_check_interval == 30.0
    assert swarm2.connection_config.health_check_interval == 60.0

    await host1.close()
    await host2.close()


@pytest.mark.trio
async def test_new_host_health_data_structure_initialized() -> None:
    """Test health data structure properly initialized when enabled."""
    config = ConnectionConfig(enable_health_monitoring=True)

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())

    # Verify health data structure exists
    assert hasattr(swarm, "health_data")
    assert isinstance(swarm.health_data, dict)
    assert len(swarm.health_data) == 0  # Empty initially

    await host.close()


@pytest.mark.trio
async def test_new_host_health_data_not_initialized_when_disabled() -> None:
    """Test health monitoring not initialized when disabled."""
    config = ConnectionConfig(enable_health_monitoring=False)

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())

    # Verify health monitoring is disabled
    assert swarm._is_health_monitoring_enabled is False

    await host.close()


@pytest.mark.trio
async def test_new_host_quic_config_warning_when_quic_disabled() -> None:
    """Test warning behavior when QUIC config provided but QUIC disabled."""
    # This test documents the expected behavior but doesn't test the warning itself
    quic_config = QUICTransportConfig(enable_health_monitoring=True)

    # Should not raise exception, just log warning
    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=False,  # QUIC disabled
        quic_transport_opt=quic_config,  # But config provided
    )

    assert host is not None

    await host.close()


@pytest.mark.trio
async def test_new_host_full_configuration_lifecycle() -> None:
    """Test full lifecycle with health monitoring configuration."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        load_balancing_strategy="health_based",
        max_connections_per_peer=3,
        min_connections_per_peer=1,
    )

    # Create host
    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())

    # Verify configuration applied
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm._is_health_monitoring_enabled is True

    # Verify health monitor created
    assert hasattr(swarm, "_health_monitor")

    # Close host
    await host.close()

    # After close, host should be in clean state
    assert host is not None  # Object still exists


@pytest.mark.trio
async def test_new_host_connection_config_dataclass_fields() -> None:
    """Test all ConnectionConfig fields are properly passed through."""
    config = ConnectionConfig(
        max_connections_per_peer=5,
        connection_timeout=45.0,
        load_balancing_strategy="health_based",
        enable_health_monitoring=True,
        health_initial_delay=10.0,
        health_warmup_window=8.0,
        health_check_interval=40.0,
        ping_timeout=4.0,
        min_health_threshold=0.4,
        min_connections_per_peer=2,
        latency_weight=0.6,
        success_rate_weight=0.2,
        stability_weight=0.2,
        max_ping_latency=800.0,
        min_ping_success_rate=0.75,
        max_failed_streams=8,
        unhealthy_grace_period=4,
    )

    host = new_host(key_pair=create_new_key_pair(), connection_config=config)

    swarm = cast(Swarm, host.get_network())
    cfg = swarm.connection_config

    # Verify every field
    assert cfg.max_connections_per_peer == 5
    assert cfg.connection_timeout == 45.0
    assert cfg.load_balancing_strategy == "health_based"
    assert cfg.enable_health_monitoring is True
    assert cfg.health_initial_delay == 10.0
    assert cfg.health_warmup_window == 8.0
    assert cfg.health_check_interval == 40.0
    assert cfg.ping_timeout == 4.0
    assert cfg.min_health_threshold == 0.4
    assert cfg.min_connections_per_peer == 2
    assert cfg.latency_weight == 0.6
    assert cfg.success_rate_weight == 0.2
    assert cfg.stability_weight == 0.2
    assert cfg.max_ping_latency == 800.0
    assert cfg.min_ping_success_rate == 0.75
    assert cfg.max_failed_streams == 8
    assert cfg.unhealthy_grace_period == 4

    await host.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
