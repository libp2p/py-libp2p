"""
peer.py
-------

Ties everything together into a single ``Peer``: local training data, the
model, local checkpoint storage + database, an IPFS client, and the libp2p
host/protocol.

A ``Peer`` is deliberately the *only* class in this codebase that imports
from every other module -- ``model``, ``checkpoint``, ``ipfs_utils``,
``messages``, ``protocol``, and ``db`` are all otherwise independent of one
another and independently testable. ``peer.py`` is where they get wired
together into the actual MVP flow described in the README:

    train -> checkpoint -> upload to IPFS -> announce CID over libp2p
    receive CID -> fetch from IPFS -> verify -> load -> continue training
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID as PeerID

from p2p_checkpoint.checkpoint import (
    copy_as_latest,
    create_checkpoint_bundle,
    extract_checkpoint_bundle,
)
from p2p_checkpoint.db import CheckpointDB
from p2p_checkpoint.ipfs_utils import IPFSClient, SupportsIPFS
from p2p_checkpoint.messages import (
    CheckpointAnnouncement,
    CheckpointAvailable,
    CheckpointRequest,
    SyncRequest,
    SyncResponse,
)
from p2p_checkpoint.model import LocalModel
from p2p_checkpoint.protocol import CheckpointProtocol

logger = logging.getLogger("p2p_checkpoint.peer")


class Peer:
    """
    Parameters
    ----------
    name:
        Human-readable label (used for the data directory and log lines).
        Not part of the libp2p identity -- the peer ID is derived from the
        keypair, see ``seed``.
    data_dir:
        Root directory for this peer's state: ``<data_dir>/checkpoints/``,
        ``<data_dir>/db.sqlite3``, ``<data_dir>/model_workspace/``.
    ipfs:
        Anything satisfying :class:`~p2p_checkpoint.ipfs_utils.SupportsIPFS`.
        Defaults to a real Kubo daemon client; tests substitute an in-memory
        fake so the suite doesn't require a running IPFS daemon.
    seed:
        Optional 32-byte seed for reproducible peer IDs (handy for demos and
        tests). If omitted, a random identity is generated each run.
    """

    def __init__(
        self,
        name: str,
        data_dir: str | Path,
        dataset: str = "iris",
        ipfs: SupportsIPFS | None = None,
        seed: bytes | None = None,
    ) -> None:
        self.name = name
        self.dataset = dataset
        self.data_dir = Path(data_dir)
        self.checkpoints_dir = self.data_dir / "checkpoints"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        self.ipfs: SupportsIPFS = ipfs or IPFSClient()
        self.db = CheckpointDB(self.data_dir / "db.sqlite3")

        secret = seed or secrets.token_bytes(32)
        self.key_pair = create_new_key_pair(secret)
        self.host = new_host(key_pair=self.key_pair)
        self.protocol = CheckpointProtocol(self.host)
        self.protocol.bind(self)  # Peer itself implements CheckpointProvider

        self.model: LocalModel | None = None

    # ------------------------------------------------------------------ #
    # Identity helpers
    # ------------------------------------------------------------------ #
    @property
    def peer_id(self) -> str:
        return self.host.get_id().to_string()

    def listen_addrs_with_peer_id(self) -> list[str]:
        """Full dialable multiaddrs for this peer.

        ``host.get_addrs()`` already includes the trailing ``/p2p/<id>``
        component on current py-libp2p, so this is mostly a thin,
        future-proof wrapper: if that ever changes upstream, only this one
        place needs to catch up.
        """
        pid = self.peer_id
        addrs = []
        for addr in self.host.get_addrs():
            addr_str = str(addr)
            addrs.append(addr_str if addr_str.endswith(f"/p2p/{pid}") else f"{addr_str}/p2p/{pid}")
        return addrs

    # ------------------------------------------------------------------ #
    # Training / checkpointing (local, no networking)
    # ------------------------------------------------------------------ #
    def train_round(self, X, y, feature_names=None, class_names=None, eval_data=None):
        """Train (or re-train) the local model and persist a new checkpoint
        bundle to disk. Does *not* touch IPFS or the network -- see
        :meth:`publish_checkpoint` for that. Returns the checkpoint archive
        path and its metadata."""
        model = LocalModel()
        model.train(X, y, feature_names=feature_names, class_names=class_names)
        self.model = model

        accuracy = None
        if eval_data is not None:
            eval_X, eval_y = eval_data
            accuracy = model.evaluate(eval_X, eval_y)

        next_round = self.db.latest_round() + 1
        archive_path, metadata = create_checkpoint_bundle(
            model,
            round=next_round,
            peer_id=self.peer_id,
            dataset=self.dataset,
            output_dir=self.checkpoints_dir,
            accuracy=accuracy,
            n_samples=len(X),
        )
        copy_as_latest(archive_path, self.checkpoints_dir)
        return archive_path, metadata

    def publish_checkpoint(self, archive_path: Path, metadata) -> str:
        """Upload a checkpoint archive to IPFS and record it locally.
        Returns the resulting CID."""
        cid = self.ipfs.upload_file(archive_path)
        checkpoint_id = f"checkpoint-{metadata.round:03d}"
        self.db.upsert(
            checkpoint_id=checkpoint_id,
            round=metadata.round,
            cid=cid,
            peer_id=metadata.peer_id,
            model_hash=metadata.model_hash,
            created_at=metadata.created_at,
            local_path=str(archive_path),
            status="verified",
            origin="local",
        )
        logger.info("Published %s -> CID %s", checkpoint_id, cid)
        return cid

    def train_and_publish(self, X, y, **kwargs) -> tuple[str, int]:
        """Convenience wrapper: train, checkpoint, upload. Returns
        ``(cid, round)``."""
        archive_path, metadata = self.train_round(X, y, **kwargs)
        cid = self.publish_checkpoint(archive_path, metadata)
        return cid, metadata.round

    # ------------------------------------------------------------------ #
    # CheckpointProvider implementation (inbound protocol handlers)
    # ------------------------------------------------------------------ #
    def handle_sync_request(self, msg: SyncRequest, sender_peer_id: str) -> SyncResponse:
        record = self.db.latest()
        if record is None:
            return SyncResponse(has_checkpoint=False)
        return SyncResponse(
            has_checkpoint=True,
            latest_round=record.round,
            cid=record.cid,
            model_hash=record.model_hash,
            peer_id=record.peer_id,
        )

    def handle_checkpoint_request(
        self, msg: CheckpointRequest, sender_peer_id: str
    ) -> CheckpointAvailable:
        record = self.db.get(msg.checkpoint_id)
        if record is None:
            return CheckpointAvailable(checkpoint_id=msg.checkpoint_id, found=False)
        return CheckpointAvailable(
            checkpoint_id=msg.checkpoint_id, found=True, cid=record.cid
        )

    def handle_announcement(
        self, msg: CheckpointAnnouncement, sender_peer_id: str
    ) -> CheckpointAvailable:
        """A peer is telling us, unprompted, about a new checkpoint. We
        just acknowledge it here -- picking it up is a deliberate decision
        made by :mod:`sync`, not an automatic reaction to the announcement,
        per README > Never Automatically Downgrade."""
        logger.info(
            "Received announcement of %s (round %d) from %s",
            msg.checkpoint_id,
            msg.round,
            sender_peer_id,
        )
        known = self.db.get(msg.checkpoint_id) is not None
        return CheckpointAvailable(
            checkpoint_id=msg.checkpoint_id, found=known, cid=msg.cid if known else None
        )

    # ------------------------------------------------------------------ #
    # Outbound protocol calls (dialer side) -- thin pass-throughs
    # ------------------------------------------------------------------ #
    async def request_sync(self, remote_peer_id: str | PeerID) -> SyncResponse:
        pid = remote_peer_id if isinstance(remote_peer_id, PeerID) else PeerID.from_base58(remote_peer_id)
        return await self.protocol.send_sync_request(pid, self.db.latest_round())

    async def announce_latest(self, remote_peer_id: str | PeerID) -> CheckpointAvailable | None:
        record = self.db.latest()
        if record is None:
            return None
        pid = remote_peer_id if isinstance(remote_peer_id, PeerID) else PeerID.from_base58(remote_peer_id)
        announcement = CheckpointAnnouncement(
            checkpoint_id=f"checkpoint-{record.round:03d}",
            round=record.round,
            cid=record.cid,
            sender=self.peer_id,
            model_hash=record.model_hash,
        )
        return await self.protocol.send_announcement(pid, announcement)

    # ------------------------------------------------------------------ #
    # Applying a checkpoint fetched from IPFS (used by sync.py)
    # ------------------------------------------------------------------ #
    def adopt_checkpoint(self, archive_path: Path, cid: str, from_peer_id: str) -> LocalModel:
        """Extract + verify a downloaded archive, load it as the local
        model, and record it in the local DB (origin='remote')."""
        model, metadata = extract_checkpoint_bundle(
            archive_path, self.data_dir / "model_workspace"
        )
        self.model = model
        checkpoint_id = f"checkpoint-{metadata.round:03d}"
        self.db.upsert(
            checkpoint_id=checkpoint_id,
            round=metadata.round,
            cid=cid,
            peer_id=from_peer_id,
            model_hash=metadata.model_hash,
            created_at=metadata.created_at,
            local_path=str(archive_path),
            status="verified",
            origin="remote",
        )
        return model

    def close(self) -> None:
        self.db.close()
