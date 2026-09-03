"""Unit tests for p2p_checkpoint.model.LocalModel."""

from __future__ import annotations

import numpy as np
import pytest

from examples.iris_data import load_partition
from p2p_checkpoint.model import LocalModel


@pytest.fixture(scope="module")
def iris_data():
    return load_partition("peer-a")


def test_model_trains(iris_data):
    X_train, y_train, *_ = iris_data
    model = LocalModel()
    assert not model.is_fitted
    model.train(X_train, y_train)
    assert model.is_fitted


def test_model_predicts(iris_data):
    X_train, y_train, X_test, y_test, *_ = iris_data
    model = LocalModel()
    model.train(X_train, y_train)
    preds = model.predict(X_test)
    assert preds.shape == y_test.shape
    assert set(np.unique(preds)).issubset({0, 1, 2})


def test_model_evaluate_is_reasonable_on_iris(iris_data):
    X_train, y_train, X_test, y_test, *_ = iris_data
    model = LocalModel()
    model.train(X_train, y_train)
    accuracy = model.evaluate(X_test, y_test)
    # Iris + logistic regression is an easy problem; a real fit should
    # comfortably beat random guessing (1/3) by a wide margin.
    assert accuracy > 0.7


def test_predict_before_train_raises():
    model = LocalModel()
    with pytest.raises(RuntimeError):
        model.predict(np.zeros((1, 4)))


def test_model_saves_and_loads_round_trip(tmp_path, iris_data):
    X_train, y_train, X_test, _, feature_names, class_names = iris_data
    model = LocalModel()
    model.train(X_train, y_train, feature_names=feature_names, class_names=class_names)

    path = tmp_path / "model.pkl"
    model.save(path)
    assert path.exists()

    loaded = LocalModel.load(path)
    assert loaded.is_fitted
    assert loaded.feature_names == feature_names
    assert loaded.class_names == class_names
    np.testing.assert_array_equal(loaded.predict(X_test), model.predict(X_test))


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalModel.load(tmp_path / "does_not_exist.pkl")
