"""
examples/iris_data.py
----------------------

Splits the classic Iris dataset between two demo peers, per README section
5: peer-a gets a 70% shard, peer-b gets the remaining 30%, both drawn from
the same stratified split so each peer's local model is at least plausible
on its own.

This is intentionally the *only* place sklearn's dataset loader is used --
``model.py`` stays dataset-agnostic and just consumes whatever ``(X, y)``
arrays it's handed.
"""

from __future__ import annotations

import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

PEER_SHARES = {
    "peer-a": 0.70,
    "peer-b": 0.30,
}


def load_partition(
    peer_name: str, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], list[str]]:
    """
    Returns ``(X_train, y_train, X_test, y_test, feature_names, class_names)``
    for the given peer.

    ``peer_name`` must be one of the keys in ``PEER_SHARES``. Any other
    name falls back to an even, deterministic hash-based split so the demo
    isn't hard-limited to exactly two participants.
    """
    iris = load_iris()
    X, y = iris.data, iris.target
    feature_names = list(iris.feature_names)
    class_names = list(iris.target_names)

    # Hold out a common test set (20%) shared by all peers, so accuracy
    # numbers printed by different peers are directly comparable.
    X_pool, X_test, y_pool, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )

    if peer_name in PEER_SHARES:
        share_a = PEER_SHARES["peer-a"]
        X_a, X_b, y_a, y_b = train_test_split(
            X_pool, y_pool, train_size=share_a, random_state=seed, stratify=y_pool
        )
        X_train, y_train = (X_a, y_a) if peer_name == "peer-a" else (X_b, y_b)
    else:
        # Deterministic fallback shard for any additional peer name.
        rng = np.random.default_rng(abs(hash(peer_name)) % (2**32))
        idx = rng.permutation(len(X_pool))[: max(10, len(X_pool) // 3)]
        X_train, y_train = X_pool[idx], y_pool[idx]

    return X_train, y_train, X_test, y_test, feature_names, class_names
