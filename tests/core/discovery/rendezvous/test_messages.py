"""
Tests for rendezvous message utilities and protobuf handling.
"""

import pytest
from multiaddr import Multiaddr

from libp2p.discovery.rendezvous.config import DEFAULT_TTL
from libp2p.discovery.rendezvous.messages import (
    create_discover_message,
    create_discover_response_message,
    create_register_message,
    create_register_response_message,
    create_unregister_message,
    parse_peer_info,
)
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


@pytest.fixture
def sample_peer_id():
    """Sample peer ID for testing."""
    return ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ")


@pytest.fixture
def sample_addrs():
    """Sample addresses for testing."""
    return [
        Multiaddr("/ip4/127.0.0.1/tcp/8000"),
        Multiaddr("/ip4/192.168.1.1/tcp/8000"),
    ]


@pytest.fixture
def sample_peer_info(sample_peer_id, sample_addrs):
    """Sample peer info for testing."""
    return PeerInfo(sample_peer_id, [addr.to_bytes() for addr in sample_addrs])


class TestMessageCreation:
    """Test cases for message creation functions."""

    def test_create_register_message(self, sample_peer_id, sample_addrs):
        """Test creating register message."""
        namespace = "test-namespace"
        ttl = DEFAULT_TTL

        message = create_register_message(namespace, sample_peer_id, sample_addrs, ttl)

        assert message.type == Message.MessageType.REGISTER
        assert message.register.ns == namespace
        assert message.register.peer.id == sample_peer_id.to_bytes()
        expected_addrs = [addr.to_bytes() for addr in sample_addrs]
        assert list(message.register.peer.addrs) == expected_addrs
        assert message.register.ttl == ttl

    def test_create_register_message_empty_addrs(self, sample_peer_id):
        """Test creating register message with empty addresses."""
        namespace = "test-namespace"
        ttl = DEFAULT_TTL
        addrs = []

        message = create_register_message(namespace, sample_peer_id, addrs, ttl)

        assert message.type == Message.MessageType.REGISTER
        assert message.register.ns == namespace
        assert message.register.peer.id == sample_peer_id.to_bytes()
        assert len(message.register.peer.addrs) == 0
        assert message.register.ttl == ttl

    def test_create_discover_message_basic(self):
        """Test creating basic discover message."""
        namespace = "test-namespace"

        message = create_discover_message(namespace)

        assert message.type == Message.MessageType.DISCOVER
        assert message.discover.ns == namespace
        assert message.discover.limit == 0  # Default from messages.py
        assert message.discover.cookie == b""

    def test_create_discover_message_with_params(self):
        """Test creating discover message with parameters."""
        namespace = "test-namespace"
        limit = 50
        cookie = b"test-cookie"

        message = create_discover_message(namespace, limit=limit, cookie=cookie)

        assert message.type == Message.MessageType.DISCOVER
        assert message.discover.ns == namespace
        assert message.discover.limit == limit
        assert message.discover.cookie == cookie

    def test_create_unregister_message(self, sample_peer_id):
        """Test creating unregister message."""
        namespace = "test-namespace"

        message = create_unregister_message(namespace, sample_peer_id)

        assert message.type == Message.MessageType.UNREGISTER
        assert message.unregister.ns == namespace
        assert message.unregister.id == sample_peer_id.to_bytes()


