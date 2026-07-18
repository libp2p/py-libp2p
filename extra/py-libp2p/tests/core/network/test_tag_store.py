"""
Tests for connection tagging and direction functionality.

Tests for TagStore, Direction enum, and integration with connection pruning.
"""

import pytest

from libp2p.network.tag_store import (
    CommonTags,
    TagInfo,
    TagStore,
    upsert_add,
    upsert_bounded,
    upsert_set,
)
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction


class TestDirection:
    """Test Direction enum functionality."""

    def test_direction_values(self):
        """Test Direction enum values."""
        assert Direction.UNKNOWN.value == -1
        assert Direction.INBOUND.value == 0
        assert Direction.OUTBOUND.value == 1

    def test_direction_str(self):
        """Test Direction string representation."""
        assert str(Direction.UNKNOWN) == "unknown"
        assert str(Direction.INBOUND) == "inbound"
        assert str(Direction.OUTBOUND) == "outbound"

    def test_direction_from_string(self):
        """Test Direction.from_string method."""
        assert Direction.from_string("inbound") == Direction.INBOUND
        assert Direction.from_string("INBOUND") == Direction.INBOUND
        assert Direction.from_string("outbound") == Direction.OUTBOUND
        assert Direction.from_string("OUTBOUND") == Direction.OUTBOUND
        assert Direction.from_string("unknown") == Direction.UNKNOWN
        assert Direction.from_string("invalid") == Direction.UNKNOWN
        assert Direction.from_string("") == Direction.UNKNOWN

    def test_direction_comparison(self):
        """Test Direction enum comparison for sorting."""
        # INBOUND (0) < OUTBOUND (1) for pruning priority
        assert Direction.INBOUND < Direction.OUTBOUND
        assert Direction.UNKNOWN < Direction.INBOUND


class TestTagInfo:
    """Test TagInfo dataclass functionality."""

    def test_tag_info_defaults(self):
        """Test TagInfo default values."""
        info = TagInfo()
        assert info.value == 0
        assert info.tags == {}
        assert info.conns == {}
        assert info.first_seen > 0

    def test_tag_info_get_total_value(self):
        """Test TagInfo.get_total_value method."""
        info = TagInfo()
        info.tags = {"tag1": 10, "tag2": 20, "tag3": -5}
        assert info.get_total_value() == 25

    def test_tag_info_to_dict(self):
        """Test TagInfo.to_dict method."""
        info = TagInfo()
        info.tags = {"tag1": 10}
        info.conns = {"conn1": 12345.0}

        result = info.to_dict()
        assert "first_seen" in result
        assert result["value"] == 0
        assert result["tags"] == {"tag1": 10}
        assert result["conns"] == {"conn1": 12345.0}


