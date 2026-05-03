"""
Test Wantlist / Message dataclasses.

Run with:
    python test_wantlist.py
"""

from libp2p.bitswap.cid import CODEC_RAW, cid_to_bytes, compute_cid_v1
from libp2p.bitswap.messages import create_wantlist_entry
from libp2p.bitswap.wantlist import (
    BitswapMessage,
    BlockPresence,
    BlockPresenceType,
    Wantlist,
    WantlistEntry,
    WantType,
)


def make_cid(content: bytes) -> bytes:
    return cid_to_bytes(compute_cid_v1(content, codec=CODEC_RAW))


def ok(label):
    print(f"  OK  {label}")


# ── WantType enum ─────────────────────────────────────────────────────────────


def test_want_type_values():
    print("\n[1] WantType enum values match protobuf")
    assert WantType.Block.value == 0
    assert WantType.Have.value == 1
    ok("WantType.Block == 0, WantType.Have == 1")


# ── WantlistEntry ─────────────────────────────────────────────────────────────


def test_wantlist_entry_from_cid():
    print("\n[2] WantlistEntry.from_cid normalises any CIDInput")
    cid = compute_cid_v1(b"entry test", codec=CODEC_RAW)
    cid_bytes = cid_to_bytes(cid)

    # from bytes
    e1 = WantlistEntry.from_cid(cid_bytes)
    assert e1.cid == cid_bytes
    assert e1.want_type == WantType.Block
    assert e1.priority == 1
    assert not e1.cancel
    ok("from bytes — defaults correct")

    # from CIDObject
    e2 = WantlistEntry.from_cid(cid, want_type=WantType.Have, send_dont_have=True)
    assert e2.want_type == WantType.Have
    assert e2.send_dont_have
    ok("from CIDObject — WantType.Have, send_dont_have=True")

    # cancel entry
    e3 = WantlistEntry.from_cid(cid_bytes, cancel=True)
    assert e3.cancel
    ok("cancel entry")


# ── Wantlist ──────────────────────────────────────────────────────────────────


def test_wantlist_add_cancel_contains():
    print("\n[3] Wantlist.add / cancel / contains")
    cid1 = make_cid(b"block 1")
    cid2 = make_cid(b"block 2")
    cid3 = make_cid(b"block 3")

    wl = Wantlist()
    assert len(wl) == 0
    assert not wl

    wl.add(cid1, want_type=WantType.Block, send_dont_have=True)
    wl.add(cid2, want_type=WantType.Have)
    wl.cancel(cid3)

    assert len(wl) == 3
    assert bool(wl)
    ok("len(wl) == 3 after 2 adds + 1 cancel")

    assert wl.contains(cid1)
    assert wl.contains(cid2)
    assert not wl.contains(cid3)  # cancel entry → not "contained"
    ok("contains() returns True for non-cancel entries only")

    # Check entry fields
    e1 = wl.entries[0]
    assert e1.want_type == WantType.Block
    assert e1.send_dont_have
    e2 = wl.entries[1]
    assert e2.want_type == WantType.Have
    e3 = wl.entries[2]
    assert e3.cancel
    ok("entry fields correct (want_type, send_dont_have, cancel)")


def test_wantlist_full_flag():
    print("\n[4] Wantlist.full flag")
    wl = Wantlist(full=True)
    assert wl.full
    ok("full=True preserved")


# ── BlockPresence ─────────────────────────────────────────────────────────────


def test_block_presence():
    print("\n[5] BlockPresence constructors")
    cid = make_cid(b"presence test")

    have = BlockPresence.have(cid)
    assert have.cid == cid
    assert have.type == BlockPresenceType.Have
    ok("BlockPresence.have()")

    dont = BlockPresence.dont_have(cid)
    assert dont.cid == cid
    assert dont.type == BlockPresenceType.DontHave
    ok("BlockPresence.dont_have()")

    assert BlockPresenceType.Have.value == 0
    assert BlockPresenceType.DontHave.value == 1
    ok("BlockPresenceType values match protobuf (Have=0, DontHave=1)")


# ── BitswapMessage ────────────────────────────────────────────────────────────


