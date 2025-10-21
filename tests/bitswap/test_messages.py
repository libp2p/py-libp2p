"""Unit tests for Bitswap messages."""

from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.messages import (
    create_block_message_v100,
    create_block_message_v110,
    create_block_presence_message,
    create_message,
    create_wantlist_entry,
    create_wantlist_message,
)
from libp2p.bitswap.pb import bitswap_pb2


class TestWantlistEntry:
    """Test wantlist entry creation."""

    def test_create_basic_entry(self):
        """Test creating a basic wantlist entry."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid)

        assert entry.block == cid
        assert entry.priority == 1
        assert entry.cancel is False

    def test_create_entry_with_priority(self):
        """Test creating entry with custom priority."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, priority=10)

        assert entry.priority == 10

    def test_create_cancel_entry(self):
        """Test creating a cancel entry."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, cancel=True)

        assert entry.cancel is True

    def test_create_entry_v120_fields(self):
        """Test creating entry with v1.2.0 fields."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, want_type=1, send_dont_have=True)

        assert entry.wantType == 1
        assert entry.sendDontHave is True


class TestWantlistMessage:
    """Test wantlist message creation."""

    def test_create_empty_wantlist(self):
        """Test creating message with empty wantlist."""
        msg = create_wantlist_message([])

        assert len(msg.wantlist.entries) == 0

    def test_create_wantlist_with_entries(self):
        """Test creating wantlist with entries."""
        cid1 = compute_cid_v1(b"data1")
        cid2 = compute_cid_v1(b"data2")

        entry1 = create_wantlist_entry(cid1, priority=5)
        entry2 = create_wantlist_entry(cid2, priority=10)

        msg = create_wantlist_message([entry1, entry2])

        assert len(msg.wantlist.entries) == 2
        assert msg.wantlist.entries[0].block == cid1
        assert msg.wantlist.entries[1].block == cid2

    def test_create_full_wantlist(self):
        """Test creating full wantlist message."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid)

        msg = create_wantlist_message([entry], full=True)

        assert msg.wantlist.full is True


class TestBlockMessages:
    """Test block message creation."""

    def test_create_block_message_v100(self):
        """Test creating v1.0.0 block message."""
        blocks = [b"block1", b"block2", b"block3"]
        msg = create_block_message_v100(blocks)

        assert len(msg.payload) == 3
        assert msg.payload[0].data == b"block1"
        assert msg.payload[1].data == b"block2"
        assert msg.payload[2].data == b"block3"

    def test_create_block_message_v110(self):
        """Test creating v1.1.0 block message with prefixes."""
        cid1 = compute_cid_v1(b"block1")
        cid2 = compute_cid_v1(b"block2")

        blocks = [
            (cid1, b"block1"),
            (cid2, b"block2"),
        ]

        msg = create_block_message_v110(blocks)

        assert len(msg.payload) == 2
        assert msg.payload[0].data == b"block1"
        assert msg.payload[1].data == b"block2"
        # Prefixes should be set
        assert len(msg.payload[0].prefix) > 0
        assert len(msg.payload[1].prefix) > 0

    def test_create_block_presence_message(self):
        """Test creating block presence message."""
        cid1 = compute_cid_v1(b"block1")
        cid2 = compute_cid_v1(b"block2")

        presences = [
            (cid1, True),  # Have
            (cid2, False),  # DontHave
        ]

        msg = create_block_presence_message(presences)

        assert len(msg.blockPresences) == 2


class TestCreateMessage:
    """Test combined message creation."""

    def test_create_message_with_wantlist(self):
        """Test creating message with wantlist."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, priority=5)

        msg = create_message(wantlist_entries=[entry])

        assert len(msg.wantlist.entries) == 1
        assert msg.wantlist.entries[0].block == cid

    def test_create_message_with_blocks(self):
        """Test creating message with blocks."""
        blocks = [b"block1", b"block2"]
        msg = create_message(blocks_v100=blocks)

        assert len(msg.blocks) == 2

    def test_create_message_with_both(self):
        """Test creating message with wantlist and blocks."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid)
        blocks = [b"block1"]

        msg = create_message(wantlist_entries=[entry], blocks_v100=blocks)

        assert len(msg.wantlist.entries) == 1
        assert len(msg.blocks) == 1

    def test_serialize_deserialize(self):
        """Test message serialization and deserialization."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, priority=7)

        msg = create_message(wantlist_entries=[entry])
        serialized = msg.SerializeToString()

        # Deserialize
        new_msg = bitswap_pb2.Message()
        new_msg.ParseFromString(serialized)

        assert len(new_msg.wantlist.entries) == 1
        assert new_msg.wantlist.entries[0].block == cid
        assert new_msg.wantlist.entries[0].priority == 7
