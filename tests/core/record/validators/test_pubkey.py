import pytest
from unittest.mock import patch, MagicMock
from libp2p.record.record import Record
from libp2p.record.validators.pubkey import PublicKeyValidator
from libp2p.record.exceptions import ErrInvalidRecordType


@pytest.fixture
def validator():
    return PublicKeyValidator()


@pytest.fixture
def record_factory():
    def _rec(key: str, value: bytes = b"dummy"):
        return Record(key=key, value=value)
    return _rec

def test_validate_success_path(validator, record_factory):
    """Happy path: all decoding/unmarshalling succeeds and peer ID matches hash."""
    rec = record_factory("pk/abcd1234")

    fake_keyhash = b"\x12\x20" + b"x" * 32  # valid multihash bytes
    fake_pubkey = MagicMock()
    fake_peer_id = MagicMock()
    fake_peer_id.to_bytes.return_value = fake_keyhash

    with patch("libp2p.record.validator.split_key", return_value=("pk", "abcd1234")), \
         patch("libp2p.record.validator.bytes.fromhex", return_value=fake_keyhash), \
         patch("libp2p.record.validator.multihash.decode", return_value="decoded"), \
         patch("libp2p.record.validator.unmarshal_public_key", return_value=fake_pubkey), \
         patch("libp2p.record.validator.ID.from_pubkey", return_value=fake_peer_id):
        # Should not raise
        validator.validate(rec)


def test_validate_raises_if_namespace_not_pk(validator, record_factory):
    rec = record_factory("wrongns/abcd")
    with patch("libp2p.record.validator.split_key", return_value=("wrongns", "abcd")):
        with pytest.raises(ErrInvalidRecordType, match="namespace not 'pk'"):
            validator.validate(rec)


def test_validate_raises_if_invalid_multihash(validator, record_factory):
    rec = record_factory("pk/abcd")

    with patch("libp2p.record.validator.split_key", return_value=("pk", "abcd")), \
         patch("libp2p.record.validator.bytes.fromhex", return_value=b"1234"), \
         patch("libp2p.record.validator.multihash.decode", side_effect=Exception("invalid mh")):
        with pytest.raises(ErrInvalidRecordType, match="valid multihash"):
            validator.validate(rec)


def test_validate_raises_if_unmarshal_fails(validator, record_factory):
    rec = record_factory("pk/abcd")

    with patch("libp2p.record.validator.split_key", return_value=("pk", "abcd")), \
         patch("libp2p.record.validator.bytes.fromhex", return_value=b"1234"), \
         patch("libp2p.record.validator.multihash.decode", return_value="decoded"), \
         patch("libp2p.record.validator.unmarshal_public_key", side_effect=Exception("bad pubkey")):
        with pytest.raises(ErrInvalidRecordType, match="Unable to unmarshal public key"):
            validator.validate(rec)


def test_validate_raises_if_peer_id_derivation_fails(validator, record_factory):
    rec = record_factory("pk/abcd")

    fake_pubkey = MagicMock()

    with patch("libp2p.record.validator.split_key", return_value=("pk", "abcd")), \
         patch("libp2p.record.validator.bytes.fromhex", return_value=b"1234"), \
         patch("libp2p.record.validator.multihash.decode", return_value="decoded"), \
         patch("libp2p.record.validator.unmarshal_public_key", return_value=fake_pubkey), \
         patch("libp2p.record.validator.ID.from_pubkey", side_effect=Exception("fail")):
        with pytest.raises(ErrInvalidRecordType, match="Could not derive peer ID"):
            validator.validate(rec)


def test_validate_raises_if_peer_id_bytes_mismatch(validator, record_factory):
    rec = record_factory("pk/abcd")

    fake_pubkey = MagicMock()
    fake_peer_id = MagicMock()
    fake_peer_id.to_bytes.return_value = b"DIFFERENT"

    with patch("libp2p.record.validator.split_key", return_value=("pk", "abcd")), \
         patch("libp2p.record.validator.bytes.fromhex", return_value=b"hash"), \
         patch("libp2p.record.validator.multihash.decode", return_value="decoded"), \
         patch("libp2p.record.validator.unmarshal_public_key", return_value=fake_pubkey), \
         patch("libp2p.record.validator.ID.from_pubkey", return_value=fake_peer_id):
        with pytest.raises(ErrInvalidRecordType, match="does not match storage key"):
            validator.validate(rec)


def test_select_always_returns_zero(validator, record_factory):
    recs = [record_factory("pk/abcd"), record_factory("pk/efgh")]
    idx = validator.select("pk/abcd", recs)
    assert idx == 0


def test_select_does_not_raise_on_empty_list(validator):
    """Even though docstring doesn't specify, should not throw — just return 0."""
    assert validator.select("pk/abcd", []) == 0
