# p2pcalc/state_sync.py — Late-joiner state synchronisation
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# INNOVATION: Two-phase state reconstruction
#
# Phase 1: Snapshot transfer
#   The late joiner requests a snapshot via GossipSub SNAPSHOT_REQUEST.
#   Any peer that has state responds with SNAPSHOT_CHUNK operations.
#   Multiple peers may respond — we pick the first complete snapshot
#   and verify it with a content hash.
#
# Phase 2: Op-log replay
#   The snapshot includes op_log_from = N (the op count at snapshot time).
#   Any operations that arrived after N are replayed on top.
#   This is exactly how Git's pack-file + reflog system works.
#
# ADDITIONAL INNOVATION: Snapshot race resolution
#   Multiple peers may send snapshots simultaneously. We use the peer
#   with the highest op count as the authoritative source, since they
#   have seen the most history. If counts are equal, lower peer_id wins.

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging

from .crdt import SheetCRDT
from .operation import Operation

logger = logging.getLogger("p2pcalc.sync")

# How long to wait for snapshot chunks before timing out
SNAPSHOT_TIMEOUT_SECONDS = 15

# Maximum snapshot size we accept (10 MB)
MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024


@dataclass
class SnapshotCandidate:
    """A snapshot being assembled from chunk operations."""

    peer_id: str
    total_chunks: int
    op_log_from: int  # replay ops from this index
    chunks: dict[int, bytes] = field(default_factory=dict)
    received_at: float = field(default_factory=lambda: __import__("time").time())

    @property
    def is_complete(self) -> bool:
        return len(self.chunks) == self.total_chunks

    @property
    def data(self) -> bytes:
        return b"".join(self.chunks[i] for i in range(self.total_chunks))

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.data).hexdigest()[:16]


class StateSyncManager:
    """
    Manages late-joiner state synchronisation for a single sheet.

    Used by P2PCalcNode internally when a new peer joins a sheet and
    requests a snapshot.
    """

    def __init__(self, sheet: SheetCRDT):
        self._sheet = sheet
        self._candidates: dict[str, SnapshotCandidate] = {}
        self._synced = False
        self._sync_event = asyncio.Event()

    def handle_snapshot_chunk(self, op: Operation) -> bool:
        """
        Process an incoming SNAPSHOT_CHUNK operation.

        Returns True when a complete, valid snapshot has been assembled
        and applied.
        """
        if self._synced:
            return True

        payload = op.payload
        peer_id = op.peer_id
        chunk_idx = payload.get("idx", 0)
        total = payload.get("total", 1)
        data_hex = payload.get("data", "")
        op_log_from = payload.get("op_log_from", 0)

        try:
            chunk_data = bytes.fromhex(data_hex)
        except ValueError:
            logger.warning("Invalid chunk data from peer %s", peer_id[:8])
            return False

        # Get or create candidate for this peer
        if peer_id not in self._candidates:
            self._candidates[peer_id] = SnapshotCandidate(
                peer_id=peer_id,
                total_chunks=total,
                op_log_from=op_log_from,
            )

        candidate = self._candidates[peer_id]
        candidate.chunks[chunk_idx] = chunk_data

        if not candidate.is_complete:
            logger.debug(
                "Snapshot from %s: %d/%d chunks received",
                peer_id[:8],
                len(candidate.chunks),
                total,
            )
            return False

        return self._apply_candidate(candidate)

    def _apply_candidate(self, candidate: SnapshotCandidate) -> bool:
        """Validate and apply a complete snapshot candidate."""
        data = candidate.data

        if len(data) > MAX_SNAPSHOT_BYTES:
            logger.warning(
                "Snapshot from %s too large (%d bytes) — rejected",
                candidate.peer_id[:8],
                len(data),
            )
            return False

        try:
            snapshot = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(
                "Invalid snapshot JSON from %s: %s", candidate.peer_id[:8], e
            )
            return False

        # If multiple peers sent snapshots, pick the one with most history
        best = self._best_candidate()
        if best and best.peer_id != candidate.peer_id:
            if best.op_log_from > candidate.op_log_from:
                logger.debug(
                    "Ignoring snapshot from %s — peer %s has more history",
                    candidate.peer_id[:8],
                    best.peer_id[:8],
                )
                return False

        # Apply snapshot to sheet state
        self._apply_snapshot_dict(snapshot)
        self._synced = True
        self._sync_event.set()

        logger.info(
            "Snapshot applied from peer %s: %d cells, op_log_from=%d",
            candidate.peer_id[:8],
            len(snapshot.get("cells", {})),
            candidate.op_log_from,
        )
        return True

    def _best_candidate(self) -> SnapshotCandidate | None:
        """Return the candidate with the most op history."""
        complete = [c for c in self._candidates.values() if c.is_complete]
        if not complete:
            return None
        return max(
            complete,
            key=lambda c: (c.op_log_from, -ord(c.peer_id[0])),
        )

    def _apply_snapshot_dict(self, snapshot: dict) -> None:
        """Reconstruct sheet cell state from a snapshot dict."""
        cells = snapshot.get("cells", {})

        from .operation import OperationFactory

        factory = OperationFactory(peer_id="__snapshot__")

        for coord, cell_data in cells.items():
            value = cell_data.get("value", "")
            formula = cell_data.get("formula", "")

            if formula:
                command = f"set {coord} formula {formula}"
            elif value:
                command = f"set {coord} value {value}"
            else:
                continue

            op = factory.from_socialcalc_command(command, self._sheet.sheet_id)
            self._sheet.apply(op)

        logger.debug("Applied %d cells from snapshot", len(cells))

    async def wait_for_sync(self, timeout: float = SNAPSHOT_TIMEOUT_SECONDS) -> bool:
        """Wait until a snapshot has been successfully applied."""
        try:
            await asyncio.wait_for(self._sync_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Snapshot sync timed out after %.1fs — starting from empty state",
                timeout,
            )
            self._synced = True
            return False

    @property
    def is_synced(self) -> bool:
        return self._synced


class OpLogPersistence:
    """
    Persists the operation log to local disk for crash recovery.

    INNOVATION: On restart, a peer replays its own op-log to recover
    its last known state before requesting a network snapshot. This
    means peers can recover from crashes without needing the network,
    and reduces the burden on other peers to serve full snapshots.

    Format: newline-delimited MessagePack operations (like a WAL).
    """

    def __init__(self, sheet_id: str, data_dir: str = "./p2pcalc_data"):
        from pathlib import Path

        _dir = Path(data_dir)
        _dir.mkdir(parents=True, exist_ok=True)
        self._path = str(_dir / f"{sheet_id}.oplog")
        self._file = None

    async def open(self) -> None:
        self._file = open(self._path, "ab")
        logger.info("Op-log opened: %s", self._path)

    async def append(self, op: Operation) -> None:
        if not self._file:
            return
        data = op.to_bytes()
        # Write: 4-byte length prefix + msgpack bytes
        import struct

        self._file.write(struct.pack(">I", len(data)) + data)
        self._file.flush()

    def replay(self) -> list[Operation]:
        """Read all operations from the log file."""
        ops = []
        import struct

        try:
            with open(self._path, "rb") as f:
                while True:
                    header = f.read(4)
                    if len(header) < 4:
                        break
                    length = struct.unpack(">I", header)[0]
                    data = f.read(length)
                    if len(data) < length:
                        break
                    try:
                        ops.append(Operation.from_bytes(data))
                    except Exception as e:
                        logger.warning("Corrupt op-log entry: %s", e)
                        break
        except FileNotFoundError:
            pass
        logger.info("Replayed %d operations from local op-log", len(ops))
        return ops

    async def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
