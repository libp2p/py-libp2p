"""Tests for Phase 4: Advanced Features Integration."""

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.early_data import (
    BufferingEarlyDataHandler,
    CallbackEarlyDataHandler,
    CompositeEarlyDataHandler,
    EarlyDataManager,
    LoggingEarlyDataHandler,
)
from libp2p.security.noise.rekey import (
    ByteCountRekeyPolicy,
    CompositeRekeyPolicy,
    RekeyManager,
    TimeBasedRekeyPolicy,
)
from libp2p.security.noise.transport import Transport
from libp2p.security.noise.webtransport import (
    WebTransportCertManager,
    WebTransportSupport,
)
from tests.utils.factories import (
    noise_static_key_factory,
    transport_handshake_factory,
)


class TestWebTransportSupport:
    """Test WebTransport integration features."""

    def test_webtransport_support_creation(self):
        """Test WebTransport support creation."""
        wt_support = WebTransportSupport()
        assert wt_support is not None
        assert wt_support.cert_manager is not None

    def test_certificate_management(self):
        """Test certificate management functionality."""
        wt_support = WebTransportSupport()

        # Test adding certificates
        cert1_hash = wt_support.add_certificate(b"test_certificate_1")
        cert2_hash = wt_support.add_certificate(b"test_certificate_2")

        assert len(cert1_hash) == 32  # SHA-256 hash length
        assert len(cert2_hash) == 32
        assert cert1_hash != cert2_hash

        # Test getting certificate hashes
        hashes = wt_support.get_certificate_hashes()
        assert len(hashes) == 2
        assert cert1_hash in hashes
        assert cert2_hash in hashes

        # Test has_certificates
        assert wt_support.has_certificates() is True

    def test_certificate_validation(self):
        """Test certificate validation functionality."""
        wt_support = WebTransportSupport()

        # Add a certificate
        cert_hash = wt_support.add_certificate(b"test_certificate")

        # Test validation
        assert wt_support.validate_certificate_hash(cert_hash) is True

        # Test invalid hash
        invalid_hash = b"invalid_hash" + b"0" * 20  # 32 bytes but not a valid hash
        assert wt_support.validate_certificate_hash(invalid_hash) is False

        # Test wrong length hash
        short_hash = b"short"
        assert wt_support.validate_certificate_hash(short_hash) is False

    def test_cert_manager_functionality(self):
        """Test WebTransportCertManager functionality."""
        cert_manager = WebTransportCertManager()

        # Test empty state
        assert len(cert_manager) == 0
        assert bool(cert_manager) is False

        # Test adding certificates
        cert1_hash = cert_manager.add_certificate(b"cert1")
        cert2_hash = cert_manager.add_certificate(b"cert2")

        assert len(cert_manager) == 2
        assert bool(cert_manager) is True

        # Test getting hashes
        hashes = cert_manager.get_certificate_hashes()
        assert len(hashes) == 2

        # Test checking specific hash
        assert cert_manager.has_certificate_hash(cert1_hash) is True
        assert cert_manager.has_certificate_hash(cert2_hash) is True

        # Test adding duplicate (should not add again)
        cert1_hash_dup = cert_manager.add_certificate(b"cert1")
        assert cert1_hash == cert1_hash_dup
        assert len(cert_manager) == 2

        # Test clearing
        cert_manager.clear_certificates()
        assert len(cert_manager) == 0
        assert bool(cert_manager) is False


