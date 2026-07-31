"""
Tests for connection tagging and direction functionality.

Tests for TagStore, Direction enum, and integration with connection pruning.
"""

from unittest.mock import MagicMock

import pytest

from libp2p.network.tag_store import (
    CommonTags,
    TagInfo,
    TagStore,
    TagStoreNotifee,
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
        assert info.temp is False  # explicitly created TagInfo is not temp

    def test_tag_info_copy_independence(self):
        """TagInfo.copy() returns an object whose mutations don't affect original."""
        original = TagInfo(value=5, tags={"x": 5}, conns={1: 1.0}, temp=True)
        copy = original.copy()

        # Verify values are equal
        assert copy.value == 5
        assert copy.tags == {"x": 5}
        assert copy.conns == {1: 1.0}
        assert copy.temp is True

        # Mutate copy — original must be unaffected
        copy.tags["y"] = 99
        copy.conns[2] = 2.0
        copy.temp = False

        assert "y" not in original.tags
        assert 2 not in original.conns
        assert original.temp is True

    def test_tag_info_get_total_value(self):
        """Test TagInfo.get_total_value method."""
        info = TagInfo()
        info.tags = {"tag1": 10, "tag2": 20, "tag3": -5}
        assert info.get_total_value() == 25

    def test_tag_info_to_dict(self):
        """Test TagInfo.to_dict method."""
        info = TagInfo()
        info.tags = {"tag1": 10}
        info.conns = {id("conn1"): 12345.0}  # type: ignore[assignment]

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
        """Test recording connection — conn_id is an int (id(conn))."""
        store.record_connection(peer_id, 12345)

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert 12345 in info.conns

    def test_remove_connection(self, store, peer_id):
        """Test removing connection record — only one of two conns removed."""
        store.record_connection(peer_id, 1001)
        store.record_connection(peer_id, 1002)

        store.remove_connection(peer_id, 1001)

        info = store.get_tag_info(peer_id)
        assert 1001 not in info.conns
        assert 1002 in info.conns

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

    # ── Phase 1 lifecycle tests ────────────────────────────────────────────────

    def test_temp_entry_on_early_tag(self, store, peer_id):
        """Tagging a peer before any connection creates a temp entry."""
        store.tag_peer(peer_id, "dht", 10)
        info = store.get_tag_info(peer_id)
        assert info is not None
        assert info.temp is True

    def test_temp_flips_on_first_connection(self, store, peer_id):
        """record_connection flips temp=False and updates first_seen."""
        import time

        store.tag_peer(peer_id, "dht", 10)
        before = time.time()
        store.record_connection(peer_id, 101)
        after = time.time()

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert info.temp is False
        assert before <= info.first_seen <= after
        assert 101 in info.conns

    def test_second_connection_does_not_reset_first_seen(self, store, peer_id):
        """Subsequent record_connection calls don't overwrite first_seen."""
        store.record_connection(peer_id, 101)
        first_seen = store.get_tag_info(peer_id).first_seen

        store.record_connection(peer_id, 102)
        assert store.get_tag_info(peer_id).first_seen == first_seen

    def test_entry_deleted_on_last_disconnect(self, store, peer_id):
        """Removing the last connection deletes the entire tag entry."""
        store.tag_peer(peer_id, "test", 10)
        store.protect(peer_id, "relay")
        store.record_connection(peer_id, 101)
        store.remove_connection(peer_id, 101)

        # Entry and protection should both be gone
        assert store.get_tag_info(peer_id) is None
        assert store.is_protected(peer_id) is False

    def test_partial_disconnect_preserves_entry(self, store, peer_id):
        """Removing one of two connections does NOT delete the entry."""
        store.tag_peer(peer_id, "test", 10)
        store.record_connection(peer_id, 101)
        store.record_connection(peer_id, 102)
        store.remove_connection(peer_id, 101)

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert 102 in info.conns

    def test_get_tag_info_returns_copy(self, store, peer_id):
        """get_tag_info returns a defensive copy; mutations don't affect the store."""
        store.tag_peer(peer_id, "test", 10)
        info = store.get_tag_info(peer_id)

        # Mutate the returned copy
        info.tags["injected"] = 999
        info.value = 999

        # Store must be unchanged
        fresh = store.get_tag_info(peer_id)
        assert "injected" not in fresh.tags
        assert fresh.value == 10

    def test_upsert_tag_creates_temp_entry(self, store, peer_id):
        """upsert_tag on an unknown peer creates a temp entry."""
        store.upsert_tag(peer_id, "score", lambda x: x + 5)
        info = store.get_tag_info(peer_id)
        assert info is not None
        assert info.temp is True
        assert info.tags["score"] == 5


class TestTagStoreNotifee:
    """Test TagStoreNotifee bridges swarm events into TagStore."""

    @pytest.fixture
    def store(self):
        return TagStore()

    @pytest.fixture
    def peer_id(self):
        return ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")

    def _make_conn(self, peer_id, conn_id_override=None):
        """Build a minimal mock INetConn."""
        conn = MagicMock()
        conn.muxed_conn.peer_id = peer_id
        if conn_id_override is not None:
            conn.__hash__ = lambda self: conn_id_override  # type: ignore[assignment]
        return conn

    @pytest.mark.trio
    async def test_connected_records_connection(self, store, peer_id):
        """TagStoreNotifee.connected() calls record_connection."""
        notifee = TagStoreNotifee(store)
        conn = self._make_conn(peer_id)
        network = MagicMock()

        await notifee.connected(network, conn)

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert id(conn) in info.conns
        assert info.temp is False

    @pytest.mark.trio
    async def test_disconnected_removes_entry_when_last(self, store, peer_id):
        # TagStoreNotifee.disconnected() deletes the entry when
        # last connection leaves.
        notifee = TagStoreNotifee(store)
        conn = self._make_conn(peer_id)
        network = MagicMock()

        await notifee.connected(network, conn)
        assert store.get_tag_info(peer_id) is not None

        await notifee.disconnected(network, conn)
        assert store.get_tag_info(peer_id) is None

    @pytest.mark.trio
    async def test_disconnected_partial_keeps_entry(self, store, peer_id):
        """TagStoreNotifee.disconnected() keeps entry while other connections exist."""
        notifee = TagStoreNotifee(store)
        conn_a = self._make_conn(peer_id)
        conn_b = self._make_conn(peer_id)
        network = MagicMock()

        await notifee.connected(network, conn_a)
        await notifee.connected(network, conn_b)
        await notifee.disconnected(network, conn_a)

        info = store.get_tag_info(peer_id)
        assert info is not None
        assert id(conn_b) in info.conns

    @pytest.mark.trio
    async def test_early_tag_survives_connect(self, store, peer_id):
        """Tags applied before connect are preserved and temp flips to False."""
        store.tag_peer(peer_id, "dht", 15)
        assert store.get_tag_info(peer_id).temp is True

        notifee = TagStoreNotifee(store)
        conn = self._make_conn(peer_id)
        network = MagicMock()
        await notifee.connected(network, conn)

        info = store.get_tag_info(peer_id)
        assert info.temp is False
        assert info.tags["dht"] == 15  # tag survived the connect


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
