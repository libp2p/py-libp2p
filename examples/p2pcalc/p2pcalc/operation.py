# p2pcalc/operation.py — Spreadsheet operation encoding protocol
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
# IIT Jammu, B.Tech CSE 2024-2028
#
# Design principles:
#   - Operations are the unit of truth, never full state
#   - Every operation is deterministically replayable
#   - MessagePack for compact binary serialisation (faster than JSON on wire)
#   - Hybrid Logical Clocks (HLC) for causally-consistent ordering across peers
#     without requiring clock synchronisation
#
# SocialCalc command format (what EtherCalc actually sends):
#   "set A1 value 42"
#   "set B2 formula =SUM(A1:A5)"
#   "set A1:B5 bgcolor #ff0000"
#   "insertrow 3 1"
#   "deletecol C 2"
#
# We wrap these commands in a typed envelope and add HLC timestamps,
# peer identity, causal dependencies, and a content hash for integrity.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import hashlib
import time
import uuid

import msgpack

# ---------------------------------------------------------------------------
# Hybrid Logical Clock
# ---------------------------------------------------------------------------


class HLC:
    """
    Hybrid Logical Clock for causal ordering without clock sync.

    HLC combines physical time (for human readability) with a logical
    counter (for causal ordering when physical clocks agree). This gives
    us causally-consistent ordering across peers even with clock drift,
    which pure Lamport clocks or pure wall clocks cannot guarantee alone.

    Reference: Kulkarni et al., "Logical Physical Clocks" (2014)
    """

    def __init__(self):
        self._physical: int = 0  # milliseconds
        self._logical: int = 0

    def now(self) -> tuple[int, int]:
        """Generate a new HLC timestamp. Returns (physical_ms, logical)."""
        pt = int(time.time() * 1000)
        if pt > self._physical:
            self._physical = pt
            self._logical = 0
        else:
            self._logical += 1
        return (self._physical, self._logical)

    def update(self, remote_physical: int, remote_logical: int) -> tuple[int, int]:
        """Receive a remote HLC timestamp and advance local clock."""
        pt = int(time.time() * 1000)
        self._physical = max(self._physical, remote_physical, pt)
        if self._physical == remote_physical == pt:
            self._logical = max(self._logical, remote_logical) + 1
        elif self._physical == remote_physical:
            self._logical = max(self._logical, remote_logical) + 1
        elif self._physical == pt:
            self._logical += 1
        else:
            self._logical = 0
        return (self._physical, self._logical)

    def compare(
        self,
        a: tuple[int, int],
        b: tuple[int, int],
    ) -> int:
        """Compare two HLC timestamps. Returns -1, 0, or 1."""
        if a[0] != b[0]:
            return -1 if a[0] < b[0] else 1
        if a[1] != b[1]:
            return -1 if a[1] < b[1] else 1
        return 0


# Module-level singleton clock
_clock = HLC()


# ---------------------------------------------------------------------------
# Operation types
# ---------------------------------------------------------------------------


class OpType(IntEnum):
    # Cell operations (mapped from SocialCalc command strings)
    SET_CELL_VALUE = 0x01
    SET_CELL_FORMULA = 0x02
    SET_CELL_FORMAT = 0x03
    CLEAR_CELL = 0x04

    # Range operations
    SET_RANGE_FORMAT = 0x10
    COPY_RANGE = 0x11
    MOVE_RANGE = 0x12

    # Structural operations
    INSERT_ROW = 0x20
    DELETE_ROW = 0x21
    INSERT_COL = 0x22
    DELETE_COL = 0x23

    # Sheet operations
    SORT_SHEET = 0x30
    RENAME_SHEET = 0x31

    # Control
    SNAPSHOT_REQUEST = 0xF0  # late joiner asks for current state
    SNAPSHOT_CHUNK = 0xF1  # response: one chunk of snapshot
    HEARTBEAT = 0xFF  # peer presence signal


# ---------------------------------------------------------------------------
# Core Operation dataclass
# ---------------------------------------------------------------------------


