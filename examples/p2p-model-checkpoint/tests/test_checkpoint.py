"""Unit tests for p2p_checkpoint.checkpoint (bundling, metadata, integrity)."""

from __future__ import annotations

import json
import tarfile

import pytest

from examples.iris_data import load_partition
from p2p_checkpoint.checkpoint import (
    METADATA_FILENAME,
    MODEL_FILENAME,
    CheckpointMetadata,
    compute_sha256,
    copy_as_latest,
    create_checkpoint_bundle,
    extract_checkpoint_bundle,
    latest_checkpoint_path,
)
from p2p_checkpoint.model import LocalModel


@pytest.fixture()
def trained_model():
    X_train, y_train, *_ = load_partition("peer-a")
    model = LocalModel()
    model.train(X_train, y_train)
    return model


def test_checkpoint_created(tmp_path, trained_model):
    archive_path, metadata = create_checkpoint_bundle(
        trained_model,
        round=1,
        peer_id="12D3fakepeer",
        dataset="iris",
        output_dir=tmp_path,
    )
    assert archive_path.exists()
    assert archive_path.name == "checkpoint-001.tar.gz"
    assert isinstance(metadata, CheckpointMetadata)


def test_checkpoint_bundle_contains_model_and_metadata(tmp_path, trained_model):
    archive_path, _ = create_checkpoint_bundle(
        trained_model, round=2, peer_id="12D3x", dataset="iris", output_dir=tmp_path
    )
    with tarfile.open(archive_path, "r:gz") as tar:
        names = set(tar.getnames())
    assert MODEL_FILENAME in names
    assert METADATA_FILENAME in names


def test_metadata_stored_matches_round_trip(tmp_path, trained_model):
    archive_path, metadata = create_checkpoint_bundle(
        trained_model,
        round=3,
        peer_id="12D3y",
        dataset="iris",
        output_dir=tmp_path,
        accuracy=0.95,
        n_samples=84,
    )
    with tarfile.open(archive_path, "r:gz") as tar:
        raw = json.loads(tar.extractfile(METADATA_FILENAME).read())
    assert raw["round"] == 3
    assert raw["peer_id"] == "12D3y"
    assert raw["accuracy"] == 0.95
    assert raw["n_samples"] == 84
    assert raw["model_hash"] == metadata.model_hash


def test_checkpoint_restored(tmp_path, trained_model):
    X_train, y_train, X_test, _, *_ = load_partition("peer-a")
    archive_path, metadata = create_checkpoint_bundle(
        trained_model, round=1, peer_id="12D3z", dataset="iris", output_dir=tmp_path
    )
    model2, metadata2 = extract_checkpoint_bundle(archive_path, tmp_path / "extracted")
    assert metadata2.round == metadata.round
    assert metadata2.model_hash == metadata.model_hash
    assert model2.is_fitted
    assert (model2.predict(X_test) == trained_model.predict(X_test)).all()


def test_extract_rejects_tampered_model_file(tmp_path, trained_model):
    """If the model file inside the archive doesn't match the hash recorded
    in metadata (e.g. corrupted in transit), extraction must fail loudly
    rather than silently loading a bad model."""
    archive_path, _ = create_checkpoint_bundle(
        trained_model, round=1, peer_id="12D3z", dataset="iris", output_dir=tmp_path
    )

    # Rebuild the archive with a corrupted model file but the original metadata.
    extract_dir = tmp_path / "tmp_extract"
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(extract_dir, filter="data")
    (extract_dir / MODEL_FILENAME).write_bytes(b"not a real model")

    tampered_path = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered_path, "w:gz") as tar:
        tar.add(extract_dir / MODEL_FILENAME, arcname=MODEL_FILENAME)
        tar.add(extract_dir / METADATA_FILENAME, arcname=METADATA_FILENAME)

    with pytest.raises(ValueError, match="integrity check failed"):
        extract_checkpoint_bundle(tampered_path, tmp_path / "extracted_tampered")


def test_compute_sha256_is_deterministic(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    h1 = compute_sha256(f)
    h2 = compute_sha256(f)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_latest_checkpoint_path_and_copy_as_latest(tmp_path, trained_model):
    assert latest_checkpoint_path(tmp_path) is None
    archive1, _ = create_checkpoint_bundle(
        trained_model, round=1, peer_id="p", dataset="iris", output_dir=tmp_path
    )
    archive2, _ = create_checkpoint_bundle(
        trained_model, round=2, peer_id="p", dataset="iris", output_dir=tmp_path
    )
    assert latest_checkpoint_path(tmp_path) == archive2

    latest = copy_as_latest(archive2, tmp_path)
    assert latest.name == "latest.tar.gz"
    assert latest.read_bytes() == archive2.read_bytes()


def test_metadata_from_dict_ignores_unknown_fields():
    meta = CheckpointMetadata.from_dict(
        {
            "round": 1,
            "peer_id": "p",
            "dataset": "iris",
            "model_type": "logistic_regression",
            "created_at": "2026-01-01T00:00:00+00:00",
            "model_hash": "sha256:abc",
            "some_future_field": "ignored",
        }
    )
    assert meta.round == 1
    assert meta.model_hash == "sha256:abc"
