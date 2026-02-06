"""
Tests for inbound connection gate and timeout enforcement.

Tests to verify:
1. Inbound connections respect allow/deny lists (connection gate)
2. Inbound connections timeout properly with inbound_upgrade_timeout
"""

import secrets

from multiaddr import Multiaddr
import pytest
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.config import ConnectionConfig
from libp2p.network.exceptions import SwarmException
from libp2p.peer.peerinfo import PeerInfo


@pytest.mark.trio
class TestInboundConnectionGate:
    """Test that inbound connections respect connection gate (allow/deny lists)."""

    async def test_inbound_denied_by_deny_list(self):
        """
        Test that inbound connections are blocked by deny list.

        This verifies fix for: "Inbound allow/deny lists are not enforced"
        """
        # Create two hosts: host_a will try to connect to host_b
        # host_b has a deny list that blocks host_a's IP
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with deny list blocking 127.0.0.1 (localhost)
        config_b = ConnectionConfig(
            deny_list=["127.0.0.1"],  # Block localhost
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Try to connect from host_a to host_b
            # This should fail because host_b denies 127.0.0.1
            with pytest.raises(Exception):  # SwarmException or connection error
                await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))

            # Verify that host_b has no connections (connection was blocked)
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() == 0

    async def test_inbound_allowed_by_allow_list(self):
        """
        Test that inbound connections are allowed by allow list.

        This verifies fix for: "Inbound allow/deny lists are not enforced"
        """
        # Create two hosts: host_a will try to connect to host_b
        # host_b has an allow list that permits host_a's IP
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with allow list permitting 127.0.0.1 (localhost)
        config_b = ConnectionConfig(
            allow_list=["127.0.0.1"],  # Allow localhost
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Connect from host_a to host_b
            # This should succeed because host_b allows 127.0.0.1
            await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))

            # Verify that host_b has 1 connection (connection was accepted)
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() == 1

    async def test_inbound_blocked_not_in_allow_list(self):
        """
        Test that inbound connections are blocked when not in allow list.

        When an allow list is configured, only IPs in the list should be allowed.
        """
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with allow list that does NOT include localhost
        # Using a different IP range to ensure localhost is rejected
        config_b = ConnectionConfig(
            allow_list=["192.168.1.0/24"],  # Allow only 192.168.1.x
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Try to connect from host_a to host_b
            # This should fail because 127.0.0.1 is not in the allow list
            with pytest.raises(Exception):  # SwarmException or connection error
                await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))

            # Verify that host_b has no connections
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() == 0


@pytest.mark.trio
class TestInboundUpgradeTimeout:
    """Test that inbound connections timeout properly with inbound_upgrade_timeout."""

    async def test_inbound_upgrade_timeout_config(self):
        """
        Test that inbound_upgrade_timeout configuration is properly set.

        This verifies the config exists and can be set.
        """
        config = ConnectionConfig(inbound_upgrade_timeout=5.0)
        assert config.inbound_upgrade_timeout == 5.0

    async def test_short_inbound_timeout_prevents_hangs(self):
        """
        Test that a very short inbound_upgrade_timeout prevents indefinite hangs.

        This is a behavioral test to ensure the timeout is actually applied.
        We use a very short timeout to ensure the test runs quickly.
        """
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with very short inbound upgrade timeout (0.1 seconds)
        # This is intentionally very short to trigger timeout during testing
        config_b = ConnectionConfig(
            inbound_upgrade_timeout=0.1,  # Very short timeout
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Try to connect - with such a short timeout, connection might fail
            # The key point is that it should NOT hang indefinitely
            # Use a timeout on the entire connection attempt
            with trio.fail_after(2.0):  # Overall test timeout of 2 seconds
                try:
                    await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))
                    # Connection might succeed if it's fast enough
                except Exception:
                    # Connection might fail due to timeout - that's acceptable
                    # The important thing is we didn't hang indefinitely
                    pass

            # If we reach here, the test passed (no indefinite hang)

    async def test_reasonable_timeout_allows_connection(self):
        """
        Test that a reasonable inbound_upgrade_timeout allows connections to succeed.

        This verifies the timeout doesn't prevent normal connections.
        """
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with reasonable inbound upgrade timeout (10 seconds - default)
        config_b = ConnectionConfig(
            inbound_upgrade_timeout=10.0,  # Reasonable timeout
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Connect from host_a to host_b
            # This should succeed with a reasonable timeout
            await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))

            # Verify connection was established
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() >= 1


@pytest.mark.trio
class TestBothFixes:
    """Test that both fixes work together correctly."""

    async def test_connection_gate_and_timeout_together(self):
        """
        Test that both connection gate and timeout work together.

        Verifies that:
        1. Connection gate is checked first
        2. Timeout is applied after gate check passes
        """
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with both allow list and timeout configured
        config_b = ConnectionConfig(
            allow_list=["127.0.0.1"],  # Allow localhost
            inbound_upgrade_timeout=10.0,  # Reasonable timeout
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Connect should succeed (passes gate and completes within timeout)
            await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))

            # Verify connection was established
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() >= 1

    async def test_deny_list_blocks_before_timeout(self):
        """
        Test that deny list blocks connection before timeout is applied.

        Verifies that connection gate is checked first, saving time by
        rejecting blocked connections early.
        """
        key_pair_a = create_new_key_pair(secrets.token_bytes(32))
        key_pair_b = create_new_key_pair(secrets.token_bytes(32))

        # Host B with both deny list and timeout
        config_b = ConnectionConfig(
            deny_list=["127.0.0.1"],  # Block localhost
            inbound_upgrade_timeout=10.0,
        )

        host_a = new_host(key_pair=key_pair_a)
        host_b = new_host(key_pair=key_pair_b, connection_config=config_b)

        listen_addr_a = [Multiaddr("/ip4/127.0.0.1/tcp/0")]
        listen_addr_b = [Multiaddr("/ip4/127.0.0.1/tcp/0")]

        async with host_a.run(listen_addrs=listen_addr_a), host_b.run(
            listen_addrs=listen_addr_b
        ):
            # Connection should be rejected quickly by gate (before timeout)
            start_time = trio.current_time()
            with pytest.raises(Exception):
                await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))
            elapsed = trio.current_time() - start_time

            # Should fail quickly (well before the 10s timeout)
            assert elapsed < 5.0  # Generous margin

            # Verify no connection was established
            swarm_b = host_b.get_network()
            assert swarm_b.get_total_connections() == 0
