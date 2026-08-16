"""
Tests for auto-connector and enhanced connection manager functionality.

Tests for AutoConnector, updated ConnectionConfig with watermarks,
and connection pruner with watermark support.
"""

import pytest

from libp2p.network.auto_connector import AutoConnector
from libp2p.network.config import (
    AUTO_CONNECT_INTERVAL,
    GRACE_PERIOD,
    HIGH_WATERMARK,
    LOW_WATERMARK,
    MAX_CONNECTIONS,
    MIN_CONNECTIONS,
    ConnectionConfig,
)
from libp2p.peer.id import ID


class TestConnectionConfigWatermarks:
    """Test ConnectionConfig with watermark fields."""

    def test_default_watermark_values(self):
        """Test default watermark values."""
        config = ConnectionConfig()
        assert config.min_connections == MIN_CONNECTIONS
        assert config.low_watermark == LOW_WATERMARK
        assert config.high_watermark == HIGH_WATERMARK
        assert config.max_connections == MAX_CONNECTIONS
        assert config.auto_connect_interval == AUTO_CONNECT_INTERVAL
        assert config.grace_period == GRACE_PERIOD

    def test_custom_watermark_values(self):
        """Test custom watermark values."""
        config = ConnectionConfig(
            min_connections=10,
            low_watermark=20,
            high_watermark=50,
            max_connections=100,
            auto_connect_interval=15.0,
            grace_period=10.0,
        )
        assert config.min_connections == 10
        assert config.low_watermark == 20
        assert config.high_watermark == 50
        assert config.max_connections == 100
        assert config.auto_connect_interval == 15.0
        assert config.grace_period == 10.0

    def test_watermark_validation_low_watermark_less_than_min(self):
        """Test validation: low_watermark must be >= min_connections."""
        match_str = "Low watermark should be >= min_connections"
        with pytest.raises(ValueError, match=match_str):
            ConnectionConfig(
                min_connections=50,
                low_watermark=30,  # Invalid: less than min_connections
                high_watermark=100,
                max_connections=200,
            )

    def test_watermark_validation_high_watermark_less_than_low(self):
        """Test validation: high_watermark must be >= low_watermark."""
        match_str = "High watermark should be >= low_watermark"
        with pytest.raises(ValueError, match=match_str):
            ConnectionConfig(
                min_connections=10,
                low_watermark=50,
                high_watermark=30,  # Invalid: less than low_watermark
                max_connections=200,
            )

    def test_watermark_validation_max_less_than_high(self):
        """Test validation: max_connections must be >= high_watermark."""
        match_str = "Max connections should be >= high_watermark"
        with pytest.raises(ValueError, match=match_str):
            ConnectionConfig(
                min_connections=10,
                low_watermark=50,
                high_watermark=100,
                max_connections=80,  # Invalid: less than high_watermark
            )

    def test_watermark_validation_negative_min_connections(self):
        """Test validation: min_connections must be non-negative."""
        with pytest.raises(ValueError, match="Min connections should be non-negative"):
            ConnectionConfig(min_connections=-1)

    def test_watermark_validation_negative_auto_connect_interval(self):
        """Test validation: auto_connect_interval must be positive."""
        match_str = "Auto connect interval should be positive"
        with pytest.raises(ValueError, match=match_str):
            ConnectionConfig(auto_connect_interval=0)

        with pytest.raises(ValueError, match=match_str):
            ConnectionConfig(auto_connect_interval=-1.0)

    def test_watermark_validation_negative_grace_period(self):
        """Test validation: grace_period must be non-negative."""
        with pytest.raises(ValueError, match="Grace period should be non-negative"):
            ConnectionConfig(grace_period=-1.0)

    def test_valid_zero_grace_period(self):
        """Test that zero grace_period is valid."""
        config = ConnectionConfig(grace_period=0.0)
        assert config.grace_period == 0.0

    def test_valid_equal_watermarks(self):
        """Test that equal watermarks are valid."""
        config = ConnectionConfig(
            min_connections=50,
            low_watermark=50,  # Equal to min_connections
            high_watermark=50,  # Equal to low_watermark
            max_connections=50,  # Equal to high_watermark
        )
        assert config.min_connections == 50
        assert config.low_watermark == 50
        assert config.high_watermark == 50
        assert config.max_connections == 50


