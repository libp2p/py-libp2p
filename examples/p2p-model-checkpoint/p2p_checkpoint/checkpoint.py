"""
checkpoint.py
-------------

Turns a trained :class:`~p2p_checkpoint.model.LocalModel` into a
self-describing, content-hashable bundle that can be handed to IPFS.

A checkpoint on disk looks like::

    checkpoint-<round>/
        model.pkl        # joblib-serialized LocalModel payload
        metadata.json     # CheckpointMetadata, see below

which then gets archived into a single ``checkpoint-<round>.tar.gz`` --
*that* archive is what actually gets uploaded to IPFS and referenced by CID.
Shipping one file instead of a directory keeps the IPFS side of the code
trivial (a single ``add`` / ``cat`` per checkpoint).

Metadata answers the question a bare CID cannot: which model, which round,
whose model, and when. See README > Checkpoint Metadata.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from p2p_checkpoint.model import LocalModel

METADATA_FILENAME = "metadata.json"
MODEL_FILENAME = "model.pkl"


@dataclass
class CheckpointMetadata:
    """Everything a peer needs to know about a checkpoint without loading it."""

    round: int
    peer_id: str
    dataset: str
    model_type: str
    created_at: str
    model_hash: str
    accuracy: float | None = None
    n_samples: int | None = None
    parent_hash: str | None = None

    @classmethod
    def new(
        cls,
        *,
        round: int,
        peer_id: str,
        dataset: str,
        model_type: str,
        model_hash: str,
        accuracy: float | None = None,
        n_samples: int | None = None,
        parent_hash: str | None = None,
    ) -> "CheckpointMetadata":
        return cls(
            round=round,
            peer_id=peer_id,
            dataset=dataset,
            model_type=model_type,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            model_hash=model_hash,
            accuracy=accuracy,
            n_samples=n_samples,
            parent_hash=parent_hash,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CheckpointMetadata":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def compute_sha256(path: str | Path) -> str:
    """Stream-hash a file. Used both for model integrity and CID-adjacent
    bookkeeping (see README > Model Integrity for why we keep both)."""
    path = Path(path)
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def create_checkpoint_bundle(
    model: LocalModel,
    *,
    round: int,
    peer_id: str,
    dataset: str,
    output_dir: str | Path,
    accuracy: float | None = None,
    n_samples: int | None = None,
    parent_hash: str | None = None,
) -> tuple[Path, CheckpointMetadata]:
    """
    Save ``model`` + metadata into ``output_dir/checkpoint-<round>.tar.gz``.

    Returns the archive path and the metadata object that was embedded in it
    (metadata.model_hash is the hash of the *model file*, computed before
    archiving, so it survives independent of however IPFS ends up
    content-addressing the outer archive).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        model_path = tmp_path / MODEL_FILENAME
        model.save(model_path)
        model_hash = compute_sha256(model_path)

        metadata = CheckpointMetadata.new(
            round=round,
            peer_id=peer_id,
            dataset=dataset,
            model_type=model.MODEL_TYPE,
            model_hash=model_hash,
            accuracy=accuracy,
            n_samples=n_samples,
            parent_hash=parent_hash,
        )
        metadata_path = tmp_path / METADATA_FILENAME
        metadata_path.write_text(json.dumps(metadata.to_dict(), indent=2))

        archive_path = output_dir / f"checkpoint-{round:03d}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(model_path, arcname=MODEL_FILENAME)
            tar.add(metadata_path, arcname=METADATA_FILENAME)

    return archive_path, metadata


def extract_checkpoint_bundle(
    archive_path: str | Path, dest_dir: str | Path
) -> tuple[LocalModel, CheckpointMetadata]:
    """Inverse of :func:`create_checkpoint_bundle`. Loads the model and
    metadata out of a ``checkpoint-*.tar.gz`` archive (e.g. one just fetched
    from IPFS)."""
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        _safe_extractall(tar, dest_dir)

    model_path = dest_dir / MODEL_FILENAME
    metadata_path = dest_dir / METADATA_FILENAME
    if not model_path.exists() or not metadata_path.exists():
        raise ValueError(
            f"Checkpoint archive {archive_path} is missing "
            f"{MODEL_FILENAME} or {METADATA_FILENAME}"
        )

    metadata = CheckpointMetadata.from_dict(json.loads(metadata_path.read_text()))

    # Integrity check: the model file we just extracted must match the hash
    # recorded in metadata at creation time. This catches truncated
    # downloads or a mismatched/forged archive even though IPFS itself
    # already guarantees the archive's bytes match its CID.
    actual_hash = compute_sha256(model_path)
    if actual_hash != metadata.model_hash:
        raise ValueError(
            "Checkpoint integrity check failed: "
            f"expected {metadata.model_hash}, got {actual_hash}"
        )

    model = LocalModel.load(model_path)
    return model, metadata


def _safe_extractall(tar: tarfile.TarFile, dest_dir: Path) -> None:
    """Extract a tarfile while refusing path traversal / absolute members.

    Checkpoints may originate from an untrusted peer over IPFS, so we don't
    trust archive member names by default.
    """
    dest_dir = dest_dir.resolve()
    for member in tar.getmembers():
        member_path = (dest_dir / member.name).resolve()
        if not str(member_path).startswith(str(dest_dir)):
            raise ValueError(f"Unsafe path in checkpoint archive: {member.name}")
    # `filter="data"` opts into Python 3.12+'s hardened extraction (rejects
    # absolute paths, symlinks escaping dest_dir, device files, etc.) and
    # silences the 3.14 deprecation warning. Members are already validated
    # above for interpreters where the `filter` kwarg isn't available.
    try:
        tar.extractall(dest_dir, filter="data")
    except TypeError:  # pragma: no cover - Python < 3.12
        tar.extractall(dest_dir)


def latest_checkpoint_path(checkpoints_dir: str | Path) -> Path | None:
    """Convenience for the CLI: locate the highest-round archive on disk."""
    checkpoints_dir = Path(checkpoints_dir)
    if not checkpoints_dir.exists():
        return None
    archives = sorted(checkpoints_dir.glob("checkpoint-*.tar.gz"))
    return archives[-1] if archives else None


def copy_as_latest(archive_path: str | Path, checkpoints_dir: str | Path) -> Path:
    """Maintain a stable ``latest.tar.gz`` pointer alongside the versioned
    archives, mirroring the ``checkpoints/latest.pkl`` convenience described
    in the design doc."""
    checkpoints_dir = Path(checkpoints_dir)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    latest_path = checkpoints_dir / "latest.tar.gz"
    shutil.copyfile(archive_path, latest_path)
    return latest_path
