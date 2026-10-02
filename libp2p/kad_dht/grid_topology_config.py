"""
Grid Topology Configuration

Configuration parameters for the grid topology routing table.
Simplified to include only parameters directly used by GridRoutingTable.
"""

from dataclasses import dataclass


@dataclass
class GridTopologyConfig:
    """
    Configuration for grid topology routing table.

    Includes only essential parameters for grid topology peer management.
    """

    # Bucket configuration - directly used by GridRoutingTable
    max_bucket_size: int = 20
    """Maximum number of peers per bucket (k-parameter in Kademlia)."""

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.max_bucket_size < 2:
            raise ValueError("max_bucket_size must be at least 2")


def get_default_config() -> GridTopologyConfig:
    """Get the default grid topology configuration."""
    return GridTopologyConfig(max_bucket_size=20)


def get_testing_config() -> GridTopologyConfig:
    """Get a configuration suitable for testing with smaller buckets."""
    return GridTopologyConfig(max_bucket_size=5)


def get_small_network_config() -> GridTopologyConfig:
    """Get a configuration for small networks (local testing)."""
    return GridTopologyConfig(max_bucket_size=10)


def get_large_network_config() -> GridTopologyConfig:
    """Get a configuration for large networks (production)."""
    return GridTopologyConfig(max_bucket_size=20)