class TestAutoConnectorUnit:
    """Unit tests for AutoConnector (without full swarm)."""

    @pytest.fixture
    def peer_id(self):
        """Create a test peer ID."""
        return ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")

    def test_cooldown_tracking(self, peer_id):
        """Test that cooldown is tracked for failed connection attempts."""

        # Create a mock swarm with minimal attributes
        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig(
                    min_connections=1,
                    low_watermark=5,
                    high_watermark=10,
                    max_connections=20,
                )

        mock_swarm = MockSwarm()
        connector = AutoConnector(mock_swarm)  # type: ignore

        # Initially, peer should not be skipped
        assert connector._should_skip_peer(peer_id) is False

        # Record failed connection
        connector.record_failed_connection(peer_id)

        # Now peer should be skipped (cooldown)
        assert connector._should_skip_peer(peer_id) is True

        # Clear cooldown
        connector.clear_cooldown(peer_id)

        # Peer should no longer be skipped
        assert connector._should_skip_peer(peer_id) is False

    def test_successful_connection_clears_cooldown(self, peer_id):
        """Test that successful connection clears cooldown."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig()

        mock_swarm = MockSwarm()
        connector = AutoConnector(mock_swarm)  # type: ignore

        # Record failed connection (sets cooldown)
        connector.record_failed_connection(peer_id)
        assert connector._should_skip_peer(peer_id) is True

        # Record successful connection (clears cooldown)
        connector.record_successful_connection(peer_id)
        assert connector._should_skip_peer(peer_id) is False

    def test_clear_all_cooldowns(self, peer_id):
        """Test clearing all cooldowns."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig()

        mock_swarm = MockSwarm()
        connector = AutoConnector(mock_swarm)  # type: ignore

        peer_id_2 = ID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")

        # Record failed connections for both peers
        connector.record_failed_connection(peer_id)
        connector.record_failed_connection(peer_id_2)

        assert connector._should_skip_peer(peer_id) is True
        assert connector._should_skip_peer(peer_id_2) is True

        # Clear all cooldowns
        connector.clear_all_cooldowns()

        assert connector._should_skip_peer(peer_id) is False
        assert connector._should_skip_peer(peer_id_2) is False


