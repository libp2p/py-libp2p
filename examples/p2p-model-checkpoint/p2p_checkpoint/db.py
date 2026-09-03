"""
db.py
-----

A tiny SQLite-backed ledger of every checkpoint a peer has produced or
pulled in from the network. This is the "did I already see this?" /
"what's my latest round?" bookkeeping layer referenced in
README > Local Checkpoint Database.

JSON would have been adequate for the MVP too (and the design doc says so);
SQLite was chosen here because ``status`` transitions (pending -> verified
-> failed) and "give me the max round" queries are both a little cleaner
with real indices and a WHERE clause than with hand-rolled JSON scanning.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    round         INTEGER NOT NULL,
    cid           TEXT NOT NULL,
    peer_id       TEXT NOT NULL,
    model_hash    TEXT,
    created_at    TEXT NOT NULL,
    local_path    TEXT,
    status        TEXT NOT NULL DEFAULT 'verified',
    origin        TEXT NOT NULL DEFAULT 'local'
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_round ON checkpoints(round);
"""


@dataclass
class CheckpointRecord:
    checkpoint_id: str
    round: int
    cid: str
    peer_id: str
    model_hash: str | None
    created_at: str
    local_path: str | None
    status: str
    origin: str

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "CheckpointRecord":
        return cls(**{k: row[k] for k in row.keys()})


class CheckpointDB:
    """Wraps a single SQLite file. Safe to open multiple times (e.g. once
    per CLI invocation) since each round is only ever inserted once thanks
    to ``checkpoint_id`` being the primary key."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CheckpointDB":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def upsert(
        self,
        *,
        checkpoint_id: str,
        round: int,
        cid: str,
        peer_id: str,
        created_at: str,
        model_hash: str | None = None,
        local_path: str | None = None,
        status: str = "verified",
        origin: str = "local",
    ) -> CheckpointRecord:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO checkpoints
                    (checkpoint_id, round, cid, peer_id, model_hash,
                     created_at, local_path, status, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    cid=excluded.cid,
                    model_hash=excluded.model_hash,
                    local_path=excluded.local_path,
                    status=excluded.status,
                    origin=excluded.origin
                """,
                (
                    checkpoint_id,
                    round,
                    cid,
                    peer_id,
                    model_hash,
                    created_at,
                    local_path,
                    status,
                    origin,
                ),
            )
        return self.get(checkpoint_id)  # type: ignore[return-value]

    def get(self, checkpoint_id: str) -> CheckpointRecord | None:
        with closing(
            self._conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            )
        ) as cur:
            row = cur.fetchone()
        return CheckpointRecord._from_row(row) if row else None

    def latest(self) -> CheckpointRecord | None:
        with closing(
            self._conn.execute(
                "SELECT * FROM checkpoints ORDER BY round DESC LIMIT 1"
            )
        ) as cur:
            row = cur.fetchone()
        return CheckpointRecord._from_row(row) if row else None

    def latest_round(self) -> int:
        record = self.latest()
        return record.round if record else 0

    def list_all(self) -> list[CheckpointRecord]:
        with closing(
            self._conn.execute("SELECT * FROM checkpoints ORDER BY round ASC")
        ) as cur:
            rows = cur.fetchall()
        return [CheckpointRecord._from_row(r) for r in rows]

    def by_round(self, round: int) -> CheckpointRecord | None:
        with closing(
            self._conn.execute(
                "SELECT * FROM checkpoints WHERE round = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (round,),
            )
        ) as cur:
            row = cur.fetchone()
        return CheckpointRecord._from_row(row) if row else None
