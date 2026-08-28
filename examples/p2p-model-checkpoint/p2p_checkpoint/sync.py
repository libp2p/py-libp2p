"""
sync.py
-------

The "offline peer recovery" logic (README > The Most Important Feature,
> Synchronization Protocol, > Never Automatically Downgrade).

Deliberately pull-based: a peer decides *for itself* when to sync, by
asking a connected peer "what's your latest round?" and comparing that
against its own. This sidesteps the need for a persistent broadcast/queue
of missed announcements -- if you were offline, you simply ask on
reconnect, and the answer always comes from durable IPFS storage rather
than depending on the announcer still being around.

The "hybrid" behavior from README > Hybrid Synchronization falls out
naturally: the *coordination* (who has what) always happens directly over
libp2p when two peers are connected; the *payload* always comes from IPFS
either way. There's no separate direct-transfer code path to fall back
away from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from p2p_checkpoint.db import CheckpointRecord
from p2p_checkpoint.messages import SyncResponse
from p2p_checkpoint.peer import Peer

logger = logging.getLogger("p2p_checkpoint.sync")


class SyncError(RuntimeError):
    """Raised when a sync attempt fails outright (peer unreachable, IPFS
    unavailable, integrity check failed, etc.)."""


@dataclass
class SyncOutcome:
    """What happened as a result of a :func:`sync_with_peer` call."""

    action: str  # "up_to_date" | "updated" | "remote_behind" | "remote_empty"
    local_round_before: int
    local_round_after: int
    remote_round: int | None = None
    cid: str | None = None


async def sync_with_peer(peer: Peer, remote_peer_id: str) -> SyncOutcome:
    """
    Ask ``remote_peer_id`` (already connected) for its latest checkpoint,
    and adopt it if -- and only if -- it's strictly newer than what we
    already have.

    This is the whole "offline peer catches up" story end to end:
    round-comparison happens over libp2p, the checkpoint bytes always come
    from IPFS.
    """
    local_round_before = peer.db.latest_round()

    try:
        response: SyncResponse = await peer.request_sync(remote_peer_id)
    except Exception as exc:  # noqa: BLE001
        raise SyncError(f"Sync request to {remote_peer_id} failed: {exc}") from exc

    if not response.has_checkpoint:
        return SyncOutcome(
            action="remote_empty",
            local_round_before=local_round_before,
            local_round_after=local_round_before,
        )

    if response.latest_round <= local_round_before:
        # README > Never Automatically Downgrade: a remote at or behind our
        # own round is simply left alone, whether it's equal (nothing to do)
        # or genuinely behind (that peer should be asking *us*).
        action = "up_to_date" if response.latest_round == local_round_before else "remote_behind"
        return SyncOutcome(
            action=action,
            local_round_before=local_round_before,
            local_round_after=local_round_before,
            remote_round=response.latest_round,
            cid=response.cid,
        )

    # Remote is strictly ahead -- fetch, verify, and adopt.
    if response.cid is None:
        raise SyncError("Remote reported a newer round but no CID")

    archive_path = _download_path(peer, response)
    try:
        peer.ipfs.download_file(response.cid, archive_path)
    except Exception as exc:  # noqa: BLE001
        raise SyncError(f"Failed to fetch checkpoint {response.cid} from IPFS: {exc}") from exc

    try:
        peer.adopt_checkpoint(archive_path, response.cid, response.peer_id or remote_peer_id)
    except Exception as exc:  # noqa: BLE001
        raise SyncError(f"Downloaded checkpoint failed verification: {exc}") from exc

    local_round_after = peer.db.latest_round()
    logger.info(
        "%s synced from round %d -> %d (cid=%s)",
        peer.name,
        local_round_before,
        local_round_after,
        response.cid,
    )
    return SyncOutcome(
        action="updated",
        local_round_before=local_round_before,
        local_round_after=local_round_after,
        remote_round=response.latest_round,
        cid=response.cid,
    )


def _download_path(peer: Peer, response: SyncResponse) -> Path:
    fname = f"checkpoint-{response.latest_round:03d}-{response.cid[:12]}.tar.gz"
    return peer.data_dir / "downloads" / fname


def describe(record: CheckpointRecord | None) -> str:
    """Human-readable one-liner for CLI ``status`` output."""
    if record is None:
        return "no checkpoint yet"
    return (
        f"round {record.round} | cid={record.cid} | "
        f"origin={record.origin} | peer={record.peer_id[:16]}..."
    )