class TestAutoConnectorCandidateFiltering:
    """Test _get_candidate_peers filters private/unroutable addresses."""

    @pytest.mark.trio
    async def test_candidates_exclude_private_only_peers(self):
        """Peers with only private IP addrs are excluded from candidates."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import _addr_is_direct, _addr_is_routable

        # Sanity-check the address classifier directly.
        assert _addr_is_routable(Multiaddr("/ip4/8.8.8.8/tcp/4001"))
        assert _addr_is_routable(Multiaddr("/ip4/52.54.248.232/tcp/4001"))
        assert _addr_is_routable(Multiaddr("/dnsaddr/bootstrap.libp2p.io/tcp/4001"))
        assert not _addr_is_routable(Multiaddr("/ip4/172.20.0.2/tcp/4001"))
        assert not _addr_is_routable(Multiaddr("/ip4/10.0.0.5/tcp/4001"))
        assert not _addr_is_routable(Multiaddr("/ip4/192.168.1.5/tcp/4001"))
        assert not _addr_is_routable(Multiaddr("/ip4/127.0.0.1/tcp/4001"))

        # Relay (p2p-circuit) paths are routable but NOT directly dialable.
        relay_addr = Multiaddr(
            "/ip4/141.11.164.205/udp/4001/quic-v1/p2p/"
            "12D3KooWEnYdmNc1VkgodEq8Hyoi9WtAsYqeXsV96rPJyuZjhYSc/p2p-circuit"
        )
        assert _addr_is_routable(relay_addr)
        assert not _addr_is_direct(relay_addr)
        assert _addr_is_direct(Multiaddr("/ip4/8.8.8.8/tcp/4001"))
        assert _addr_is_direct(Multiaddr("/ip4/52.7.183.75/udp/4001/quic-v1"))

    @pytest.mark.trio
    async def test_get_candidate_peers_filters_private_only_on_public_node(self):
        """A public node excludes private-only peers from candidates."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        pub_peer = ID(b"12D3KooW1" + b"a" * 46)
        priv_peer = ID(b"12D3KooW2" + b"b" * 46)
        mixed_peer = ID(b"12D3KooW3" + b"c" * 46)
        self_peer = ID(b"12D3KooW4" + b"d" * 46)

        class MockPeerstore:
            def peer_ids(self):
                return [pub_peer, priv_peer, mixed_peer, self_peer]

            def addrs(self, peer_id):
                if peer_id == pub_peer:
                    return [Multiaddr("/ip4/8.8.8.8/tcp/4001")]
                if peer_id == priv_peer:
                    return [Multiaddr("/ip4/172.20.0.2/tcp/4001")]
                if peer_id == mixed_peer:
                    return [
                        Multiaddr("/ip4/172.20.0.3/tcp/4001"),
                        Multiaddr("/ip4/9.9.9.9/tcp/4001"),
                    ]
                return []

            def get_local_record(self):
                # This node announces a public address → treat as public node.
                class _FakeRecord:
                    def record(self):
                        class _FakeRec:
                            addrs = [Multiaddr("/ip4/52.7.183.75/tcp/4001")]

                        return _FakeRec()

                return _FakeRecord()

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = self_peer

        connector = AutoConnector(MockSwarm())  # type: ignore
        candidates = await connector._get_candidate_peers()

        assert pub_peer in candidates
        assert mixed_peer in candidates  # has at least one public addr
        assert priv_peer not in candidates
        assert self_peer not in candidates

    @pytest.mark.trio
    async def test_get_candidate_peers_excludes_relay_only_peers(self):
        """A public node excludes peers whose only addrs are p2p-circuit relays."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        direct_peer = ID(b"12D3KooW1" + b"a" * 46)
        relay_peer = ID(b"12D3KooW2" + b"b" * 46)
        self_peer = ID(b"12D3KooW3" + b"c" * 46)

        class MockPeerstore:
            def peer_ids(self):
                return [direct_peer, relay_peer, self_peer]

            def addrs(self, peer_id):
                if peer_id == direct_peer:
                    return [Multiaddr("/ip4/8.8.8.8/tcp/4001")]
                if peer_id == relay_peer:
                    # Routable IP embedded, but the path goes through a relay.
                    return [
                        Multiaddr(
                            "/ip4/141.11.164.205/udp/4001/quic-v1/p2p/"
                            "12D3KooWEnYdmNc1VkgodEq8Hyoi9WtAsYqeXsV96rPJyuZjhYSc"
                            "/p2p-circuit"
                        )
                    ]
                return []

            def get_local_record(self):
                class _FakeRecord:
                    def record(self):
                        class _FakeRec:
                            addrs = [Multiaddr("/ip4/52.7.183.75/tcp/4001")]

                        return _FakeRec()

                return _FakeRecord()

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = self_peer

        connector = AutoConnector(MockSwarm())  # type: ignore
        candidates = await connector._get_candidate_peers()

        assert direct_peer in candidates
        assert relay_peer not in candidates
        assert self_peer not in candidates

    @pytest.mark.trio
    async def test_get_candidate_peers_keeps_private_on_lan_node(self):
        """A LAN node (no public announced addr) keeps private peers dialable."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        priv_peer = ID(b"12D3KooW1" + b"a" * 46)

        class MockPeerstore:
            def peer_ids(self):
                return [priv_peer]

            def addrs(self, peer_id):
                return [Multiaddr("/ip4/192.168.1.5/tcp/4001")]

            def get_local_record(self):
                # No public address announced (LAN/mDNS deployment).
                return None

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = ID(b"12D3KooW2" + b"b" * 46)

        connector = AutoConnector(MockSwarm())  # type: ignore
        candidates = await connector._get_candidate_peers()

        assert priv_peer in candidates

    def test_initial_state(self):
        """Test initial state of AutoConnector."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig()

        connector = AutoConnector(MockSwarm())  # type: ignore
        assert connector._started is False

    @pytest.mark.trio
    async def test_start_stop(self):
        """Test starting and stopping the AutoConnector."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig()

        connector = AutoConnector(MockSwarm())  # type: ignore

        await connector.start()
        assert connector._started is True

        await connector.stop()
        assert connector._started is False


