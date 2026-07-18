# p2pcalc/crdt.py — CRDT conflict resolution for P2PCalc
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# INNOVATION: We implement a two-phase CRDT approach:
#
# Phase 1 (cell values): Multi-Value Register (MVR)
#   Unlike naive Last-Write-Wins (LWW) which silently loses data,
#   MVR tracks ALL concurrent values for a cell. When concurrent
#   edits happen, both values are preserved and surfaced to the user
#   as a conflict marker (like Git merge conflicts, but for cells).
#   The user explicitly resolves — no silent data loss.
#
# Phase 2 (structural ops): Replicated Growable Array (RGA) for rows/cols
#   Row/column insertions and deletions are tracked as a CRDT sequence.
#   Concurrent insertions use peer_id as a tiebreaker for determinism.
#   Deletions use tombstones so concurrent edits to a deleted row can
#   still be applied without crashing.
#
# This is significantly more principled than the "last-write-wins using
# timestamps" approach most collaborative editors use, which breaks under
# network partition.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging

from .operation import HLC, Operation, OpType

logger = logging.getLogger("p2pcalc.crdt")

_clock = HLC()


# ---------------------------------------------------------------------------
# Cell state
# ---------------------------------------------------------------------------


class ConflictPolicy(Enum):
    LAST_WRITE_WINS = "lww"  # Phase 1 baseline — fast, simple
    MULTI_VALUE = "mvr"  # Phase 2 — safe, surfaced to user
    PEER_PRIORITY = "peer"  # Deterministic: lowest peer_id wins


@dataclass
class CellVersion:
    """A single versioned value for a cell."""

    value: str
    formula: str
    formats: dict  # attr -> value
    hlc: tuple[int, int]
    peer_id: str
    op_id: str


@dataclass
class CellState:
    """
    CRDT state for a single cell.

    In Phase 1 (LWW): only the winning version is kept.
    In Phase 2 (MVR): all concurrent versions are kept as candidates.
    A cell is in "conflict" when len(candidates) > 1.
    """

    coord: str  # e.g. "A1"
    candidates: list[CellVersion] = field(default_factory=list)
    resolved_value: str | None = None  # set by user during conflict resolution
    is_conflict: bool = False

    @property
    def current_value(self) -> str:
        if self.is_conflict and self.resolved_value is not None:
            return self.resolved_value
        if self.candidates:
            return self.candidates[0].value
        return ""

    @property
    def current_formula(self) -> str:
        if self.candidates:
            return self.candidates[0].formula
        return ""


# ---------------------------------------------------------------------------
# Multi-Value Register (cell-level CRDT)
# ---------------------------------------------------------------------------


