"""
Message construction helpers for Bitswap protocol.
Supports v1.0.0, v1.1.0, and v1.2.0 message formats.
"""

from .pb.bitswap_pb2 import Message


def create_wantlist_entry(
    block_cid: bytes,
    priority: int = 1,
    cancel: bool = False,
    want_type: int = 0,  # 0 = Block, 1 = Have (v1.2.0)
    send_dont_have: bool = False,  # v1.2.0
) -> Message.Wantlist.Entry:
    """
    Create a wantlist entry.

    Args:
        block_cid: The CID of the block
        priority: Priority of the request (higher = more important)
        cancel: Whether this cancels a previous request
        want_type: 0 for Block (full block), 1 for Have (just check if
            peer has it) - v1.2.0
        send_dont_have: Whether to send DontHave response if block not
            found - v1.2.0

    Returns:
        A wantlist entry

    """
    entry = Message.Wantlist.Entry()
    entry.block = block_cid
    entry.priority = priority
    entry.cancel = cancel
    # Type checkers don't like int assignment to enum, but protobuf accepts it
    entry.wantType = want_type  # type: ignore[assignment]  # v1.2.0 field
    entry.sendDontHave = send_dont_have  # v1.2.0 field
    return entry


def create_wantlist_message(
    entries: list[Message.Wantlist.Entry], full: bool = False
) -> Message:
    """
    Create a message with a wantlist.

    Args:
        entries: List of wantlist entries
        full: Whether this is the full wantlist or just updates

    Returns:
        A Bitswap message

    """
    msg = Message()
    msg.wantlist.entries.extend(entries)
    msg.wantlist.full = full
    return msg


def create_block_message_v100(blocks: list[bytes]) -> Message:
    """
    Create a message containing blocks (v1.0.0 format).

    Args:
        blocks: List of block data

    Returns:
        A Bitswap message

    """
    msg = Message()
    for data in blocks:
        block = msg.payload.add()
        block.data = data
    return msg


def create_block_message_v110(blocks: list[tuple[bytes, bytes]]) -> Message:
    """
    Create a message containing blocks with CID prefixes (v1.1.0+ format).

    Args:
        blocks: List of (prefix, data) tuples

    Returns:
        A Bitswap message

    """
    msg = Message()
    for prefix, data in blocks:
        block = msg.payload.add()
        block.prefix = prefix
        block.data = data
    return msg


def create_block_presence_message(presences: list[tuple[bytes, bool]]) -> Message:
    """
    Create a message with block presence information (v1.2.0).

    Args:
        presences: List of (cid, has_block) tuples where has_block is True
            for Have, False for DontHave

    Returns:
        A Bitswap message

    """
    msg = Message()
    for cid, has_block in presences:
        presence = msg.blockPresences.add()
        presence.cid = cid
        presence.type = Message.Have if has_block else Message.DontHave
    return msg


def create_message(
    wantlist_entries: list[Message.Wantlist.Entry] | None = None,
    blocks_v100: list[bytes] | None = None,
    blocks_v110: list[tuple[bytes, bytes]] | None = None,
    block_presences: list[tuple[bytes, bool]] | None = None,
    pending_bytes: int = 0,
    full_wantlist: bool = False,
) -> Message:
    """
    Create a complete Bitswap message supporting all protocol versions.

    Args:
        wantlist_entries: Optional list of wantlist entries
        blocks_v100: Optional list of blocks (v1.0.0 format)
        blocks_v110: Optional list of (prefix, data) tuples (v1.1.0+ format)
        block_presences: Optional list of (cid, has_block) tuples (v1.2.0)
        pending_bytes: Number of bytes queued to send (v1.2.0)
        full_wantlist: Whether the wantlist is complete

    Returns:
        A Bitswap message

    """
    msg = Message()

    if wantlist_entries:
        msg.wantlist.entries.extend(wantlist_entries)
        msg.wantlist.full = full_wantlist

    if blocks_v100:
        msg.blocks.extend(blocks_v100)

    if blocks_v110:
        for prefix, data in blocks_v110:
            block = msg.payload.add()
            block.prefix = prefix
            block.data = data

    if block_presences:
        for cid, has_block in block_presences:
            presence = msg.blockPresences.add()
            presence.cid = cid
            presence.type = Message.Have if has_block else Message.DontHave

    if pending_bytes > 0:
        msg.pendingBytes = pending_bytes

    return msg
