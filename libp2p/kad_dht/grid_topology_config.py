"""
Grid Topology Configuration

Configuration parameters for the grid topology routing table,
matching the cpp-libp2p Kademlia DHT configuration.
"""

from dataclasses import dataclass


@dataclass
class GridTopologyConfig:
    """
    Configuration for grid topology routing table.

    Matches cpp-libp2p's Kademlia configuration structure.
    """

    d_min: int = 5

    d_max: int = 10

    max_bucket_size: int = 20

    ideal_connections_num: int = 100

    max_connections_num: int = 1000

    max_message_size: int = 1 << 24

    rw_timeout_msec: int = 10000

    connection_timeout_msec: int = 3000

    response_timeout_msec: int = 10000

    heartbeat_interval_msec: int = 1000

    ban_interval_msec: int = 60000

    max_dial_attempts: int = 3

    address_expiration_msec: int = 3600000

    query_initial_peers: int = 20

    replication_factor: int = 20

    closer_peer_count: int = 6

    request_concurrency: int = 3

    value_lookups_quorum: int = 0

    floodsub_forward_mode: bool = False

    echo_forward_mode: bool = False

    sign_messages: bool = False

    storage_record_ttl_sec: int = 86400

    storage_wiping_interval_sec: int = 3600

    storage_refresh_interval_sec: int = 300

    provider_record_ttl_sec: int = 86400

    provider_wiping_interval_sec: int = 3600

    max_providers_per_key: int = 6

    random_walk_enabled: bool = True

    random_walk_queries_per_period: int = 1

    random_walk_interval_sec: int = 30

    random_walk_timeout_sec: int = 10

    random_walk_delay_sec: int = 10

    periodic_replication_enabled: bool = True

    periodic_replication_interval_sec: int = 3600

    periodic_replication_peers_per_cycle: int = 3

    periodic_republishing_enabled: bool = True

    periodic_republishing_interval_sec: int = 86400

    periodic_republishing_peers_per_cycle: int = 6

    protocol_id: str = "/ipfs/kad/1.0.0"

    passive_mode: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.max_bucket_size < 2:
            raise ValueError("max_bucket_size must be at least 2")
        if self.d_min > self.d_max:
            raise ValueError("d_min must be <= d_max")
        if self.max_bucket_size < self.d_min:
            raise ValueError("max_bucket_size must be >= d_min")


DEFAULT_CONFIG = GridTopologyConfig()


def get_default_config() -> GridTopologyConfig:
    """Get the default grid topology configuration."""
    return GridTopologyConfig()


def get_testing_config() -> GridTopologyConfig:
    """Get a configuration suitable for testing with smaller buckets."""
    return GridTopologyConfig(
        max_bucket_size=5,
        ideal_connections_num=10,
        max_connections_num=50,
        d_min=2,
        d_max=3,
    )


def get_small_network_config() -> GridTopologyConfig:
    """Get a configuration for small networks (local testing)."""
    return GridTopologyConfig(
        max_bucket_size=10,
        ideal_connections_num=20,
        max_connections_num=100,
        heartbeat_interval_msec=500,
    )


def get_large_network_config() -> GridTopologyConfig:
    """Get a configuration for large networks (production)."""
    return GridTopologyConfig(
        max_bucket_size=20,
        ideal_connections_num=100,
        max_connections_num=1000,
        request_concurrency=4,
        closer_peer_count=8,
    )