class TestResponseMessageCreation:
    """Test cases for response message creation functions."""

    def test_create_register_response_message_success(self):
        """Test creating successful register response message."""
        ttl = 3600

        message = create_register_response_message(Message.ResponseStatus.OK, ttl=ttl)

        assert message.type == Message.MessageType.REGISTER_RESPONSE
        assert message.registerResponse.status == Message.ResponseStatus.OK
        assert message.registerResponse.ttl == ttl
        assert message.registerResponse.statusText == ""

    def test_create_register_response_message_error(self):
        """Test creating error register response message."""
        status = Message.ResponseStatus.E_INVALID_NAMESPACE
        status_text = "Invalid namespace provided"

        message = create_register_response_message(status, status_text=status_text)

        assert message.type == Message.MessageType.REGISTER_RESPONSE
        assert message.registerResponse.status == status
        assert message.registerResponse.ttl == 0
        assert message.registerResponse.statusText == status_text

    def test_create_discover_response_message_success(self):
        """Test creating successful discover response message."""
        # Create sample registrations
        registrations = []
        reg = Message.Register()
        reg.ns = "test-namespace"
        reg.peer.id = ID.from_base58("QmTest123").to_bytes()
        reg.peer.addrs.append(b"/ip4/127.0.0.1/tcp/8001")
        reg.ttl = 3600
        registrations.append(reg)

        cookie = b"next-page"

        message = create_discover_response_message(registrations, cookie=cookie)

        assert message.type == Message.MessageType.DISCOVER_RESPONSE
        assert message.discoverResponse.status == Message.ResponseStatus.OK
        assert len(message.discoverResponse.registrations) == 1
        assert message.discoverResponse.cookie == cookie
        assert message.discoverResponse.statusText == ""

    def test_create_discover_response_message_empty(self):
        """Test creating discover response message with no registrations."""
        message = create_discover_response_message([])

        assert message.type == Message.MessageType.DISCOVER_RESPONSE
        assert message.discoverResponse.status == Message.ResponseStatus.OK
        assert len(message.discoverResponse.registrations) == 0
        assert message.discoverResponse.cookie == b""

    def test_create_discover_response_message_error(self):
        """Test creating error discover response message."""
        status = Message.ResponseStatus.E_INVALID_NAMESPACE
        status_text = "Namespace not found"

        message = create_discover_response_message(
            [], status=status, status_text=status_text
        )

        assert message.type == Message.MessageType.DISCOVER_RESPONSE
        assert message.discoverResponse.status == status
        assert len(message.discoverResponse.registrations) == 0
        assert message.discoverResponse.statusText == status_text


class TestPeerInfoParsing:
    """Test cases for peer info parsing."""

    def test_parse_peer_info_valid(self, sample_peer_id, sample_addrs):
        """Test parsing valid peer info from protobuf."""
        # Create protobuf peer
        peer_pb = Message.PeerInfo()
        peer_pb.id = sample_peer_id.to_bytes()
        addr_bytes = [addr.to_bytes() for addr in sample_addrs]
        peer_pb.addrs.extend(addr_bytes)

        peer_id, addrs = parse_peer_info(peer_pb)

        assert peer_id == sample_peer_id
        assert addrs == sample_addrs

    def test_parse_peer_info_empty_addrs(self, sample_peer_id):
        """Test parsing peer info with empty addresses."""
        # Create protobuf peer
        peer_pb = Message.PeerInfo()
        peer_pb.id = sample_peer_id.to_bytes()
        # No addresses added

        peer_id, addrs = parse_peer_info(peer_pb)

        assert peer_id == sample_peer_id
        assert addrs == []

    def test_parse_peer_info_invalid_id(self, sample_addrs):
        """Test parsing peer info with invalid peer ID."""
        # Create protobuf peer with invalid ID
        peer_pb = Message.PeerInfo()
        peer_pb.id = b"invalid-peer-id"
        addr_bytes = [addr.to_bytes() for addr in sample_addrs]
        peer_pb.addrs.extend(addr_bytes)

        # PeerID is very lenient - it accepts any bytes
        peer_id, addrs = parse_peer_info(peer_pb)
        assert peer_id is not None
        assert addrs == sample_addrs

    def test_parse_peer_info_empty_id(self, sample_addrs):
        """Test parsing peer info with empty peer ID."""
        # Create protobuf peer with empty ID
        peer_pb = Message.PeerInfo()
        peer_pb.id = b""
        addr_bytes = [addr.to_bytes() for addr in sample_addrs]
        peer_pb.addrs.extend(addr_bytes)

        # PeerID accepts empty bytes too
        peer_id, addrs = parse_peer_info(peer_pb)
        assert peer_id is not None
        assert addrs == sample_addrs


