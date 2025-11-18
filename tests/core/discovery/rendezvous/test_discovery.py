"""
Unit tests for the rendezvous discovery implementation.
"""

import time
from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.discovery.rendezvous.discovery import PeerCache, RendezvousDiscovery
from libp2p.discovery.rendezvous.errors import RendezvousError
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


@pytest.fixture
def mock_host():
    """Mock host for testing."""
    host = Mock()
    host.get_id.return_value = ID.from_base58(
        "QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    )
    return host


@pytest.fixture
def rendezvous_peer():
    """Rendezvous server peer ID for testing."""
    return ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM")


@pytest.fixture
def discovery(mock_host, rendezvous_peer):
    """Rendezvous discovery for testing."""
    return RendezvousDiscovery(mock_host, rendezvous_peer)


@pytest.fixture
def sample_peer_info():
    """Sample peer info for testing."""
    peer_id = ID.from_base58("QmTestPeer123")
    addrs = [
        Multiaddr("/ip4/127.0.0.1/tcp/8001"),
        Multiaddr("/ip4/192.168.1.1/tcp/8001"),
    ]
    return PeerInfo(peer_id, addrs)


class TestPeerCache:
    """Test cases for PeerCache."""

    def test_init(self):
        """Test cache initialization."""
        cache = PeerCache()
        assert cache.peers == {}
        assert cache.expiry == {}
        assert cache.cookie == b""

    def test_add_peer(self, sample_peer_info):
        """Test adding a peer to cache."""
        cache = PeerCache()
        ttl = 300

        cache.add_peer(sample_peer_info, ttl)

        assert sample_peer_info.peer_id in cache.peers
        assert cache.peers[sample_peer_info.peer_id] == sample_peer_info
        assert sample_peer_info.peer_id in cache.expiry
        assert cache.expiry[sample_peer_info.peer_id] > time.time()

    def test_get_valid_peers_fresh(self, sample_peer_info):
        """Test getting valid peers from cache."""
        cache = PeerCache()
        cache.add_peer(sample_peer_info, 300)  # 5 minutes TTL

        valid_peers = cache.get_valid_peers()
        assert len(valid_peers) == 1
        assert valid_peers[0] == sample_peer_info

    def test_get_valid_peers_expired(self, sample_peer_info):
        """Test getting valid peers removes expired ones."""
        cache = PeerCache()

        # Add expired peer
        cache.add_peer(sample_peer_info, 1)
        time.sleep(1.1)  # Wait for expiration

        valid_peers = cache.get_valid_peers()
        assert len(valid_peers) == 0
        assert sample_peer_info.peer_id not in cache.peers
        assert sample_peer_info.peer_id not in cache.expiry

    def test_get_valid_peers_with_limit(self):
        """Test getting valid peers with limit."""
        cache = PeerCache()

        # Add multiple peers
        peer_infos = []
        for i in range(5):
            # Generate valid peer IDs using crypto
            from libp2p.crypto.ed25519 import create_new_key_pair

            key_pair = create_new_key_pair()
            peer_id = ID.from_pubkey(key_pair.public_key)
            peer_info = PeerInfo(peer_id, [Multiaddr(f"/ip4/127.0.0.1/tcp/800{i}")])
            peer_infos.append(peer_info)
            cache.add_peer(peer_info, 300)

        # Get with limit
        valid_peers = cache.get_valid_peers(limit=3)
        assert len(valid_peers) == 3

    def test_clear(self, sample_peer_info):
        """Test clearing the cache."""
        cache = PeerCache()
        cache.add_peer(sample_peer_info, 300)
        cache.cookie = b"test-cookie"

        cache.clear()

        assert cache.peers == {}
        assert cache.expiry == {}
        assert cache.cookie == b""


class TestRendezvousDiscovery:
    """Test cases for RendezvousDiscovery."""

    def test_init(self, mock_host, rendezvous_peer):
        """Test discovery initialization."""
        discovery = RendezvousDiscovery(mock_host, rendezvous_peer, enable_refresh=True)

        assert discovery.host == mock_host
        assert discovery.client.rendezvous_peer == rendezvous_peer
        assert discovery.client.enable_refresh is True
        assert discovery.caches == {}
        assert discovery._discover_locks == {}

    @pytest.mark.trio
    async def test_run(self, discovery):
        """Test running the discovery service."""
        # Test the run method without MockClock to avoid compatibility issues
        async with trio.open_nursery() as nursery:
            # Set the nursery on the client
            discovery.client.set_nursery(nursery)

            # Start the run method in background
            nursery.start_soon(discovery.run)

            # Give it a moment to start
            await trio.sleep(0.01)

            # Cancel to test cleanup
            nursery.cancel_scope.cancel()

    @pytest.mark.trio
    async def test_register(self, discovery, mock_host):
        """Test peer registration."""
        # Mock the client register method
        discovery.client.register = AsyncMock(return_value=3600.0)

        ttl = await discovery.advertise("test-namespace", 3600)

        assert ttl == 3600.0
        discovery.client.register.assert_called_once_with("test-namespace", 3600)

    @pytest.mark.trio
    async def test_unregister(self, discovery):
        """Test peer unregistration."""
        # Mock the client unregister method
        discovery.client.unregister = AsyncMock()

        await discovery.unregister("test-namespace")

        discovery.client.unregister.assert_called_once_with("test-namespace")

    @pytest.mark.trio
    async def test_discover_no_cache(self, discovery, sample_peer_info):
        """Test discovery without cache."""
        # Mock the client discover method
        discovery.client.discover = AsyncMock(return_value=([sample_peer_info], b""))

        peers = await discovery.find_all_peers("test-namespace")

        assert len(peers) == 1
        assert peers[0] == sample_peer_info
        discovery.client.discover.assert_called_once()

    @pytest.mark.trio
    async def test_discover_with_cache_hit(self, discovery, sample_peer_info):
        """Test discovery with cache hit."""
        # Add peer to cache
        cache = PeerCache()
        cache.add_peer(sample_peer_info, 300)
        discovery.caches["test-namespace"] = cache

        # Use find_peers to get limited results from cache
        peers = []
        count = 0
        async for peer in discovery.find_peers("test-namespace", limit=1):
            peers.append(peer)
            count += 1
            if count >= 1:
                break

        assert len(peers) == 1
        assert peers[0] == sample_peer_info

    @pytest.mark.trio
    async def test_discover_with_cache_miss(self, discovery, sample_peer_info):
        """Test discovery with cache miss (expired cache)."""
        # Add expired peer to cache
        cache = PeerCache()
        cache.add_peer(sample_peer_info, 1)
        time.sleep(1.1)  # Wait for expiration
        discovery.caches["test-namespace"] = cache

        # Mock the client discover method
        discovery.client.discover = AsyncMock(return_value=([sample_peer_info], b""))

        peers = await discovery.find_all_peers("test-namespace")

        assert len(peers) == 1
        assert peers[0] == sample_peer_info
        discovery.client.discover.assert_called_once()

    @pytest.mark.trio
    async def test_discover_concurrent_requests(self, discovery, sample_peer_info):
        """Test concurrent discovery requests are handled safely."""

        # Mock the client discover method with delay
        async def mock_discover(*args, **kwargs):
            await trio.sleep(0.1)
            return ([sample_peer_info], b"")

        discovery.client.discover = mock_discover

        # Start multiple concurrent discoveries
        async with trio.open_nursery() as nursery:
            results = []

            async def discover_and_store():
                peers = await discovery.find_all_peers("test-namespace")
                results.append(peers)

            # Start 3 concurrent discoveries
            for _ in range(3):
                nursery.start_soon(discover_and_store)

        # All should return the same result
        assert len(results) == 3
        for result in results:
            assert len(result) == 1
            assert result[0] == sample_peer_info

    @pytest.mark.trio
    async def test_error_handling(self, discovery):
        """Test error handling in discovery."""
        # Mock the client to raise an error
        discovery.client.discover = AsyncMock(
            side_effect=RendezvousError(
                Message.ResponseStatus.E_INVALID_NAMESPACE, "Invalid namespace"
            )
        )

        # Core method should handle errors gracefully and return empty list
        peers = await discovery.find_all_peers("invalid-namespace")
        assert peers == []

    @pytest.mark.trio
    async def test_cache_ttl_management(self, discovery, sample_peer_info):
        """Test cache TTL management."""
        # Create a cache directly and add a peer with short TTL
        cache = PeerCache()
        cache.add_peer(sample_peer_info, 1)  # 1 second TTL
        discovery.caches["test-namespace"] = cache

        # Initially peer should be valid
        assert len(cache.get_valid_peers()) == 1

        # Manually expire the peer by setting expiry time to past
        import time

        cache.expiry[sample_peer_info.peer_id] = time.time() - 1

        # Peer should now be expired and removed when we check
        assert len(cache.get_valid_peers()) == 0
