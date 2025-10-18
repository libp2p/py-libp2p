import pytest

from libp2p.crypto.ed25519 import Ed25519PublicKey, create_new_key_pair
from libp2p.crypto.keys import PublicKey
from libp2p.peer.id import ID
from libp2p.records.pubkey import PublicKeyValidator, unmarshal_public_key
from libp2p.records.record import make_put_record
from libp2p.records.utils import InvalidRecordType, split_key
from libp2p.records.validator import NamespacedValidator, Validator

bad_paths = [
    "foo/bar/baz",
    "//foo/nar/baz",
    "/ns",
    "ns",
    "ns/",
    "",
    "//",
    "/",
    "////",
]


@pytest.mark.parametrize("path", bad_paths)
def test_split_key_bad(path):
    with pytest.raises(InvalidRecordType):
        split_key(path)


def test_split_key_good_multi():
    ns, key = split_key("/foo/bar/baz")
    assert ns == "foo", f"expected ns='foo, got '{ns}'"
    assert key == "bar/baz", f"expected key='bar/baz', got '{key}'"


def test_make_put_record():
    key = "some_key"
    value = b"some_value"

    record = make_put_record(key, value)
    assert record.key == key.encode()
    assert record.value == value


class DummyValidator(Validator):
    def validate(self, key: str, value: bytes) -> None:
        if not value:
            raise ValueError("value is empty")

    def select(self, key: str, values: list[bytes]) -> int:
        return max(range(len(values)), key=lambda i: len(values[i]))


def test_namespaced_validator_validate_and_select():
    validators = NamespacedValidator({"dummy": DummyValidator()})

    key = "/dummy/somekey"
    value = b"valid-data"

    validators.validate(key, value)

    values = [b"short", b"longer", b"longest-data"]
    idx = validators.select(key, values)
    assert idx == 2


def test_namespaced_validator_invalid_key():
    validators = NamespacedValidator({"dummy": DummyValidator()})

    # Invalid namespace
    with pytest.raises(InvalidRecordType):
        validators.validate("/wrongns/somekey", b"valid-data")

    # Key that doesn't start with /
    with pytest.raises(InvalidRecordType):
        validators.validate("not/a/valid/key", b"valid-data")

    # select from empty list
    with pytest.raises(ValueError):
        validators.select("/dummy/somekey", [])


def test_dummy_validator_rejects_empty():
    validator = DummyValidator()
    with pytest.raises(ValueError):
        validator.validate("/dummy/somekey", b"")


def test_unmarshal_ed25519_public_key():
    key_pair = create_new_key_pair()
    pubkey = key_pair.public_key

    serialized = pubkey.serialize()

    unamrshalled = unmarshal_public_key(serialized)

    assert isinstance(unamrshalled, Ed25519PublicKey)
    assert isinstance(unamrshalled, PublicKey)
    assert unamrshalled.to_bytes() == pubkey.to_bytes()


def test_validate_valid_public_key():
    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)
    key = f"/pk/{peer_id.to_bytes().hex()}"
    value = keypair.public_key.serialize()

    validator = PublicKeyValidator()
    validator.validate(key, value)  # Should not raise


def test_validate_wrong_namespace():
    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)
    key = f"/wrongns/{peer_id.to_bytes().hex()}"
    value = keypair.public_key.serialize()

    validator = PublicKeyValidator()
    with pytest.raises(InvalidRecordType, match="namespace not 'pk'"):
        validator.validate(key, value)


def test_validate_invalid_multihash():
    key = "/pk/abcdef1234567890"  # Not a valid multihash
    value = b"not-a-real-key"

    validator = PublicKeyValidator()
    with pytest.raises(InvalidRecordType, match="valid multihash"):
        validator.validate(key, value)


def test_validate_peer_id_mismatch():
    key_pair1 = create_new_key_pair()
    key_pair2 = create_new_key_pair()

    # Construct key using peer_id1
    peer_id1 = ID.from_pubkey(key_pair1.public_key)
    key = f"/pk/{peer_id1.to_bytes().hex()}"

    # But serialize a different public key (pub_key2)
    value = key_pair2.public_key.serialize()

    validator = PublicKeyValidator()
    with pytest.raises(InvalidRecordType, match="does not match storage key"):
        validator.validate(key, value)
