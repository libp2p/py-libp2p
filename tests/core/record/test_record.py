import pytest
from typing import cast
from libp2p.record.record import (
    Record, 
    register_type, 
    blank_record_for_payload_type, 
    unmarshal_record_payload,
    _payload_type_registry
)


# Dummy concrete Record class for testing
class DummyRecord(Record):
    def __init__(self, data: bytes = b""):
        self.data = data

    def domain(self) -> str:
        return "dummy"

    def codec(self) -> bytes:
        return b"dummy-record"

    def marshal_record(self) -> bytes:
        return self.data

    def unmarshal_record(self, data: bytes) -> None:
        self.data = data


@pytest.fixture(autouse=True)
def setup_registry():
    # Clear registry before each test
    _payload_type_registry.clear()
    register_type(DummyRecord())


def test_register_type_adds_to_registry():
    assert b"dummy-record" in _payload_type_registry
    assert _payload_type_registry[b"dummy-record"] == DummyRecord


def test_register_type_invalid_codec():
    class BadRecord(Record):
        def domain(self): return "bad"
        def codec(self): return cast(bytes, "not-bytes")
        def marshal_record(self): return b""
        def unmarshal_record(self, data: bytes): pass

    with pytest.raises(TypeError):
        register_type(BadRecord())


def test_blank_record_for_payload_type_returns_instance():
    rec = blank_record_for_payload_type(b"dummy-record")
    assert isinstance(rec, DummyRecord)
    assert rec.data == b""


def test_blank_record_for_unknown_payload_type_raises():
    with pytest.raises(ValueError):
        blank_record_for_payload_type(b"unknown-record")


def test_unmarshal_record_payload_sets_data_correctly():
    payload = b"testdata"
    rec = unmarshal_record_payload(b"dummy-record", payload)
    assert isinstance(rec, DummyRecord)
    assert rec.data == payload


def test_unmarshal_record_payload_unknown_type_raises():
    with pytest.raises(ValueError):
        unmarshal_record_payload(b"unknown", b"data")


def test_marshal_and_unmarshal_roundtrip():
    original = DummyRecord(b"hello")
    marshaled = original.marshal_record()
    new_rec = DummyRecord()
    new_rec.unmarshal_record(marshaled)
    assert new_rec.data == original.data


def test_multiple_records_independent():
    r1 = DummyRecord(b"one")
    r2 = DummyRecord(b"two")
    assert r1.data != r2.data
    r1.unmarshal_record(b"updated")
    assert r1.data == b"updated"
    assert r2.data == b"two"