class TestEarlyDataHandlers:
    """Test early data handler functionality."""

    def test_logging_early_data_handler(self):
        """Test LoggingEarlyDataHandler."""
        handler = LoggingEarlyDataHandler("test_logger")
        assert handler.logger_name == "test_logger"

    @pytest.mark.trio
    async def test_buffering_early_data_handler(self):
        """Test BufferingEarlyDataHandler."""
        handler = BufferingEarlyDataHandler(max_buffer_size=1024)

        # Test empty state
        assert len(handler) == 0
        assert handler.size == 0

        # Test adding data
        await handler.handle_early_data(b"test_data_1")
        await handler.handle_early_data(b"test_data_2")

        assert len(handler) == 2
        assert handler.size == len(b"test_data_1") + len(b"test_data_2")

        # Test getting buffered data
        buffered_data = handler.get_buffered_data()
        assert buffered_data == b"test_data_1test_data_2"

        # Test clearing buffer
        handler.clear_buffer()
        assert len(handler) == 0
        assert handler.size == 0

    @pytest.mark.trio
    async def test_callback_early_data_handler(self):
        """Test CallbackEarlyDataHandler."""
        callback_data = []

        def sync_callback(data):
            callback_data.append(data)

        handler = CallbackEarlyDataHandler(sync_callback)

        # Test sync callback
        await handler.handle_early_data(b"sync_data")
        assert callback_data == [b"sync_data"]

        # Test async callback
        async def async_callback(data):
            callback_data.append(data)

        handler = CallbackEarlyDataHandler(async_callback)
        await handler.handle_early_data(b"async_data")
        assert callback_data == [b"sync_data", b"async_data"]

    @pytest.mark.trio
    async def test_composite_early_data_handler(self):
        """Test CompositeEarlyDataHandler."""
        handler1 = BufferingEarlyDataHandler()
        handler2 = BufferingEarlyDataHandler()

        composite = CompositeEarlyDataHandler([handler1, handler2])

        # Test handling data
        await composite.handle_early_data(b"composite_data")

        assert handler1.get_buffered_data() == b"composite_data"
        assert handler2.get_buffered_data() == b"composite_data"

        # Test adding handler
        handler3 = BufferingEarlyDataHandler()
        composite.add_handler(handler3)
        assert len(composite.handlers) == 3

        # Test removing handler
        composite.remove_handler(handler3)
        assert len(composite.handlers) == 2

    @pytest.mark.trio
    async def test_early_data_manager(self):
        """Test EarlyDataManager."""
        handler = BufferingEarlyDataHandler()
        manager = EarlyDataManager(handler)

        # Test initial state
        assert manager.has_early_data() is False
        assert manager.get_early_data() is None

        # Test handling early data
        await manager.handle_early_data(b"manager_data")

        assert manager.has_early_data() is True
        assert manager.get_early_data() == b"manager_data"

        # Test clearing early data
        manager.clear_early_data()
        assert manager.has_early_data() is False
        assert manager.get_early_data() is None

        # Test setting new handler
        new_handler = BufferingEarlyDataHandler()
        manager.set_handler(new_handler)
        assert manager.handler == new_handler


class TestRekeySupport:
    """Test rekey functionality."""

    def test_time_based_rekey_policy(self):
        """Test TimeBasedRekeyPolicy."""
        policy = TimeBasedRekeyPolicy(max_time_seconds=1)

        # Test immediately after creation
        assert policy.should_rekey(0, 0) is False

        # Test after time limit
        assert policy.should_rekey(0, 1.1) is True

        # Test with bytes (should be ignored)
        assert policy.should_rekey(1000000, 0.5) is False

    def test_byte_count_rekey_policy(self):
        """Test ByteCountRekeyPolicy."""
        policy = ByteCountRekeyPolicy(max_bytes=1000)

        # Test immediately after creation
        assert policy.should_rekey(0, 0) is False

        # Test after byte limit
        assert policy.should_rekey(1001, 0) is True

        # Test with time (should be ignored)
        assert policy.should_rekey(500, 3600) is False

    def test_composite_rekey_policy(self):
        """Test CompositeRekeyPolicy."""
        time_policy = TimeBasedRekeyPolicy(max_time_seconds=1)
        byte_policy = ByteCountRekeyPolicy(max_bytes=1000)

        composite = CompositeRekeyPolicy([time_policy, byte_policy])

        # Test neither condition met
        assert composite.should_rekey(500, 0.5) is False

        # Test time condition met
        assert composite.should_rekey(500, 1.1) is True

        # Test byte condition met
        assert composite.should_rekey(1001, 0.5) is True

    def test_rekey_manager(self):
        """Test RekeyManager functionality."""
        policy = TimeBasedRekeyPolicy(max_time_seconds=1)
        manager = RekeyManager(policy)

        # Test initial state
        assert manager.should_rekey() is False
        stats = manager.get_stats()
        assert stats["rekey_count"] == 0
        assert stats["bytes_since_rekey"] == 0

        # Test updating bytes
        manager.update_bytes_processed(500)
        stats = manager.get_stats()
        assert stats["bytes_since_rekey"] == 500

        # Test performing rekey
        manager.perform_rekey()
        stats = manager.get_stats()
        assert stats["rekey_count"] == 1
        assert stats["bytes_since_rekey"] == 0

        # Test reset stats
        manager.reset_stats()
        stats = manager.get_stats()
        assert stats["rekey_count"] == 0