class MultiValueRegister:
    """
    Cell-level CRDT using Multi-Value Register semantics.

    A write dominates another if it causally follows it (HLC comparison).
    Concurrent writes (neither dominates the other) produce a conflict.

    This is mathematically equivalent to a state-based CRDT G-Set of
    (value, version) pairs, merged by taking the union and pruning
    dominated versions.
    """

    def __init__(self, policy: ConflictPolicy = ConflictPolicy.MULTI_VALUE):
        self._policy = policy
        self._cells: dict[str, CellState] = {}

    def apply(self, op: Operation) -> CellState:
        """Apply a cell operation and return the resulting cell state."""
        coord = op.payload.get("cell", "")
        if not coord:
            return CellState(coord="")

        state = self._cells.get(coord, CellState(coord=coord))

        new_version = CellVersion(
            value=op.payload.get("value", ""),
            formula=op.payload.get("formula", ""),
            formats={op.payload.get("attr", ""): op.payload.get("value", "")}
            if op.op_type == OpType.SET_CELL_FORMAT
            else {},
            hlc=op.hlc,
            peer_id=op.peer_id,
            op_id=op.op_id,
        )

        if op.op_type == OpType.CLEAR_CELL:
            state.candidates = []
            state.is_conflict = False
            state.resolved_value = None
            self._cells[coord] = state
            return state

        if self._policy == ConflictPolicy.LAST_WRITE_WINS:
            state = self._apply_lww(state, new_version)
        elif self._policy == ConflictPolicy.MULTI_VALUE:
            state = self._apply_mvr(state, new_version)
        elif self._policy == ConflictPolicy.PEER_PRIORITY:
            state = self._apply_peer_priority(state, new_version)

        self._cells[coord] = state
        return state

    def _apply_lww(self, state: CellState, new_ver: CellVersion) -> CellState:
        """Last-Write-Wins: higher HLC always wins."""
        if not state.candidates:
            state.candidates = [new_ver]
        else:
            existing = state.candidates[0]
            cmp = _clock.compare(new_ver.hlc, existing.hlc)
            if cmp > 0:
                state.candidates = [new_ver]
            elif cmp == 0:
                # Tie: use peer_id as deterministic tiebreaker
                if new_ver.peer_id < existing.peer_id:
                    state.candidates = [new_ver]
        state.is_conflict = False
        return state

    def _apply_mvr(self, state: CellState, new_ver: CellVersion) -> CellState:
        """Multi-Value Register: preserve all concurrent versions."""
        survivors = []
        new_dominates_all = True

        for existing in state.candidates:
            cmp = _clock.compare(new_ver.hlc, existing.hlc)
            if cmp > 0:
                # new_ver causally dominates existing — prune existing
                pass
            elif cmp < 0:
                # existing causally dominates new_ver — new_ver is stale
                new_dominates_all = False
                survivors.append(existing)
            else:
                # Concurrent — keep both
                survivors.append(existing)

        if new_dominates_all or not state.candidates:
            survivors.append(new_ver)

        # Sort by peer_id for deterministic ordering
        survivors.sort(key=lambda v: (v.hlc[0], v.hlc[1], v.peer_id))
        state.candidates = survivors
        state.is_conflict = len(survivors) > 1
        if state.is_conflict:
            logger.info(
                "Conflict at %s: %d concurrent values from peers %s",
                state.coord,
                len(survivors),
                [v.peer_id[:8] for v in survivors],
            )
        return state

    def _apply_peer_priority(self, state: CellState, new_ver: CellVersion) -> CellState:
        """Deterministic: lexicographically smallest peer_id always wins."""
        if not state.candidates:
            state.candidates = [new_ver]
        else:
            existing = state.candidates[0]
            if new_ver.peer_id <= existing.peer_id:
                state.candidates = [new_ver]
        state.is_conflict = False
        return state

    def resolve_conflict(self, coord: str, chosen_op_id: str) -> CellState:
        """User explicitly picks one candidate as the resolved value."""
        state = self._cells.get(coord)
        if not state:
            return CellState(coord=coord)
        chosen = next((v for v in state.candidates if v.op_id == chosen_op_id), None)
        if chosen:
            state.resolved_value = chosen.value
            state.is_conflict = False
            state.candidates = [chosen]
        return state

    def get_conflicts(self) -> list[CellState]:
        return [s for s in self._cells.values() if s.is_conflict]

    def get_cell(self, coord: str) -> CellState | None:
        return self._cells.get(coord)

    def snapshot(self) -> dict[str, dict]:
        """Export current state as a serialisable dict."""
        result = {}
        for coord, state in self._cells.items():
            if state.candidates:
                best = state.candidates[0]
                result[coord] = {
                    "value": best.value,
                    "formula": best.formula,
                    "formats": best.formats,
                    "is_conflict": state.is_conflict,
                    "candidates": len(state.candidates),
                }
        return result


# ---------------------------------------------------------------------------
# RGA for structural operations (row/column insertions + deletions)
# ---------------------------------------------------------------------------


@dataclass
class RGANode:
    """A node in the Replicated Growable Array."""

    index: int  # Original row or column index at insertion time
    peer_id: str  # Peer that inserted this
    hlc: tuple[int, int]
    is_tombstone: bool = False  # Soft delete — never remove from array