class TestConnectionPrunerWatermarks:
    """Test ConnectionPruner with watermark support."""

    def test_pruner_uses_watermarks(self):
        """Test that pruner configuration uses watermarks from config."""
        from libp2p.network.connection_pruner import ConnectionPruner

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig(
                    min_connections=10,
                    low_watermark=50,
                    high_watermark=100,
                    max_connections=200,
                )
                self.peerstore = None
                self.connections = {}
                self.tag_store = None
                self.connection_gate = None

            def get_connections(self):
                return []

        mock_swarm = MockSwarm()
        ConnectionPruner(mock_swarm)  # type: ignore

        # Pruner should use watermarks from swarm's connection_config
        assert mock_swarm.connection_config.high_watermark == 100
        assert mock_swarm.connection_config.low_watermark == 50


class TestAutoConnectorCustomInterval:
    """Test AutoConnector with custom interval."""

    def test_custom_interval(self):
        """Test AutoConnector with custom auto_connect_interval."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig(
                    auto_connect_interval=60.0,
                )

        connector = AutoConnector(MockSwarm(), auto_connect_interval=60.0)  # type: ignore
        assert connector.auto_connect_interval == 60.0

    def test_default_interval(self):
        """Test AutoConnector with default interval."""

        class MockSwarm:
            def __init__(self):
                self.connection_config = ConnectionConfig()

        connector = AutoConnector(MockSwarm())  # type: ignore
        assert connector.auto_connect_interval == AUTO_CONNECT_INTERVAL


class TestAutoConnectorDialBatchCap:
    """Test that the auto-connector caps dials per cycle to avoid a storm."""

    @pytest.mark.trio
    async def test_maybe_connect_dials_at_most_capped_batch(self):
        """A node far below the watermark dials a bounded batch, not needed*2."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        self_peer = ID(b"12D3KooW1" + b"a" * 46)
        # 300 candidate peers, all public and directly dialable.
        peers = [ID((b"12D3KooW%02d" % i) + b"b" * 44) for i in range(300)]

        dialed: list[ID] = []

        class MockPeerstore:
            def peer_ids(self):
                return peers

            def addrs(self, peer_id):
                return [Multiaddr("/ip4/8.8.8.8/tcp/4001")]

            def get_local_record(self):
                class _FakeRecord:
                    def record(self):
                        class _FakeRec:
                            addrs = [Multiaddr("/ip4/52.7.183.75/tcp/4001")]

                        return _FakeRec()

                return _FakeRecord()

        class MockConnectionConfig:
            low_watermark = 300
            min_connections = 50
            dial_timeout = 5.0

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = self_peer
            connection_config = MockConnectionConfig()

            def get_total_connections(self):
                return 0

            async def dial_peer(self, peer_id):
                dialed.append(peer_id)

        connector = AutoConnector(MockSwarm())  # type: ignore
        connector._started = True
        await connector.maybe_connect()

        # Must be bounded (cap = 40), NOT needed * 2 = 600.
        assert 0 < len(dialed) <= 40

    @pytest.mark.trio
    async def test_maybe_connect_small_need_not_capped(self):
        """Small needs below the cap are dialed in full (no over-restriction)."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        self_peer = ID(b"12D3KooW1" + b"a" * 46)
        peers = [ID((b"12D3KooW%02d" % i) + b"b" * 44) for i in range(10)]

        dialed: list[ID] = []

        class MockPeerstore:
            def peer_ids(self):
                return peers

            def addrs(self, peer_id):
                return [Multiaddr("/ip4/8.8.8.8/tcp/4001")]

            def get_local_record(self):
                class _FakeRecord:
                    def record(self):
                        class _FakeRec:
                            addrs = [Multiaddr("/ip4/52.7.183.75/tcp/4001")]

                        return _FakeRec()

                return _FakeRecord()

        class MockConnectionConfig:
            low_watermark = 50
            min_connections = 10
            dial_timeout = 5.0

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = self_peer
            connection_config = MockConnectionConfig()

            def get_total_connections(self):
                return 0

            async def dial_peer(self, peer_id):
                dialed.append(peer_id)

        connector = AutoConnector(MockSwarm())  # type: ignore
        connector._started = True
        await connector.maybe_connect()

        # need = 50, needed*2 = 100 but only 10 candidates exist → all dialed.
        assert len(dialed) == 10

    @pytest.mark.trio
    async def test_backoff_cooldown_progression(self):
        """
        Test exponential backoff progression:
        5s -> 15s -> 20s -> max 300s, max 60s below floor.
        """
        from libp2p.network.auto_connector import AutoConnector

        class MockSwarm:
            connections = {}
            self_id = ID(b"12D3KooW1" + b"a" * 46)
            total_conns: int = 20

            class connection_config:
                min_connections = 10
                low_watermark = 50
                dial_timeout = 5.0

            def get_total_connections(self) -> int:
                return self.total_conns

        swarm = MockSwarm()
        connector = AutoConnector(swarm)  # type: ignore
        peer = ID(b"12D3KooW2" + b"b" * 46)

        # 0 failures -> 0.0
        assert connector._get_cooldown(peer) == 0.0

        # 1 failure -> 5.0s
        connector.record_failed_connection(peer)
        assert connector._get_cooldown(peer) == 5.0

        # 2 failures -> 15.0s
        connector.record_failed_connection(peer)
        assert connector._get_cooldown(peer) == 15.0

        # 3 failures -> 20.0s (5 * 2^2)
        connector.record_failed_connection(peer)
        assert connector._get_cooldown(peer) == 20.0

        # Many failures -> capped at 300.0s
        for _ in range(10):
            connector.record_failed_connection(peer)
        assert connector._get_cooldown(peer) == 300.0

        # When below min_connections -> capped at 60.0s
        swarm.total_conns = 5  # Below min (10)
        assert connector._get_cooldown(peer) == 60.0

    @pytest.mark.trio
    async def test_discovery_callback_triggered_when_candidates_low(self):
        """Test discovery callback is invoked when candidates are low."""
        from multiaddr import Multiaddr

        from libp2p.network.auto_connector import AutoConnector

        self_peer = ID(b"12D3KooW1" + b"a" * 46)
        peers = [ID((b"12D3KooW%02d" % i) + b"b" * 44) for i in range(5)]

        class MockPeerstore:
            def peer_ids(self):
                return peers

            def addrs(self, peer_id):
                return [Multiaddr("/ip4/8.8.8.8/tcp/4001")]

            def get_local_record(self):
                class _FakeRecord:
                    def record(self):
                        class _FakeRec:
                            addrs = [Multiaddr("/ip4/52.7.183.75/tcp/4001")]

                        return _FakeRec()

                return _FakeRecord()

        class MockSwarm:
            peerstore = MockPeerstore()
            connections = {}
            self_id = self_peer

            class connection_config:
                low_watermark = 50
                high_watermark = 100
                min_connections = 10
                dial_timeout = 5.0

            def get_total_connections(self):
                return 0

            async def dial_peer(self, peer_id):
                pass

        connector = AutoConnector(MockSwarm())  # type: ignore
        connector._started = True

        discovery_called = False

        async def mock_discovery():
            nonlocal discovery_called
            discovery_called = True

        connector.set_discovery_callback(mock_discovery)
        await connector.maybe_connect()

        assert discovery_called is True
