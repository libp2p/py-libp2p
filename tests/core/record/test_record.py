import pytest
from google.protobuf.message import DecodeError

from libp2p.record.pb import record_pb2 as pb
from libp2p.record.record import Record


@pytest.fixture
def mock_record():
    return Record(
        key="test-key",
        value=b"test-value",
        time_received="2025-10-10T00:00:00Z"
    )

def test_init_with_str_key(mock_record):
    assert isinstance(mock_record.key, bytes)
    assert mock_record.key == b"test-key"
    assert mock_record.value == b"test-value"
    assert mock_record.time_received == "2025-10-10T00:00:00Z"


def test_init_with_bytes_key():
    rec = Record(key=b"binary-key", value=b"val")
    assert rec.key == b"binary-key"
    assert rec.key_str == "binary-key"
    assert rec.value == b"val"
    assert rec.time_received == ""

def test_key_and_value_str_properties(mock_record):
    assert mock_record.key_str == "test-key"
    assert mock_record.value_str == "test-value"

def test_marshal_and_unmarshal_roundtrip(mock_record):
    marshaled = mock_record.marshal()
    assert isinstance(marshaled, bytes)
    new_rec = Record.unmarshal(marshaled)
    assert new_rec == mock_record
    assert new_rec.key == b"test-key"
    assert new_rec.value == b"test-value"
    assert new_rec.time_received == "2025-10-10T00:00:00Z"

def test_unmarshal_invalid_data():
    with pytest.raises(DecodeError):
        Record.unmarshal(b"not a valid protobuf")

def test_equality(mock_record):
    rec2 = Record(
        key="test-key",
        value=b"test-value",
        time_received="2025-10-10T00:00:00Z"
    )
    rec3 = Record(key="other-key", value=b"diff-value")
    assert mock_record == rec2
    assert not (mock_record != rec2)
    assert mock_record != rec3
    assert not mock_record.__eq__(object())


def test_repr_contains_all_fields(mock_record):
    r = repr(mock_record)
    assert "<Record" in r
    assert "test-key" in r
    assert "test-value" in r
    assert "2025-10-10T00:00:00Z" in r


def test_empty_time_received_defaults_to_empty_string():
    rec = Record(key="key", value=b"value")
    assert rec.time_received == ""
    assert isinstance(rec.raw_record, pb.Record)


def test_roundtrip_with_non_utf8_key_value():
    key = b"\xff\xfe\xfd"
    value = b"\xfa\xfb\xfc"
    rec = Record(key=key, value=value, time_received="t")
    marshaled = rec.marshal()
    new_rec = Record.unmarshal(marshaled)
    assert new_rec.key == key
    assert new_rec.value == value
    assert new_rec.time_received == "t"
