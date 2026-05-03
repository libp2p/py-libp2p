"""
Typed dataclass wrappers for Bitswap wantlist entries and messages.

Provides a clean, self-documenting Python API over the raw protobuf
Message format. All types here are pure Python dataclasses — no
protobuf dependency. Convert to/from protobuf via messages.py helpers.

Usage:
    from libp2p.bitswap.wantlist import (
        WantType, BlockPresenceType,
        WantlistEntry, Wantlist,
        BlockPresence, BitswapMessage,
    )

    # Build a wantlist
    wl = Wantlist()
    wl.add(my_cid, want_type=WantType.Block, send_dont_have=True)
    wl.add(other_cid, want_type=WantType.Have)

    # Build a full message
    msg = BitswapMessage()
    msg.add_want(my_cid, want_type=WantType.Block)
    msg.add_block(root_cid, block_data)
    msg.add_have(peer_cid)
    msg.add_dont_have(missing_cid)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .cid import CIDInput, cid_to_bytes
from .pb.bitswap_pb2 import Message as PBMessage

# ── enums ─────────────────────────────────────────────────────────────────────


class WantType(Enum):
    """
    Type of want request (Bitswap 1.2.0 wantType field).

    Block = 0  →  "Send me the full block bytes."
    Have  = 1  →  "Just tell me if you have it (HAVE/DONT_HAVE response)."
                  Cheaper than Block — useful for presence checks before
                  committing to a full block transfer.
    """

    Block = 0
    Have = 1


class BlockPresenceType(Enum):
    """
    Type of block presence response (Bitswap 1.2.0 BlockPresence.type field).

    Have    = 0  →  Peer has the block and can send it.
    DontHave = 1 →  Peer does not have the block.
    """

    Have = 0
    DontHave = 1


# ── wantlist dataclasses ──────────────────────────────────────────────────────


@dataclass
class WantlistEntry:
    """
    A single entry in a Bitswap wantlist.

    Prefer constructing via WantlistEntry.from_cid() which normalises
    any CIDInput form to raw bytes.

    Attributes:
        cid:            CID of the requested block as raw bytes.
        priority:       Request urgency. Higher = more urgent. Default 1.
        cancel:         True to cancel a previously sent want for this CID.
        want_type:      WantType.Block (full data) or WantType.Have (presence).
        send_dont_have: If True, ask the peer to send an explicit DontHave
                        response when it doesn't have the block.

    """

    cid: bytes
    priority: int = 1
    cancel: bool = False
    want_type: WantType = WantType.Block
    send_dont_have: bool = False

    @classmethod
    def from_cid(
        cls,
        cid: CIDInput,
        priority: int = 1,
        cancel: bool = False,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = False,
    ) -> WantlistEntry:
        """Create a WantlistEntry from any CIDInput form."""
        return cls(
            cid=cid_to_bytes(cid),
            priority=priority,
            cancel=cancel,
            want_type=want_type,
            send_dont_have=send_dont_have,
        )


@dataclass
class Wantlist:
    """
    A collection of wantlist entries.

    Attributes:
        entries: List of WantlistEntry items.
        full:    True = this replaces the peer's entire wantlist.
                 False (default) = delta update, adds/cancels entries.

    Example:
        >>> wl = Wantlist()
        >>> wl.add(cid1, want_type=WantType.Block, send_dont_have=True)
        >>> wl.add(cid2, want_type=WantType.Have)
        >>> wl.cancel(cid3)
        >>> print(len(wl))   # 3

    """

    entries: list[WantlistEntry] = field(default_factory=list)
    full: bool = False

    def add(
        self,
        cid: CIDInput,
        priority: int = 1,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = False,
    ) -> None:
        """Add a want entry for the given CID."""
        self.entries.append(
            WantlistEntry.from_cid(
                cid,
                priority=priority,
                want_type=want_type,
                send_dont_have=send_dont_have,
            )
        )

    def cancel(self, cid: CIDInput) -> None:
        """Add a cancel entry for a previously wanted CID."""
        self.entries.append(WantlistEntry.from_cid(cid, cancel=True))

    def contains(self, cid: CIDInput) -> bool:
        """Return True if any non-cancel entry exists for this CID."""
        cid_bytes = cid_to_bytes(cid)
        return any(e.cid == cid_bytes and not e.cancel for e in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)


# ── message dataclasses ───────────────────────────────────────────────────────


@dataclass
class BlockPresence:
    """
    A HAVE or DONT_HAVE response for a specific CID (Bitswap 1.2.0).

    Use the class-method constructors for convenience:
        BlockPresence.have(cid)
        BlockPresence.dont_have(cid)
    """

    cid: bytes
    type: BlockPresenceType

    @classmethod
    def have(cls, cid: CIDInput) -> BlockPresence:
        """Create a HAVE response."""
        return cls(cid=cid_to_bytes(cid), type=BlockPresenceType.Have)

    @classmethod
    def dont_have(cls, cid: CIDInput) -> BlockPresence:
        """Create a DONT_HAVE response."""
        return cls(cid=cid_to_bytes(cid), type=BlockPresenceType.DontHave)


@dataclass
class BitswapMessage:
    """
    High-level typed representation of a Bitswap protocol message.

    Wraps the three main message components with typed fields and
    convenience builder methods. Does not depend on protobuf directly —
    convert to/from protobuf using to_proto() / from_proto().

    Attributes:
        wantlist:        Optional wantlist (want/cancel entries).
        blocks:          List of (cid_bytes, block_data) block payloads.
        block_presences: List of HAVE/DONT_HAVE presence responses.
        pending_bytes:   Bytes queued to send (v1.2.0 flow-control hint).

    Properties:
        is_want         True if the message contains want entries.
        has_blocks      True if the message contains block payloads.
        has_presences   True if the message contains HAVE/DONT_HAVE entries.

    Example:
        >>> msg = BitswapMessage()
        >>> msg.add_want(cid1, want_type=WantType.Block, send_dont_have=True)
        >>> msg.add_want(cid2, want_type=WantType.Have)
        >>> msg.add_block(root_cid, data)
        >>> msg.add_have(cid3)
        >>> msg.add_dont_have(cid4)
        >>> assert msg.is_want and msg.has_blocks and msg.has_presences

    """

    wantlist: Wantlist | None = None
    blocks: list[tuple[bytes, bytes]] = field(default_factory=list)  # (cid, data)
    block_presences: list[BlockPresence] = field(default_factory=list)
    pending_bytes: int = 0

    # ── read-only properties ──────────────────────────────────────────────────

    @property
    def is_want(self) -> bool:
        """True if this message contains wantlist entries."""
        return self.wantlist is not None and bool(self.wantlist)

    @property
    def has_blocks(self) -> bool:
        """True if this message carries block payloads."""
        return bool(self.blocks)

    @property
    def has_presences(self) -> bool:
        """True if this message carries HAVE/DONT_HAVE responses."""
        return bool(self.block_presences)

    # ── builder methods ───────────────────────────────────────────────────────

    def add_want(
        self,
        cid: CIDInput,
        priority: int = 1,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = False,
    ) -> None:
        """Add a want entry. Creates the wantlist if not yet present."""
        if self.wantlist is None:
            self.wantlist = Wantlist()
        self.wantlist.add(
            cid,
            priority=priority,
            want_type=want_type,
            send_dont_have=send_dont_have,
        )

    def cancel_want(self, cid: CIDInput) -> None:
        """Add a cancel entry for a previously wanted CID."""
        if self.wantlist is None:
            self.wantlist = Wantlist()
        self.wantlist.cancel(cid)

    def add_block(self, cid: CIDInput, data: bytes) -> None:
        """Add a block payload to this message."""
        self.blocks.append((cid_to_bytes(cid), data))

    def add_have(self, cid: CIDInput) -> None:
        """Add a HAVE presence response."""
        self.block_presences.append(BlockPresence.have(cid))

    def add_dont_have(self, cid: CIDInput) -> None:
        """Add a DONT_HAVE presence response."""
        self.block_presences.append(BlockPresence.dont_have(cid))

    # ── protobuf conversion ───────────────────────────────────────────────────

    def to_proto(self) -> PBMessage:
        """
        Convert to a raw protobuf Message object (pb.bitswap_pb2.Message).

        Returns:
            A populated protobuf Message ready for serialisation.

        """
        proto = PBMessage()

        if self.wantlist is not None:
            for entry in self.wantlist.entries:
                pb_entry = proto.wantlist.entries.add()
                pb_entry.block = entry.cid
                pb_entry.priority = entry.priority
                pb_entry.cancel = entry.cancel
                pb_entry.wantType = entry.want_type.value  # type: ignore[assignment]
                pb_entry.sendDontHave = entry.send_dont_have
            proto.wantlist.full = self.wantlist.full

        for cid_bytes, data in self.blocks:
            from .cid import get_cid_prefix

            pb_block = proto.payload.add()
            pb_block.prefix = get_cid_prefix(cid_bytes)
            pb_block.data = data

        for presence in self.block_presences:
            pb_presence = proto.blockPresences.add()
            pb_presence.cid = presence.cid
            pb_presence.type = presence.type.value  # type: ignore[assignment]

        if self.pending_bytes:
            proto.pendingBytes = self.pending_bytes

        return proto

    @classmethod
    def from_proto(cls, proto: PBMessage) -> BitswapMessage:
        """
        Build a BitswapMessage from a raw protobuf Message object.

        Args:
            proto: A pb.bitswap_pb2.Message instance.

        Returns:
            A populated BitswapMessage dataclass.

        """
        from .cid import reconstruct_cid_from_prefix_and_data

        msg = cls()

        if proto.HasField("wantlist") and proto.wantlist.entries:
            wl = Wantlist(full=proto.wantlist.full)
            for e in proto.wantlist.entries:
                wl.entries.append(
                    WantlistEntry(
                        cid=bytes(e.block),
                        priority=e.priority,
                        cancel=e.cancel,
                        want_type=WantType(e.wantType),
                        send_dont_have=e.sendDontHave,
                    )
                )
            msg.wantlist = wl

        for pb_block in proto.payload:
            cid_bytes = reconstruct_cid_from_prefix_and_data(
                bytes(pb_block.prefix), bytes(pb_block.data)
            )
            msg.blocks.append((cid_bytes, bytes(pb_block.data)))

        for pb_presence in proto.blockPresences:
            msg.block_presences.append(
                BlockPresence(
                    cid=bytes(pb_presence.cid),
                    type=BlockPresenceType(pb_presence.type),
                )
            )

        msg.pending_bytes = proto.pendingBytes
        return msg