class TestEnhancedTransport:
    """Test enhanced transport with advanced features."""

    @pytest.fixture
    def key_pairs(self):
        """Create test key pairs."""
        libp2p_keypair = create_new_key_pair()
        noise_key = noise_static_key_factory()
        return libp2p_keypair, noise_key

    @pytest.mark.trio
    async def test_enhanced_transport_creation(self, key_pairs, nursery):
        """Test enhanced transport creation with all features using real TCP."""
        libp2p_keypair, noise_key = key_pairs

        initiator_transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"test_early_data",
            early_data_handler=BufferingEarlyDataHandler(),
            rekey_policy=TimeBasedRekeyPolicy(max_time_seconds=3600),
        )

        # Test all features are available
        assert initiator_transport.webtransport_support is not None
        assert initiator_transport.early_data_manager is not None
        assert initiator_transport.rekey_manager is not None
        assert hasattr(initiator_transport, "_static_key_cache")
        assert initiator_transport.early_data == b"test_early_data"

        # Create responder transport
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
        )

        # Perform real handshake to verify all features work
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm handshake completed successfully
            test_data = b"enhanced_transport_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

    def test_pattern_selection(self, key_pairs):
        """Test pattern selection logic."""
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test default pattern (XX)
        pattern = transport.get_pattern()
        assert pattern.__class__.__name__ == "PatternXX"

        # Test pattern with remote peer (should still be XX if no cached key)
        pattern = transport.get_pattern()
        assert pattern.__class__.__name__ == "PatternXX"

    def test_static_key_caching(self, key_pairs):
        """Test static key caching for performance optimization."""
        libp2p_keypair, noise_key = key_pairs

        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test caching static key
        remote_peer = ID.from_pubkey(libp2p_keypair.public_key)
        remote_static_key = noise_key.get_public_key()

        transport.cache_static_key(remote_peer, remote_static_key)

        # Test retrieving cached key
        cached_key = transport.get_cached_static_key(remote_peer)
        assert cached_key == remote_static_key

        # Test clearing cache
        transport.clear_static_key_cache()
        cached_key = transport.get_cached_static_key(remote_peer)
        assert cached_key is None

    @pytest.mark.trio
    async def test_webtransport_integration(self, key_pairs, nursery):
        """Test WebTransport integration in transport using real TCP handshake."""
        libp2p_keypair, noise_key = key_pairs

        initiator_transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Add WebTransport certificates
        wt_support = initiator_transport.webtransport_support
        cert_hash = wt_support.add_certificate(b"webtransport_cert")

        assert wt_support.has_certificates() is True
        assert wt_support.validate_certificate_hash(cert_hash) is True

        # Create responder transport
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
        )
        responder_transport.webtransport_support.add_certificate(b"responder_cert")

        # Perform real handshake to verify WebTransport certificates work
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm handshake completed successfully
            test_data = b"webtransport_integration_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

    @pytest.mark.trio
    async def test_early_data_integration(self, key_pairs, nursery):
        """Test early data integration in transport using real TCP handshake."""
        libp2p_keypair, noise_key = key_pairs

        handler = BufferingEarlyDataHandler()
        initiator_transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            early_data=b"initiator_early_data",
            early_data_handler=handler,
        )

        # Test early data manager
        ed_manager = initiator_transport.early_data_manager
        assert ed_manager.handler == handler

        # Create responder transport
        responder_keypair = create_new_key_pair()
        responder_noise_key = noise_static_key_factory()
        responder_handler = BufferingEarlyDataHandler()
        responder_transport = Transport(
            libp2p_keypair=responder_keypair,
            noise_privkey=responder_noise_key,
            early_data_handler=responder_handler,
        )

        # Perform real handshake to verify early data works
        async with transport_handshake_factory(
            nursery, initiator_transport, responder_transport
        ) as (init_conn, resp_conn):
            # Verify connections established
            assert init_conn is not None
            assert resp_conn is not None

            # Test data exchange to confirm handshake completed successfully
            test_data = b"early_data_integration_test"
            await init_conn.write(test_data)
            received = await resp_conn.read(len(test_data))
            assert received == test_data

            # Verify early data was configured
            assert initiator_transport.early_data == b"initiator_early_data"

    def test_rekey_integration(self, key_pairs):
        """Test rekey integration in transport."""
        libp2p_keypair, noise_key = key_pairs

        policy = TimeBasedRekeyPolicy(max_time_seconds=3600)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
            rekey_policy=policy,
        )

        # Test rekey manager
        rekey_manager = transport.rekey_manager
        assert rekey_manager.policy == policy

        # Test updating bytes processed
        rekey_manager.update_bytes_processed(1024)
        stats = rekey_manager.get_stats()
        assert stats["bytes_since_rekey"] == 1024

        # Test rekey check
        assert rekey_manager.should_rekey() is False  # Time not exceeded

    def test_backward_compatibility(self, key_pairs):
        """Test backward compatibility with existing transport usage."""
        libp2p_keypair, noise_key = key_pairs

        # Test minimal transport creation (backward compatible)
        transport = Transport(
            libp2p_keypair=libp2p_keypair,
            noise_privkey=noise_key,
        )

        # Test that all required attributes exist
        assert transport.libp2p_privkey is not None
        assert transport.noise_privkey is not None
        assert transport.local_peer is not None
        assert transport.early_data is None

        # Test that advanced features are still available
        assert transport.webtransport_support is not None
        assert transport.early_data_manager is not None
        assert transport.rekey_manager is not None