class TestMessageSerialization:
    """Test message serialization and deserialization."""

    def test_register_message_roundtrip(self, sample_peer_id, sample_addrs):
        """Test register message serialization roundtrip."""
        namespace = "test-namespace"
        ttl = DEFAULT_TTL

        # Create message
        original = create_register_message(namespace, sample_peer_id, sample_addrs, ttl)

        # Serialize and deserialize
        serialized = original.SerializeToString()
        deserialized = Message()
        deserialized.ParseFromString(serialized)

        # Verify
        assert deserialized.type == Message.MessageType.REGISTER
        assert deserialized.register.ns == namespace
        assert deserialized.register.peer.id == sample_peer_id.to_bytes()
        expected_addrs = [addr.to_bytes() for addr in sample_addrs]
        assert list(deserialized.register.peer.addrs) == expected_addrs
        assert deserialized.register.ttl == ttl

    def test_discover_message_roundtrip(self):
        """Test discover message serialization roundtrip."""
        namespace = "test-namespace"
        limit = 50
        cookie = b"test-cookie"

        # Create message
        original = create_discover_message(namespace, limit=limit, cookie=cookie)

        # Serialize and deserialize
        serialized = original.SerializeToString()
        deserialized = Message()
        deserialized.ParseFromString(serialized)

        # Verify
        assert deserialized.type == Message.MessageType.DISCOVER
        assert deserialized.discover.ns == namespace
        assert deserialized.discover.limit == limit
        assert deserialized.discover.cookie == cookie

    def test_response_message_roundtrip(self):
        """Test response message serialization roundtrip."""
        # Create sample registration
        reg = Message.Register()
        reg.ns = "test-namespace"
        reg.peer.id = ID.from_base58("QmTest123").to_bytes()
        reg.peer.addrs.append(b"/ip4/127.0.0.1/tcp/8001")
        reg.ttl = 3600

        registrations = [reg]
        cookie = b"next-page"
        status_text = "Success"

        # Create message
        original = create_discover_response_message(
            registrations, cookie=cookie, status_text=status_text
        )

        # Serialize and deserialize
        serialized = original.SerializeToString()
        deserialized = Message()
        deserialized.ParseFromString(serialized)

        # Verify
        assert deserialized.type == Message.MessageType.DISCOVER_RESPONSE
        assert deserialized.discoverResponse.status == Message.ResponseStatus.OK
        assert len(deserialized.discoverResponse.registrations) == 1
        assert deserialized.discoverResponse.cookie == cookie
        assert deserialized.discoverResponse.statusText == status_text

        # Verify registration details
        deserialized_reg = deserialized.discoverResponse.registrations[0]
        assert deserialized_reg.ns == "test-namespace"
        assert deserialized_reg.peer.id == ID.from_base58("QmTest123").to_bytes()


class TestMessageValidation:
    """Test message validation scenarios."""

    def test_message_type_validation(self, sample_peer_id, sample_addrs):
        """Test that message types are set correctly."""
        # Test all message types
        register_msg = create_register_message("ns", sample_peer_id, sample_addrs, 3600)
        discover_msg = create_discover_message("ns")
        unregister_msg = create_unregister_message("ns", sample_peer_id)

        register_resp = create_register_response_message(Message.ResponseStatus.OK)
        discover_resp = create_discover_response_message([])

        assert register_msg.type == Message.MessageType.REGISTER
        assert discover_msg.type == Message.MessageType.DISCOVER
        assert unregister_msg.type == Message.MessageType.UNREGISTER
        assert register_resp.type == Message.MessageType.REGISTER_RESPONSE
        assert discover_resp.type == Message.MessageType.DISCOVER_RESPONSE

    def test_namespace_handling(self, sample_peer_id, sample_addrs):
        """Test namespace handling in messages."""
        namespaces = ["", "simple", "with-dashes", "with_underscores", "123numbers"]

        for namespace in namespaces:
            register_msg = create_register_message(
                namespace, sample_peer_id, sample_addrs, 3600
            )
            discover_msg = create_discover_message(namespace)
            unregister_msg = create_unregister_message(namespace, sample_peer_id)

            assert register_msg.register.ns == namespace
            assert discover_msg.discover.ns == namespace
            assert unregister_msg.unregister.ns == namespace

    def test_binary_data_handling(self, sample_peer_id):
        """Test handling of binary data in messages."""
        # Test with various binary cookies
        cookies = [b"", b"simple", b"\x00\x01\x02\x03", b"unicode_\xc4\x85"]

        for cookie in cookies:
            discover_msg = create_discover_message("test", cookie=cookie)
            assert discover_msg.discover.cookie == cookie

            discover_resp = create_discover_response_message([], cookie=cookie)
            assert discover_resp.discoverResponse.cookie == cookie