@dataclass
class Operation:
    """
    A single spreadsheet operation in the P2PCalc protocol.

    Every mutation flowing through the GossipSub topic is an Operation.
    Operations are:
      - Totally ordered within a sheet via HLC timestamps
      - Deduplicated by op_id across the network
      - Self-describing: contain enough info to apply or undo
      - Compact: serialised with MessagePack (not JSON)
    """

    # Identity
    op_id: str  # UUID4 — globally unique, used for dedup
    peer_id: str  # libp2p peer ID of originating peer
    sheet_id: str  # EtherCalc room name (e.g. "my-spreadsheet")

    # Causality
    hlc_physical: int  # HLC physical component (ms)
    hlc_logical: int  # HLC logical component

    # Content
    op_type: int  # OpType enum value
    raw_command: str  # Original SocialCalc command string (audit trail)
    payload: dict  # Structured payload (type-specific fields)

    # Integrity
    content_hash: str = ""  # SHA-256 of (sheet_id + raw_command + peer_id)

    # Causal dependency (optional, for CRDT causal tracking)
    depends_on: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        raw = f"{self.sheet_id}:{self.raw_command}:{self.peer_id}:{self.op_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def hlc(self) -> tuple[int, int]:
        return (self.hlc_physical, self.hlc_logical)

    def to_bytes(self) -> bytes:
        """Serialise to MessagePack bytes for wire transmission."""
        d = {
            "i": self.op_id,
            "p": self.peer_id,
            "s": self.sheet_id,
            "tp": self.hlc_physical,
            "tl": self.hlc_logical,
            "t": self.op_type,
            "c": self.raw_command,
            "d": self.payload,
            "h": self.content_hash,
            "x": self.depends_on,
        }
        result = msgpack.packb(d, use_bin_type=True)
        assert result is not None
        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> Operation:
        """Deserialise from MessagePack bytes."""
        d = msgpack.unpackb(data, raw=False)
        return cls(
            op_id=d["i"],
            peer_id=d["p"],
            sheet_id=d["s"],
            hlc_physical=d["tp"],
            hlc_logical=d["tl"],
            op_type=d["t"],
            raw_command=d["c"],
            payload=d["d"],
            content_hash=d["h"],
            depends_on=d.get("x", []),
        )

    def verify_integrity(self) -> bool:
        return self.content_hash == self._compute_hash()


# ---------------------------------------------------------------------------
# Operation factory — parse SocialCalc command strings into Operations
# ---------------------------------------------------------------------------