class TestTagStore:
    """Test TagStore functionality."""

    @pytest.fixture
    def store(self):
        """Create a fresh TagStore for each test."""
        return TagStore()

    @pytest.fixture
    def peer_id(self):
        """Create a test peer ID."""
        # Create a simple peer ID for testing
        return ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")

    def test_tag_peer(self, store, peer_id):
        """Test tagging a peer."""
        store.tag_peer(peer_id, "test", 10)

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert info.tags["test"] == 10
        assert info.value == 10

    def test_tag_peer_multiple_tags(self, store, peer_id):
        """Test multiple tags on same peer."""
        store.tag_peer(peer_id, "tag1", 10)
        store.tag_peer(peer_id, "tag2", 20)

        assert store.get_tag_value(peer_id) == 30
        assert store.get_tag(peer_id, "tag1") == 10
        assert store.get_tag(peer_id, "tag2") == 20

    def test_tag_peer_overwrite(self, store, peer_id):
        """Test overwriting a tag value."""
        store.tag_peer(peer_id, "test", 10)
        store.tag_peer(peer_id, "test", 25)

        assert store.get_tag_value(peer_id) == 25
        assert store.get_tag(peer_id, "test") == 25

    def test_untag_peer(self, store, peer_id):
        """Test removing a tag from peer."""
        store.tag_peer(peer_id, "tag1", 10)
        store.tag_peer(peer_id, "tag2", 20)

        store.untag_peer(peer_id, "tag1")

        assert store.get_tag_value(peer_id) == 20
        assert store.get_tag(peer_id, "tag1") == 0
        assert store.get_tag(peer_id, "tag2") == 20

    def test_untag_peer_nonexistent(self, store, peer_id):
        """Test removing a nonexistent tag (should not error)."""
        store.untag_peer(peer_id, "nonexistent")  # Should not raise

    def test_upsert_tag(self, store, peer_id):
        """Test upsert_tag with custom function."""
        store.tag_peer(peer_id, "test", 10)

        # Add 5 to current value
        store.upsert_tag(peer_id, "test", lambda x: x + 5)
        assert store.get_tag(peer_id, "test") == 15

        # Double the value
        store.upsert_tag(peer_id, "test", lambda x: x * 2)
        assert store.get_tag(peer_id, "test") == 30

    def test_upsert_tag_new_tag(self, store, peer_id):
        """Test upsert_tag creates new tag if not exists."""
        store.upsert_tag(peer_id, "new_tag", lambda x: x + 10)
        assert store.get_tag(peer_id, "new_tag") == 10

    def test_protect_peer(self, store, peer_id):
        """Test protecting a peer."""
        store.protect(peer_id, "relay")

        assert store.is_protected(peer_id) is True
        assert store.is_protected(peer_id, "relay") is True
        assert store.is_protected(peer_id, "other") is False

    def test_unprotect_peer(self, store, peer_id):
        """Test unprotecting a peer."""
        store.protect(peer_id, "relay")
        store.protect(peer_id, "dht")

        # Unprotect one tag
        still_protected = store.unprotect(peer_id, "relay")
        assert still_protected is True
        assert store.is_protected(peer_id, "relay") is False
        assert store.is_protected(peer_id, "dht") is True

        # Unprotect last tag
        still_protected = store.unprotect(peer_id, "dht")
        assert still_protected is False
        assert store.is_protected(peer_id) is False

    def test_record_connection(self, store, peer_id):
        """Test recording connection."""
        store.record_connection(peer_id, "/ip4/127.0.0.1/tcp/1234")

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert "/ip4/127.0.0.1/tcp/1234" in info.conns

    def test_remove_connection(self, store, peer_id):
        """Test removing connection record."""
        store.record_connection(peer_id, "conn1")
        store.record_connection(peer_id, "conn2")

        store.remove_connection(peer_id, "conn1")

        info = store.get_tag_info(peer_id)
        assert "conn1" not in info.conns
        assert "conn2" in info.conns

    def test_clear_peer(self, store, peer_id):
        """Test clearing all data for a peer."""
        store.tag_peer(peer_id, "test", 10)
        store.protect(peer_id, "relay")

        store.clear_peer(peer_id)

        assert store.get_tag_info(peer_id) is None
        assert store.is_protected(peer_id) is False

    def test_get_all_peers(self, store):
        """Test getting all peers with tags."""
        peer1 = ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")
        peer2 = ID.from_base58("QmTzQ1kKpJwVGgzJuEdq7wAA5EQUWbVcPKJ6M7eBz3vqv7")

        store.tag_peer(peer1, "test", 10)
        store.tag_peer(peer2, "test", 20)

        peers = store.get_all_peers()
        assert len(peers) == 2
        assert peer1 in peers
        assert peer2 in peers

    def test_get_protected_peers(self, store):
        """Test getting protected peers."""
        peer1 = ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")
        peer2 = ID.from_base58("QmTzQ1kKpJwVGgzJuEdq7wAA5EQUWbVcPKJ6M7eBz3vqv7")

        store.tag_peer(peer1, "test", 10)  # Tagged but not protected
        store.protect(peer2, "relay")

        protected = store.get_protected_peers()
        assert len(protected) == 1
        assert peer2 in protected


class TestUpsertHelpers:
    """Test upsert helper functions."""

    def test_upsert_add(self):
        """Test upsert_add function."""
        fn = upsert_add(5)
        assert fn(10) == 15
        assert fn(0) == 5
        assert fn(-3) == 2

    def test_upsert_set(self):
        """Test upsert_set function."""
        fn = upsert_set(42)
        assert fn(0) == 42
        assert fn(100) == 42
        assert fn(-5) == 42

    def test_upsert_bounded(self):
        """Test upsert_bounded function."""
        fn = upsert_bounded(10, 0, 100)

        # Within bounds
        assert fn(50) == 60

        # Would exceed max
        assert fn(95) == 100

        # Would go below min
        fn_sub = upsert_bounded(-20, 0, 100)
        assert fn_sub(15) == 0


class TestCommonTags:
    """Test CommonTags constants."""

    def test_common_tags_exist(self):
        """Test that common tags are defined."""
        assert CommonTags.KEEP_ALIVE == "keep-alive"
        assert CommonTags.BOOTSTRAP == "bootstrap"
        assert CommonTags.RELAY == "relay"
        assert CommonTags.DHT == "dht"
        assert CommonTags.PUBSUB == "pubsub"
        assert CommonTags.BITSWAP == "bitswap"
        assert CommonTags.APPLICATION == "application"
        assert CommonTags.ACTIVE_STREAMS == "active-streams"
