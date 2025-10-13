import pytest

from libp2p.record.exceptions import ErrInvalidRecordType
from libp2p.record.record import Record
from libp2p.record.validators.pubkey import PublicKeyValidator


# Mock classes for testing
class MockPublicKey:
    def __init__(self, peer_id_bytes):
        self._peer_id_bytes = peer_id_bytes

    def to_bytes(self):
        return self._peer_id_bytes

class MockPeerID:
    def __init__(self, peer_id_bytes):
        self._peer_id_bytes = peer_id_bytes

    @classmethod
    def from_pubkey(cls, pubkey):
        return cls(pubkey._peer_id_bytes)

    def to_bytes(self):
        return self._peer_id_bytes

@pytest.fixture
def validator():
    """Fixture to create a PublicKeyValidator instance."""
    return PublicKeyValidator()

@pytest.fixture
def valid_keyhash():
    """Fixture for a valid multihash key."""
    sample_digest = b"\x01" * 32
    multihash_bytes = b"\x12\x20" + sample_digest
    return multihash_bytes.hex()

@pytest.fixture
def valid_record(valid_keyhash):
    """Fixture for a valid Record instance."""
    record = Record(key=f"pk/{valid_keyhash}", value=b"valid_pubkey")
    return record

def test_validate_invalid_namespace(validator, valid_record, mocker):
    """Test validate with an invalid namespace."""
    mocker.patch(
        "libp2p.record.utils.split_key",
        return_value=("invalid_ns", "somehash")
    )

    with pytest.raises(ErrInvalidRecordType):
        validator.validate(valid_record)

def test_validate_invalid_multihash(validator, valid_record, mocker):
    """Test validate with an invalid multihash."""
    mocker.patch("libp2p.record.utils.split_key", return_value=("pk", "invalidhash"))
    mocker.patch("multihash.decode", side_effect=Exception("Invalid multihash"))

    with pytest.raises(ErrInvalidRecordType):
        validator.validate(valid_record)

def test_validate_invalid_public_key(validator, valid_record, valid_keyhash, mocker):
    """Test validate with an unmarshalable public key."""
    mocker.patch("libp2p.record.utils.split_key", return_value=("pk", valid_keyhash))
    mocker.patch(
        "multihash.decode",
        return_value={"code": 0x12, "name": "sha2-256", "length": 32}
    )
    mocker.patch(
        "libp2p.record.utils.unmarshal_public_key",
        side_effect=Exception("Invalid public key")
    )

    with pytest.raises(ErrInvalidRecordType):
        validator.validate(valid_record)

def test_validate_invalid_peer_id_derivation(
        validator,
        valid_record,
        valid_keyhash,
        mocker
    ):
    """Test validate when peer ID derivation fails."""
    mocker.patch("libp2p.record.utils.split_key", return_value=("pk", valid_keyhash))
    mocker.patch(
        "multihash.decode",
        return_value={"code": 0x12, "name": "sha2-256", "length": 32}
    )
    mocker.patch(
        "libp2p.record.utils.unmarshal_public_key",
        return_value=MockPublicKey(b"\x01" * 32)
    )
    mocker.patch(
        "libp2p.peer.id.ID.from_pubkey",
        side_effect=Exception("Invalid peer ID")
    )

    with pytest.raises(ErrInvalidRecordType):
        validator.validate(valid_record)

def test_validate_mismatched_keyhash(validator, valid_record, valid_keyhash, mocker):
    """Test validate when public key does not match keyhash."""
    mocker.patch("libp2p.record.utils.split_key", return_value=("pk", valid_keyhash))
    mocker.patch(
        "multihash.decode",
        return_value={"code": 0x12, "name": "sha2-256", "length": 32}
    )
    mocker.patch(
        "libp2p.record.utils.unmarshal_public_key",
        return_value=MockPublicKey(b"\x02" * 32)
    )
    mocker.patch("libp2p.peer.id.ID.from_pubkey", return_value=MockPeerID(b"\x02" * 32))

    with pytest.raises(ErrInvalidRecordType):
        validator.validate(valid_record)

# Tests for select method
def test_select_no_records(validator):
    """Test select with an empty record list."""
    result = validator.select("somekey", [])
    assert result is None

def test_select_single_record(validator, valid_record):
    """Test select with a single record."""
    result = validator.select("somekey", [valid_record])
    assert result == valid_record

def test_select_multiple_records(validator, valid_record):
    """Test select with multiple records."""
    result = validator.select("somekey", [valid_record, valid_record])
    assert result == valid_record  # Should return the first record