class OperationFactory:
    """
    Parse EtherCalc/SocialCalc command strings into Operation objects.

    SocialCalc sends human-readable command strings over its channel.
    We parse these, classify them, extract structured payload, and wrap
    in a P2PCalc Operation with HLC timestamp and peer identity.

    This factory is the critical translation layer between EtherCalc's
    existing protocol and our p2p layer. No UI changes needed.
    """

    def __init__(self, peer_id: str):
        self._peer_id = peer_id

    def from_socialcalc_command(
        self,
        command: str,
        sheet_id: str,
        depends_on: list[str] | None = None,
    ) -> Operation:
        """Parse a raw SocialCalc command string into a typed Operation."""
        command = command.strip()
        hlc_p, hlc_l = _clock.now()

        op_type, payload = self._classify(command)

        return Operation(
            op_id=str(uuid.uuid4()),
            peer_id=self._peer_id,
            sheet_id=sheet_id,
            hlc_physical=hlc_p,
            hlc_logical=hlc_l,
            op_type=op_type,
            raw_command=command,
            payload=payload,
            depends_on=depends_on or [],
        )

    def _classify(self, command: str) -> tuple[int, dict]:
        """Classify a SocialCalc command and extract structured payload."""
        parts = command.split()
        if not parts:
            return OpType.SET_CELL_VALUE, {}

        verb = parts[0].lower()

        # "set A1 value 42"
        # "set A1 formula =SUM(A1:A5)"
        # "set A1 bgcolor #ff0000"
        # "set A1:B5 bgcolor #ff0000"
        if verb == "set" and len(parts) >= 4:
            cell_or_range = parts[1]
            attr = parts[2].lower()
            value = " ".join(parts[3:])

            if attr == "value":
                return OpType.SET_CELL_VALUE, {"cell": cell_or_range, "value": value}
            elif attr == "formula":
                return OpType.SET_CELL_FORMULA, {
                    "cell": cell_or_range,
                    "formula": value,
                }
            else:
                op = (
                    OpType.SET_RANGE_FORMAT
                    if ":" in cell_or_range
                    else OpType.SET_CELL_FORMAT
                )
                return op, {"cell": cell_or_range, "attr": attr, "value": value}

        # "erase A1"
        if verb == "erase" and len(parts) >= 2:
            return OpType.CLEAR_CELL, {"cell": parts[1]}

        # "insertrow 3 1"
        if verb == "insertrow" and len(parts) >= 2:
            return OpType.INSERT_ROW, {
                "row": int(parts[1]),
                "count": int(parts[2]) if len(parts) > 2 else 1,
            }

        # "deleterow 3 1"
        if verb == "deleterow" and len(parts) >= 2:
            return OpType.DELETE_ROW, {
                "row": int(parts[1]),
                "count": int(parts[2]) if len(parts) > 2 else 1,
            }

        # "insertcol C 1"
        if verb == "insertcol" and len(parts) >= 2:
            return OpType.INSERT_COL, {
                "col": parts[1],
                "count": int(parts[2]) if len(parts) > 2 else 1,
            }

        # "deletecol C 1"
        if verb == "deletecol" and len(parts) >= 2:
            return OpType.DELETE_COL, {
                "col": parts[1],
                "count": int(parts[2]) if len(parts) > 2 else 1,
            }

        # "sort A1:D10 A up B down"
        if verb == "sort":
            return OpType.SORT_SHEET, {"raw": command}

        # "movepaste A1:B5 C3 all"
        if verb in ("movepaste", "moveinsert"):
            return OpType.MOVE_RANGE, {"raw": command}

        # "copy A1:B5 C3 all" / "paste C3 all"
        if verb in ("copy", "paste"):
            return OpType.COPY_RANGE, {"raw": command}

        # Unknown — preserve as raw for forward-compatibility
        return OpType.SET_CELL_VALUE, {"raw": command}

    def make_snapshot_request(self, sheet_id: str) -> Operation:
        hlc_p, hlc_l = _clock.now()
        return Operation(
            op_id=str(uuid.uuid4()),
            peer_id=self._peer_id,
            sheet_id=sheet_id,
            hlc_physical=hlc_p,
            hlc_logical=hlc_l,
            op_type=OpType.SNAPSHOT_REQUEST,
            raw_command="",
            payload={},
        )

    def make_snapshot_chunk(
        self,
        sheet_id: str,
        chunk_index: int,
        total_chunks: int,
        data: bytes,
        op_log_from: int = 0,
    ) -> Operation:
        hlc_p, hlc_l = _clock.now()
        return Operation(
            op_id=str(uuid.uuid4()),
            peer_id=self._peer_id,
            sheet_id=sheet_id,
            hlc_physical=hlc_p,
            hlc_logical=hlc_l,
            op_type=OpType.SNAPSHOT_CHUNK,
            raw_command="",
            payload={
                "idx": chunk_index,
                "total": total_chunks,
                "data": data.hex(),  # bytes as hex string for msgpack compat
                "op_log_from": op_log_from,
            },
        )

    def make_heartbeat(self, sheet_id: str, cell_cursor: str = "") -> Operation:
        hlc_p, hlc_l = _clock.now()
        return Operation(
            op_id=str(uuid.uuid4()),
            peer_id=self._peer_id,
            sheet_id=sheet_id,
            hlc_physical=hlc_p,
            hlc_logical=hlc_l,
            op_type=OpType.HEARTBEAT,
            raw_command="",
            payload={"cursor": cell_cursor},
        )


# ---------------------------------------------------------------------------
# Receive-side: update HLC from incoming operation
# ---------------------------------------------------------------------------


def receive_operation(op: Operation) -> Operation:
    """
    Update local HLC from an incoming operation's timestamp.

    Must be called for every received operation to maintain
    causal consistency guarantees.
    """
    _clock.update(op.hlc_physical, op.hlc_logical)
    return op