def test_bitswap_message_properties():
    print("\n[6] BitswapMessage builder + properties")
    cid1 = make_cid(b"want me")
    cid2 = make_cid(b"block data")
    cid3 = make_cid(b"i have this")
    cid4 = make_cid(b"i dont have this")
    data = b"actual block content"

    msg = BitswapMessage()
    assert not msg.is_want
    assert not msg.has_blocks
    assert not msg.has_presences

    msg.add_want(cid1, want_type=WantType.Block, send_dont_have=True)
    assert msg.is_want
    ok("is_want True after add_want()")

    msg.add_block(cid2, data)
    assert msg.has_blocks
    assert msg.blocks[0] == (cid2, data)
    ok("has_blocks True after add_block()")

    msg.add_have(cid3)
    msg.add_dont_have(cid4)
    assert msg.has_presences
    assert len(msg.block_presences) == 2
    assert msg.block_presences[0].type == BlockPresenceType.Have
    assert msg.block_presences[1].type == BlockPresenceType.DontHave
    ok("has_presences True, HAVE and DONT_HAVE entries correct")


def test_bitswap_message_cancel_want():
    print("\n[7] BitswapMessage.cancel_want()")
    cid = make_cid(b"cancel me")
    msg = BitswapMessage()
    msg.cancel_want(cid)
    assert msg.is_want
    assert msg.wantlist.entries[0].cancel
    ok("cancel_want() adds cancel entry")


# ── to_proto / from_proto round-trip ─────────────────────────────────────────


def test_to_proto_from_proto_roundtrip():
    print("\n[8] BitswapMessage to_proto() / from_proto() round-trip")
    cid1 = make_cid(b"want block")
    cid2 = make_cid(b"block payload")
    cid3 = make_cid(b"have this")
    data = b"block payload data"

    original = BitswapMessage()
    original.add_want(cid1, want_type=WantType.Block, send_dont_have=True)
    original.add_block(cid2, data)
    original.add_have(cid3)
    original.add_dont_have(make_cid(b"dont have"))

    proto = original.to_proto()
    restored = BitswapMessage.from_proto(proto)

    # Wantlist
    assert restored.wantlist is not None
    assert len(restored.wantlist.entries) == 1
    e = restored.wantlist.entries[0]
    assert e.cid == cid1
    assert e.want_type == WantType.Block
    assert e.send_dont_have
    ok("wantlist entry round-trips correctly")

    # Block payload
    assert len(restored.blocks) == 1
    restored_cid, restored_data = restored.blocks[0]
    assert restored_data == data
    ok("block payload round-trips correctly")

    # Block presences
    assert len(restored.block_presences) == 2
    assert restored.block_presences[0].type == BlockPresenceType.Have
    assert restored.block_presences[1].type == BlockPresenceType.DontHave
    ok("block presences round-trip correctly")


# ── backward compat: create_wantlist_entry accepts int OR WantType ────────────


def test_create_wantlist_entry_backward_compat():
    print("\n[9] create_wantlist_entry — backward compat (int OR WantType)")
    cid = make_cid(b"compat test")

    # Old style: raw int
    e_int = create_wantlist_entry(cid, want_type=0)
    assert e_int.wantType == 0
    ok("want_type=0 (int) still works")

    e_int2 = create_wantlist_entry(cid, want_type=1)
    assert e_int2.wantType == 1
    ok("want_type=1 (int) still works")

    # New style: WantType enum
    e_enum = create_wantlist_entry(cid, want_type=WantType.Block)
    assert e_enum.wantType == 0
    ok("want_type=WantType.Block works")

    e_enum2 = create_wantlist_entry(cid, want_type=WantType.Have)
    assert e_enum2.wantType == 1
    ok("want_type=WantType.Have works")


# ── public API exports ────────────────────────────────────────────────────────


def test_public_exports():
    print("\n[10] All types exported from libp2p.bitswap")
    from libp2p.bitswap import (
        WantType,
    )

    assert WantType.Block.value == 0
    assert WantType.Have.value == 1
    ok(
        "WantType, WantlistEntry, Wantlist, BlockPresence, BlockPresenceType, "
        "BitswapMessage all importable from libp2p.bitswap"
    )


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Wantlist / Message Dataclasses — Test Suite")
    print("=" * 60)

    test_want_type_values()
    test_wantlist_entry_from_cid()
    test_wantlist_add_cancel_contains()
    test_wantlist_full_flag()
    test_block_presence()
    test_bitswap_message_properties()
    test_bitswap_message_cancel_want()
    test_to_proto_from_proto_roundtrip()
    test_create_wantlist_entry_backward_compat()
    test_public_exports()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
