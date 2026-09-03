"""
model.py
--------

The ML side of the project is deliberately boring: a single
``LogisticRegression`` classifier trained on (a shard of) the Iris dataset.

The point of this project is not the model -- it's proving that a checkpoint
of *some* model can be trained, persisted, shipped over IPFS, announced over
libp2p, and picked back up by another peer. Keeping the model trivial keeps
that story clean.

``LocalModel`` wraps scikit-learn so the rest of the codebase (checkpoint.py,
peer.py, sync.py) never has to import sklearn directly or know which
algorithm is in use.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression


@dataclass
class TrainResult:
    """Summary of a single local training run."""

    n_samples: int
    accuracy: float | None
    classes: list[str] = field(default_factory=list)


class LocalModel:
    """
    A thin, checkpoint-friendly wrapper around ``sklearn.LogisticRegression``.

    Parameters
    ----------
    max_iter:
        Passed straight through to scikit-learn. 200 is enough for Iris to
        converge comfortably without triggering ConvergenceWarning noise.
    """

    MODEL_TYPE = "logistic_regression"

    def __init__(self, max_iter: int = 200, random_state: int = 42) -> None:
        self._clf = LogisticRegression(max_iter=max_iter, random_state=random_state)
        self._is_fitted = False
        self.feature_names: list[str] = []
        self.class_names: list[str] = []

    # ------------------------------------------------------------------ #
    # Training / inference
    # ------------------------------------------------------------------ #
    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str] | None = None,
        class_names: list[str] | None = None,
    ) -> TrainResult:
        """Fit the model in place on ``(X, y)``. Supports incremental re-fits:

        calling ``train`` again re-fits from scratch on whatever data is
        passed in. Federated aggregation across peers is explicitly out of
        scope for the MVP (see README > Limitations); each round simply
        replaces the previous local model.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            self._clf.fit(X, y)
        self._is_fitted = True
        if feature_names:
            self.feature_names = list(feature_names)
        if class_names:
            self.class_names = list(class_names)
        return TrainResult(n_samples=len(X), accuracy=None, classes=self.class_names)

    def predict(self, X: np.ndarray) -> np.ndarray:
        self._require_fitted()
        return self._clf.predict(X)

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> float:
        """Return accuracy on a held-out set."""
        self._require_fitted()
        preds = self._clf.predict(X)
        return float(np.mean(preds == y))

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def _require_fitted(self) -> None:
        if not self._is_fitted:
            raise RuntimeError("Model has not been trained or loaded yet.")

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def save(self, path: str | Path) -> Path:
        """Serialize the model (and light metadata) to ``path`` via joblib."""
        self._require_fitted()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "sklearn_estimator": self._clf,
            "model_type": self.MODEL_TYPE,
            "feature_names": self.feature_names,
            "class_names": self.class_names,
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "LocalModel":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No checkpoint model file at {path}")
        payload = joblib.load(path)
        instance = cls()
        instance._clf = payload["sklearn_estimator"]
        instance.feature_names = payload.get("feature_names", [])
        instance.class_names = payload.get("class_names", [])
        instance._is_fitted = True
        return instance
