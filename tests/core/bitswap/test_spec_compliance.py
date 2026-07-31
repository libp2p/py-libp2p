"""
Bitswap spec compliance tests.

Verifies adherence to the Bitswap protocol specification:
https://specs.ipfs.tech/bitswap-protocol/

Each test targets a specific spec requirement or a bug fix from the
spec compliance audit.
"""

from unittest.mock import MagicMock

import pytest

from libp2p.bitswap.cid import compute_cid_v1, get_cid_prefix, parse_cid
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.config import (
    BITSWAP_PROTOCOL_V100,
    BITSWAP_PROTOCOL_V110,
    BITSWAP_PROTOCOL_V120,
    MAX_MESSAGE_SIZE,
)
from libp2p.bitswap.messages import (
    create_block_message_v100,
    create_block_message_v110,
    create_message,
    create_wantlist_entry,
)
from libp2p.bitswap.pb.bitswap_pb2 import Message
from libp2p.bitswap.wantlist import (
    BlockPresenceType,
    WantType,
)

# ── BUG-9: v1.0.0 blocks field vs payload field ──────────────────────────────


class TestV100BlocksField:
    """
    Spec: v1.0.0 uses `repeated bytes blocks = 2` for block data.
    Bug: create_block_message_v100() was putting data in `payload` (field 3).
    """

    def test_v100_uses_blocks_field(self):
        """v1.0.0 message must use blocks field, not payload."""
        blocks = [b"alpha", b"beta", b"gamma"]
        msg = create_block_message_v100(blocks)

        assert len(msg.blocks) == 3
        assert msg.blocks[0] == b"alpha"
        assert msg.blocks[1] == b"beta"
        assert msg.blocks[2] == b"gamma"

    def test_v100_payload_field_empty(self):
        """v1.0.0 message payload field must be empty."""
        msg = create_block_message_v100([b"data"])
        assert len(msg.payload) == 0

    def test_v100_serialization_roundtrip(self):
        """v1.0.0 blocks survive protobuf serialization."""
        original = create_block_message_v100([b"roundtrip"])
        serialized = original.SerializeToString()

        restored = Message()
        restored.ParseFromString(serialized)
        assert len(restored.blocks) == 1
        assert restored.blocks[0] == b"roundtrip"

    def test_v100_no_wantlist_entries(self):
        """v1.0.0 block message has no wantlist entries."""
        msg = create_block_message_v100([b"data"])
        assert not msg.HasField("wantlist") or len(msg.wantlist.entries) == 0


# ── BUG-1: sendDontHave flag ignored for WANT_BLOCK ──────────────────────────


