#!/usr/bin/env python3
"""
Example demonstrating allow/deny lists for connection gating.

This example shows how to:
1. Configure allow lists (whitelist)
2. Configure deny lists (blacklist)
3. Use CIDR blocks for network ranges
4. Understand precedence rules
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_allow_list() -> None:
    """Example of allow list configuration."""
    logger.info("=" * 60)
    logger.info("Example: Allow List (Whitelist)")
    logger.info("=" * 60)

    # Configure allow list
    connection_config = ConnectionConfig(
        allow_list=[
            "192.168.1.0/24",  # Local network
            "10.0.0.1",  # Specific IP
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Allow list configuration:")
    logger.info("  - IPs/networks in allow list are always allowed")
    logger.info("  - Bypasses max_connections limit")
    logger.info("  - Never pruned by connection pruner")
    logger.info(f"  - Current allow list: {connection_config.allow_list}")

    await swarm.close()
    logger.info("Allow list example completed\n")


async def example_deny_list() -> None:
    """Example of deny list configuration."""
    logger.info("=" * 60)
    logger.info("Example: Deny List (Blacklist)")
    logger.info("=" * 60)

    # Configure deny list
    connection_config = ConnectionConfig(
        deny_list=[
            "192.168.1.100",  # Specific blocked IP
            "10.0.0.0/8",  # Block entire network
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Deny list configuration:")
    logger.info("  - IPs/networks in deny list are always rejected")
    logger.info("  - Takes precedence over allow list")
    logger.info("  - Connections are rejected immediately")
    logger.info(f"  - Current deny list: {connection_config.deny_list}")

    await swarm.close()
    logger.info("Deny list example completed\n")


async def example_cidr_blocks() -> None:
    """Example of using CIDR blocks for network ranges."""
    logger.info("=" * 60)
    logger.info("Example: CIDR Blocks")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(
        allow_list=[
            "192.168.0.0/16",  # All 192.168.x.x addresses
            "10.0.0.0/8",  # All 10.x.x.x addresses
            "172.16.0.0/12",  # Private network range
        ],
        deny_list=[
            "192.168.1.100/32",  # Specific IP (explicit /32)
            "10.0.0.0/24",  # Block specific subnet
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("CIDR block examples:")
    logger.info("  - /16: 65,536 addresses (192.168.0.0 - 192.168.255.255)")
    logger.info("  - /24: 256 addresses (192.168.1.0 - 192.168.1.255)")
    logger.info("  - /32: Single IP address")
    logger.info("  - Supports both IPv4 and IPv6")

    await swarm.close()
    logger.info("CIDR blocks example completed\n")


async def example_precedence_rules() -> None:
    """Example demonstrating allow/deny list precedence."""
    logger.info("=" * 60)
    logger.info("Example: Precedence Rules")
    logger.info("=" * 60)

    # Both allow and deny lists
    connection_config = ConnectionConfig(
        allow_list=["192.168.1.0/24"],
        deny_list=["192.168.1.100"],  # This is in the allow list range
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Precedence rules:")
    logger.info("  1. Deny list is checked FIRST")
    logger.info("  2. If IP is in deny list → REJECTED")
    logger.info("  3. If IP is in allow list → ALLOWED (bypasses limits)")
    logger.info("  4. Otherwise → Normal connection rules apply")
    logger.info("\nExample:")
    logger.info("  - 192.168.1.100 is in both lists")
    logger.info("  - Result: REJECTED (deny takes precedence)")

    await swarm.close()
    logger.info("Precedence rules example completed\n")


async def example_production_allow_deny() -> None:
    """Example of production-ready allow/deny list configuration."""
    logger.info("=" * 60)
    logger.info("Example: Production Configuration")
    logger.info("=" * 60)

    # Production scenario: Allow trusted networks, deny known bad actors
    # Example configuration (not used in this demo, just shown)
    _example_config = ConnectionConfig(
        allow_list=[
            "10.0.0.0/8",  # Internal network
            "172.16.0.0/12",  # Private network
            "192.168.0.0/16",  # Local network
        ],
        deny_list=[
            "0.0.0.0/0",  # Block all (if you want to be very restrictive)
            # In practice, you'd list specific bad IPs
        ],
        max_connections=300,
    )

    logger.info("Production configuration example:")
    logger.info("  - Allow trusted internal networks")
    logger.info("  - Deny known malicious IPs")
    logger.info("  - Use CIDR blocks for efficiency")
    logger.info("  - Combine with connection limits")

    logger.info("\nBest practices:")
    logger.info("  - Keep allow lists small and specific")
    logger.info("  - Regularly update deny lists")
    logger.info("  - Monitor connection attempts")
    logger.info("  - Use CIDR blocks for network ranges")


async def main() -> None:
    """Run all allow/deny list examples."""
    logger.info("\n" + "=" * 60)
    logger.info("Allow/Deny Lists Examples")
    logger.info("=" * 60 + "\n")

    try:
        await example_allow_list()
        await example_deny_list()
        await example_cidr_blocks()
        await example_precedence_rules()
        await example_production_allow_deny()

        logger.info("=" * 60)
        logger.info("All allow/deny list examples completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)
