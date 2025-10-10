import pytest
from unittest.mock import MagicMock, patch

from libp2p.record.record import Record
from libp2p.record.validator import NamespacedValidator, Validator
from libp2p.record.exceptions import ErrInvalidRecordType


class MockValidator(Validator):
    """A simple validator that records calls."""
    def __init__(self):
        self.validated = []
        self.selected = []

    def validate(self, rec: Record) -> None:
        self.validated.append(rec)
        if rec.key_str == "bad-record":
            raise ValueError("Invalid record")

    def select(self, key: str, values: list[Record]) -> int:
        self.selected.append((key, values))
        return len(values) - 1  # pick the last for determinism


@pytest.fixture
def namespaced_validator():
    """Create a NamespacedValidator with two dummy sub-validators."""
    v_a = MockValidator()
    v_b = MockValidator()
    nv = NamespacedValidator({"nsA": v_a, "nsB": v_b})
    return nv, v_a, v_b


@pytest.fixture
def record_factory():
    def _rec(key: str, val: str = "value"):
        return Record(key=key, value=val.encode())
    return _rec


# --- Tests ---

def test_validator_by_key_valid_namespace(mocker, namespaced_validator):
    nv, v_a, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsA", "foo"))

    result = nv.validator_by_key("nsA/foo")
    assert result == v_a


def test_validator_by_key_unknown_namespace(mocker, namespaced_validator):
    nv, _, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsX", "foo"))

    result = nv.validator_by_key("nsX/foo")
    assert result is None


def test_validator_by_key_raises_exception_returns_none(mocker, namespaced_validator):
    nv, _, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", side_effect=Exception("bad split"))

    result = nv.validator_by_key("invalid")
    assert result is None


def test_validate_delegates_to_correct_validator(mocker, namespaced_validator, record_factory):
    nv, v_a, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsA", "foo"))

    rec = record_factory("nsA/foo")
    nv.validate(rec)
    assert v_a.validated == [rec]


def test_validate_raises_if_namespace_not_found(mocker, namespaced_validator, record_factory):
    nv, _, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("unknown", "foo"))

    rec = record_factory("unknown/foo")
    with pytest.raises(ErrInvalidRecordType):
        nv.validate(rec)


def test_validate_bubbles_up_exceptions(mocker, namespaced_validator, record_factory):
    nv, v_a, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsA", "foo"))

    rec = record_factory("nsA/foo", val="bad-record")  # will trigger ValueError
    with pytest.raises(ValueError, match="Invalid record"):
        nv.validate(rec)


def test_select_delegates_correctly(mocker, namespaced_validator, record_factory):
    nv, _, v_b = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsB", "foo"))

    values = [record_factory("nsB/foo", "v1"), record_factory("nsB/foo", "v2")]
    idx = nv.select("nsB/foo", values)

    assert idx == 1  # last record selected by MockValidator
    assert v_b.selected 


def test_select_raises_on_empty_values(namespaced_validator):
    nv, _, _ = namespaced_validator
    with pytest.raises(ValueError, match="can't select from no values"):
        nv.select("nsA/foo", [])


def test_select_raises_if_namespace_not_found(mocker, namespaced_validator, record_factory):
    nv, _, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("unknown", "foo"))

    values = [record_factory("unknown/foo")]
    with pytest.raises(ErrInvalidRecordType):
        nv.select("unknown/foo", values)


def test_select_bubbles_up_exception(mocker, namespaced_validator, record_factory):
    """Ensure exceptions from sub-validator.select propagate."""
    nv, v_a, _ = namespaced_validator
    mocker.patch("libp2p.record.validation.split_key", return_value=("nsA", "foo"))

    def bad_select(key, vals):
        raise RuntimeError("Selection failed")

    v_a.select = bad_select

    with pytest.raises(RuntimeError, match="Selection failed"):
        nv.select("nsA/foo", [record_factory("nsA/foo")])