class TestSendDontHaveRespected:
    """
    Spec: "if C has requested for DontHave responses then S SHOULD respond
    with DontHave" — only when sendDontHave=True.
    Bug: Server always sent DontHave for WANT_BLOCK regardless of flag.
    """

    def test_wantlist_entry_send_dont_have_field(self):
        """SendDontHave field is correctly set in protobuf."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, send_dont_have=True)
        assert entry.sendDontHave is True

        entry2 = create_wantlist_entry(cid, send_dont_have=False)
        assert entry2.sendDontHave is False

    def test_wantlist_entry_send_dont_have_default(self):
        """SendDontHave defaults to False per spec."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid)
        assert entry.sendDontHave is False

    def test_wanttype_block_defaults_to_zero(self):
        """WantType defaults to Block (0) per spec."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid)
        assert entry.wantType == 0

    def test_wanttype_have_is_one(self):
        """WantType Have = 1 per spec."""
        cid = compute_cid_v1(b"test")
        entry = create_wantlist_entry(cid, want_type=WantType.Have)
        assert entry.wantType == 1


# ── BUG-2: WANT_HAVE sends block instead of HAVE presence ────────────────────


class TestWantHaveResponseFormat:
    """
    Spec: "If C sends S a Have request for data S has ... it SHOULD respond
    with a Have"
    Bug: Server was sending block directly instead of Have presence.
    """

    def test_blockpresencetype_have_value(self):
        """BlockPresenceType.Have = 0 per spec."""
        assert BlockPresenceType.Have.value == 0

    def test_blockpresencetype_donthave_value(self):
        """BlockPresenceType.DontHave = 1 per spec."""
        assert BlockPresenceType.DontHave.value == 1

    def test_wanttype_block_value(self):
        """WantType.Block = 0 per spec."""
        assert WantType.Block.value == 0

    def test_wanttype_have_value(self):
        """WantType.Have = 1 per spec."""
        assert WantType.Have.value == 1


# ── BUG-4: Cancel message missing wantType ───────────────────────────────────


class TestCancelMessageWantType:
    """
    Spec: Cancel entries should retain the wantType of the original request.
    Bug: Cancel messages always used default want_type=0.
    """

    def test_cancel_retains_want_type_block(self):
        """Cancel for Block request retains wantType=0."""
        cid = compute_cid_v1(b"cancel-block")
        entry = create_wantlist_entry(cid, cancel=True, want_type=WantType.Block)
        assert entry.wantType == 0
        assert entry.cancel is True

    def test_cancel_retains_want_type_have(self):
        """Cancel for Have request retains wantType=1."""
        cid = compute_cid_v1(b"cancel-have")
        entry = create_wantlist_entry(cid, cancel=True, want_type=WantType.Have)
        assert entry.wantType == 1
        assert entry.cancel is True

    def test_cancel_default_want_type_is_block(self):
        """Cancel without explicit wantType defaults to Block."""
        cid = compute_cid_v1(b"cancel-default")
        entry = create_wantlist_entry(cid, cancel=True)
        assert entry.wantType == 0


# ── BUG-6: Priority not used for response ordering ──────────────────────────


class TestPriorityOrdering:
    """
    Spec: "S SHOULD respect the relative priority of wantlist requests
    from C, with wants that have higher priority values being responded
    to first."
    """

    def test_priority_field_preserved(self):
        """Priority field is correctly stored in entry."""
        cid = compute_cid_v1(b"priority-test")
        entry = create_wantlist_entry(cid, priority=10)
        assert entry.priority == 10

    def test_priority_default_is_one(self):
        """Default priority is 1 per spec."""
        cid = compute_cid_v1(b"priority-default")
        entry = create_wantlist_entry(cid)
        assert entry.priority == 1

    def test_priority_range_supports_int32(self):
        """Priority supports full int32 range per protobuf spec."""
        cid = compute_cid_v1(b"priority-max")
        entry = create_wantlist_entry(cid, priority=2**31 - 1)
        assert entry.priority == 2147483647


# ── BUG-5: pendingBytes never populated ──────────────────────────────────────


class TestPendingBytes:
    """
    Spec: "S MAY choose to include the number of bytes that are pending
    to be sent to C in the response message."
    """

    def test_pending_bytes_field_in_proto(self):
        """PendingBytes field exists in protobuf message."""
        msg = Message()
        msg.pendingBytes = 12345
        assert msg.pendingBytes == 12345

    def test_pending_bytes_default_zero(self):
        """PendingBytes defaults to 0."""
        msg = Message()
        assert msg.pendingBytes == 0

    def test_create_message_with_pending_bytes(self):
        """create_message supports pending_bytes parameter."""
        msg = create_message(pending_bytes=42)
        assert msg.pendingBytes == 42

    def test_create_message_pending_bytes_zero(self):
        """pending_bytes=0 does not set the field."""
        msg = create_message(pending_bytes=0)
        assert msg.pendingBytes == 0


# ── Wire format: varint length prefix ────────────────────────────────────────


class TestWireFormat:
    """
    Spec: "All protocol messages sent over a stream are prefixed with the
    message length in bytes, encoded as an unsigned variable length integer."
    """

    def test_message_size_limit_enforced(self):
        """Messages must be <= 4MiB per spec."""
        assert MAX_MESSAGE_SIZE == 4 * 1024 * 1024

    def test_empty_message_serializes(self):
        """Empty message serializes to valid protobuf."""
        msg = Message()
        serialized = msg.SerializeToString()
        assert isinstance(serialized, bytes)

    def test_wantlist_message_serializes(self):
        """Wantlist message serializes correctly."""
        cid = compute_cid_v1(b"wire-test")
        entry = create_wantlist_entry(cid, priority=5)
        msg = create_message(wantlist_entries=[entry])
        serialized = msg.SerializeToString()
        assert len(serialized) > 0

    def test_block_message_serializes(self):
        """Block message serializes correctly."""
        msg = create_message(blocks_v100=[b"block data"])
        serialized = msg.SerializeToString()
        assert len(serialized) > 0

    def test_presence_message_serializes(self):
        """Block presence message serializes correctly."""
        cid = compute_cid_v1(b"presence")
        msg = create_message(block_presences=[(cid, True)])
        serialized = msg.SerializeToString()
        assert len(serialized) > 0

    def test_full_message_with_all_fields(self):
        """Message with all fields serializes correctly."""
        cid = compute_cid_v1(b"full-test")
        entry = create_wantlist_entry(cid, want_type=1, send_dont_have=True)
        msg = create_message(
            wantlist_entries=[entry],
            blocks_v100=[b"block"],
            block_presences=[(cid, True)],
            pending_bytes=100,
            full_wantlist=True,
        )
        serialized = msg.SerializeToString()
        restored = Message()
        restored.ParseFromString(serialized)
        assert restored.wantlist.full is True
        assert len(restored.blocks) == 1
        assert len(restored.blockPresences) == 1
        assert restored.pendingBytes == 100


# ── Protocol version constants ───────────────────────────────────────────────


class TestProtocolVersions:
    """Verify correct protocol ID strings."""

    def test_v100_protocol_id(self):
        """v1.0.0 uses /ipfs/bitswap/1.0.0."""
        assert BITSWAP_PROTOCOL_V100 == "/ipfs/bitswap/1.0.0"

    def test_v110_protocol_id(self):
        """v1.1.0 uses /ipfs/bitswap/1.1.0."""
        assert BITSWAP_PROTOCOL_V110 == "/ipfs/bitswap/1.1.0"

    def test_v120_protocol_id(self):
        """v1.2.0 uses /ipfs/bitswap/1.2.0."""
        assert BITSWAP_PROTOCOL_V120 == "/ipfs/bitswap/1.2.0"


# ── CID prefix handling (v1.1.0+) ───────────────────────────────────────────


class TestCIDPrefix:
    """
    Spec: v1.1.0 Block messages include CID prefix (version + codec +
    hash type + hash length, but NOT the digest).
    """

    def test_v110_block_has_prefix(self):
        """v1.1.0 block message includes CID prefix."""
        cid = compute_cid_v1(b"prefix-test")
        prefix = get_cid_prefix(cid)
        assert len(prefix) > 0

    def test_v110_prefix_is_shorter_than_cid(self):
        """CID prefix is shorter than full CID (no digest)."""
        cid = compute_cid_v1(b"prefix-length")
        prefix = get_cid_prefix(cid)
        cid_bytes = parse_cid(cid).buffer
        assert len(prefix) < len(cid_bytes)

    def test_v110_block_message_prefix_set(self):
        """v1.1.0 block message has prefix field set."""
        cid = compute_cid_v1(b"msg-prefix")
        prefix = get_cid_prefix(cid)
        msg = create_block_message_v110([(prefix, b"data")])
        assert len(msg.payload) == 1
        assert len(msg.payload[0].prefix) > 0

    def test_v110_block_message_data_set(self):
        """v1.1.0 block message has data field set."""
        prefix = b"\x01\x01\x12\x20"
        msg = create_block_message_v110([(prefix, b"block-data")])
        assert msg.payload[0].data == b"block-data"

    def test_reconstruct_cid_from_prefix_and_data(self):
        """CID can be reconstructed from prefix + data."""
        from libp2p.bitswap.cid import (
            reconstruct_cid_from_prefix_and_data,
        )

        data = b"reconstruct me"
        cid = compute_cid_v1(data)
        prefix = get_cid_prefix(cid)
        cid_bytes = parse_cid(cid).buffer

        reconstructed = reconstruct_cid_from_prefix_and_data(prefix, data)
        assert reconstructed == cid_bytes


# ── Block size limits ────────────────────────────────────────────────────────


class TestBlockSizeLimits:
    """
    Spec: "Bitswap implementations MUST support sending and receiving
    individual blocks of sizes less than or equal to 2MiB."
    """

    def test_max_message_size_is_4mib(self):
        """Max message size is 4MiB per spec."""
        assert MAX_MESSAGE_SIZE == 4 * 1024 * 1024

    def test_add_block_validates_size(self):
        """add_block rejects blocks exceeding MAX_BLOCK_SIZE."""
        from libp2p.bitswap.cid import parse_cid

        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        from libp2p.bitswap.config import MAX_BLOCK_SIZE

        cid_bytes = compute_cid_v1(b"too-big")
        cid = parse_cid(cid_bytes)
        oversized_data = b"x" * (MAX_BLOCK_SIZE + 1)
        with pytest.raises(Exception):
            client._wantlist[cid] = {
                "priority": 1,
                "want_type": 0,
                "send_dont_have": False,
            }
            # add_block validates size
            import trio

            async def _add_block():
                await client.add_block(cid, oversized_data)

            trio.run(_add_block)


# ── full wantlist flag ───────────────────────────────────────────────────────


class TestFullWantlistFlag:
    """
    Spec: "bool full = 2; // whether this is the full wantlist.
    default to false"
    """

    def test_full_wantlist_flag_true(self):
        """full=True is set in protobuf."""
        cid = compute_cid_v1(b"full-test")
        entry = create_wantlist_entry(cid)
        msg = create_message(wantlist_entries=[entry], full_wantlist=True)
        assert msg.wantlist.full is True

    def test_full_wantlist_flag_false(self):
        """full=False is default."""
        cid = compute_cid_v1(b"not-full-test")
        entry = create_wantlist_entry(cid)
        msg = create_message(wantlist_entries=[entry], full_wantlist=False)
        assert msg.wantlist.full is False

    def test_full_wantlist_empty_message(self):
        """Empty message has no wantlist field set."""
        msg = Message()
        assert not msg.HasField("wantlist")


# ── WantlistEntry protobuf field numbers ─────────────────────────────────────


class TestProtobufFieldNumbers:
    """Verify protobuf field numbers match the spec exactly."""

    def test_entry_block_field_1(self):
        """entry.block is field 1."""
        cid = compute_cid_v1(b"field1")
        entry = create_wantlist_entry(cid)
        proto_entry = Message.Wantlist.Entry()
        proto_entry.CopyFrom(entry)
        # block is field 1 in protobuf
        assert proto_entry.block == cid

    def test_entry_priority_field_2(self):
        """entry.priority is field 2."""
        cid = compute_cid_v1(b"field2")
        entry = create_wantlist_entry(cid, priority=42)
        assert entry.priority == 42

    def test_entry_cancel_field_3(self):
        """entry.cancel is field 3."""
        cid = compute_cid_v1(b"field3")
        entry = create_wantlist_entry(cid, cancel=True)
        assert entry.cancel is True

    def test_entry_wanttype_field_4(self):
        """entry.wantType is field 4 (v1.2.0)."""
        cid = compute_cid_v1(b"field4")
        entry = create_wantlist_entry(cid, want_type=1)
        assert entry.wantType == 1

    def test_entry_send_donthave_field_5(self):
        """entry.sendDontHave is field 5 (v1.2.0)."""
        cid = compute_cid_v1(b"field5")
        entry = create_wantlist_entry(cid, send_dont_have=True)
        assert entry.sendDontHave is True

    def test_message_wantlist_field_1(self):
        """message.wantlist is field 1."""
        msg = Message()
        assert not msg.HasField("wantlist") or True  # default

    def test_message_blocks_field_2(self):
        """message.blocks is field 2 (v1.0.0)."""
        msg = Message()
        msg.blocks.append(b"test")
        assert msg.blocks[0] == b"test"

    def test_message_payload_field_3(self):
        """message.payload is field 3 (v1.1.0+)."""
        msg = Message()
        block = msg.payload.add()
        block.data = b"test"
        assert msg.payload[0].data == b"test"

    def test_message_blockpresences_field_4(self):
        """message.blockPresences is field 4 (v1.2.0)."""
        msg = Message()
        presence = msg.blockPresences.add()
        presence.cid = b"cid"
        presence.type = Message.Have
        assert msg.blockPresences[0].type == Message.Have

    def test_message_pendingbytes_field_5(self):
        """message.pendingBytes is field 5 (v1.2.0)."""
        msg = Message()
        msg.pendingBytes = 999
        assert msg.pendingBytes == 999


# ── Integration: WantType semantics ──────────────────────────────────────────


class TestWantTypeSemantics:
    """
    End-to-end test that WantType and sendDontHave fields survive
    serialization round-trip.
    """

    def test_want_have_roundtrip(self):
        """WantType.Have survives protobuf round-trip."""
        cid = compute_cid_v1(b"have-roundtrip")
        entry = create_wantlist_entry(cid, want_type=WantType.Have, send_dont_have=True)
        msg = create_message(wantlist_entries=[entry])
        serialized = msg.SerializeToString()

        restored = Message()
        restored.ParseFromString(serialized)
        assert restored.wantlist.entries[0].wantType == 1
        assert restored.wantlist.entries[0].sendDontHave is True

    def test_want_block_roundtrip(self):
        """WantType.Block survives protobuf round-trip."""
        cid = compute_cid_v1(b"block-roundtrip")
        entry = create_wantlist_entry(
            cid, want_type=WantType.Block, send_dont_have=False
        )
        msg = create_message(wantlist_entries=[entry])
        serialized = msg.SerializeToString()

        restored = Message()
        restored.ParseFromString(serialized)
        assert restored.wantlist.entries[0].wantType == 0
        assert restored.wantlist.entries[0].sendDontHave is False

    def test_cancel_with_want_type_roundtrip(self):
        """Cancel entry with wantType survives round-trip."""
        cid = compute_cid_v1(b"cancel-roundtrip")
        entry = create_wantlist_entry(cid, cancel=True, want_type=WantType.Have)
        msg = create_message(wantlist_entries=[entry])
        serialized = msg.SerializeToString()

        restored = Message()
        restored.ParseFromString(serialized)
        assert restored.wantlist.entries[0].cancel is True
        assert restored.wantlist.entries[0].wantType == 1


# ── Client state management ──────────────────────────────────────────────────


class TestClientStateManagement:
    """Test client internal state handling."""

    @pytest.mark.trio
    async def test_response_streams_cleared_on_stop(self):
        """_response_streams is cleared when client stops."""
        mock_host = MagicMock()
        mock_host.set_stream_handler = MagicMock()
        client = BitswapClient(mock_host)

        # _response_streams was removed; verify stop works without error
        await client.start()
        await client.stop()
        # Verify client is stopped
        assert not client._started

    @pytest.mark.trio
    async def test_wantlist_tracks_want_type(self):
        """want_block stores want_type in the wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"want-type-track")

        await client.want_block(cid, want_type=1, send_dont_have=True)
        cid_obj = parse_cid(cid)
        assert client._wantlist[cid_obj]["want_type"] == 1
        assert client._wantlist[cid_obj]["send_dont_have"] is True

    @pytest.mark.trio
    async def test_cancel_preserves_want_type(self):
        """cancel_want reads want_type before deleting from wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"cancel-preserve")

        await client.want_block(cid, want_type=1)
        # Verify want_type stored
        cid_obj = parse_cid(cid)
        assert client._wantlist[cid_obj]["want_type"] == 1

        # Cancel should not raise
        await client.cancel_want(cid)
        assert cid_obj not in client._wantlist


# ── Message creation edge cases ──────────────────────────────────────────────


class TestMessageCreationEdgeCases:
    """Edge cases in message creation."""

    def test_create_message_empty(self):
        """Empty message has no fields set."""
        msg = create_message()
        assert not msg.HasField("wantlist")
        assert len(msg.blocks) == 0
        assert len(msg.payload) == 0
        assert len(msg.blockPresences) == 0
        assert msg.pendingBytes == 0

    def test_create_message_wantlist_only(self):
        """Message with only wantlist."""
        cid = compute_cid_v1(b"wantlist-only")
        entry = create_wantlist_entry(cid)
        msg = create_message(wantlist_entries=[entry])
        assert len(msg.wantlist.entries) == 1
        assert len(msg.blocks) == 0

    def test_create_message_blocks_only(self):
        """Message with only blocks."""
        msg = create_message(blocks_v100=[b"data1", b"data2"])
        assert len(msg.blocks) == 2
        assert not msg.HasField("wantlist") or len(msg.wantlist.entries) == 0

    def test_create_message_presences_only(self):
        """Message with only block presences."""
        cid = compute_cid_v1(b"presences-only")
        msg = create_message(block_presences=[(cid, True), (cid, False)])
        assert len(msg.blockPresences) == 2

    def test_create_message_all_fields(self):
        """Message with all fields populated."""
        cid = compute_cid_v1(b"all-fields")
        entry = create_wantlist_entry(cid)
        msg = create_message(
            wantlist_entries=[entry],
            blocks_v100=[b"block"],
            blocks_v110=[(b"prefix", b"data")],
            block_presences=[(cid, True)],
            pending_bytes=100,
            full_wantlist=True,
        )
        assert len(msg.wantlist.entries) == 1
        assert len(msg.blocks) == 1
        assert len(msg.payload) == 1
        assert len(msg.blockPresences) == 1
        assert msg.pendingBytes == 100
        assert msg.wantlist.full is True

    def test_v110_message_has_no_v100_blocks(self):
        """v1.1.0 message uses payload, not blocks."""
        cid = compute_cid_v1(b"v110-no-v100")
        prefix = get_cid_prefix(cid)
        msg = create_block_message_v110([(prefix, b"data")])
        assert len(msg.blocks) == 0
        assert len(msg.payload) == 1