class StructuralCRDT:
    """
    RGA-based CRDT for row/column insertions and deletions.

    Key innovation: we track the INTENT of structural operations
    (insert row 3) rather than their absolute effect (rows 4..N shift down).
    This allows concurrent structural ops to be merged without the ambiguity
    of "which row 3 did you mean?" problem that plagues OT-based systems.

    Concurrent insertions at the same position use peer_id as a tiebreaker
    to deterministically order them.
    """

    def __init__(self):
        self._rows: list[RGANode] = []
        self._cols: list[RGANode] = []

    def apply(self, op: Operation) -> None:
        if op.op_type == OpType.INSERT_ROW:
            self._insert(self._rows, op.payload["row"], op.peer_id, op.hlc)
        elif op.op_type == OpType.DELETE_ROW:
            self._delete(self._rows, op.payload["row"])
        elif op.op_type == OpType.INSERT_COL:
            self._insert(self._cols, op.payload.get("col_index", 0), op.peer_id, op.hlc)
        elif op.op_type == OpType.DELETE_COL:
            self._delete(self._cols, op.payload.get("col_index", 0))

    def _insert(
        self,
        seq: list[RGANode],
        idx: int,
        peer_id: str,
        hlc: tuple[int, int],
    ) -> None:
        node = RGANode(index=idx, peer_id=peer_id, hlc=hlc)
        # Find insertion position: after all nodes with same or earlier index,
        # with concurrent nodes ordered by peer_id (deterministic tiebreak)
        insert_pos = len(seq)
        for i, existing in enumerate(seq):
            if existing.index > idx:
                insert_pos = i
                break
            if existing.index == idx:
                # Concurrent — lower peer_id goes first (arbitrary but deterministic)
                if peer_id < existing.peer_id:
                    insert_pos = i
                    break
        seq.insert(insert_pos, node)

    def _delete(self, seq: list[RGANode], idx: int) -> None:
        for node in seq:
            if node.index == idx and not node.is_tombstone:
                node.is_tombstone = True
                return

    def visible_rows(self) -> list[int]:
        """Return the current visible row indices in order."""
        return [n.index for n in self._rows if not n.is_tombstone]

    def visible_cols(self) -> list[int]:
        return [n.index for n in self._cols if not n.is_tombstone]

    def snapshot(self) -> dict:
        return {
            "rows": [
                {"idx": n.index, "peer": n.peer_id, "deleted": n.is_tombstone}
                for n in self._rows
            ],
            "cols": [
                {"idx": n.index, "peer": n.peer_id, "deleted": n.is_tombstone}
                for n in self._cols
            ],
        }


# ---------------------------------------------------------------------------
# Unified sheet CRDT state
# ---------------------------------------------------------------------------


class SheetCRDT:
    """
    Complete CRDT state for a single spreadsheet sheet.

    Combines:
      - MultiValueRegister for all cell mutations
      - StructuralCRDT for row/column structure
      - Op-log for late-joiner state reconstruction
    """

    def __init__(
        self,
        sheet_id: str,
        policy: ConflictPolicy = ConflictPolicy.MULTI_VALUE,
    ):
        self.sheet_id = sheet_id
        self.cells = MultiValueRegister(policy=policy)
        self.structure = StructuralCRDT()
        self._op_log: list[Operation] = []
        self._seen_op_ids: set[str] = set()

    def apply(self, op: Operation) -> bool:
        """Apply an operation. Returns False if already seen (duplicate)."""
        if op.op_id in self._seen_op_ids:
            return False
        self._seen_op_ids.add(op.op_id)
        self._op_log.append(op)

        if op.op_type in (
            OpType.SET_CELL_VALUE,
            OpType.SET_CELL_FORMULA,
            OpType.SET_CELL_FORMAT,
            OpType.SET_RANGE_FORMAT,
            OpType.CLEAR_CELL,
        ):
            self.cells.apply(op)
        elif op.op_type in (
            OpType.INSERT_ROW,
            OpType.DELETE_ROW,
            OpType.INSERT_COL,
            OpType.DELETE_COL,
        ):
            self.structure.apply(op)

        return True

    def get_conflicts(self) -> list[CellState]:
        return self.cells.get_conflicts()

    def op_log_since(self, from_index: int) -> list[Operation]:
        return self._op_log[from_index:]

    def op_log_length(self) -> int:
        return len(self._op_log)

    def snapshot(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "cells": self.cells.snapshot(),
            "structure": self.structure.snapshot(),
            "op_count": len(self._op_log),
        }
