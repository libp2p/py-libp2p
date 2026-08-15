import pytest

from libp2p.crypto.ed25519 import Ed25519PublicKey, create_new_key_pair
from libp2p.crypto.keys import PublicKey
from libp2p.peer.id import ID
from libp2p.records.pubkey import PublicKeyValidator, unmarshal_public_key
from libp2p.records.record import make_put_record
from libp2p.records.utils import (
    InvalidRecordType,
    sign_record,
    split_key,
    verify_record,
)
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
    key = b"some_key"
    value = b"some_value"

    record = make_put_record(key, value)
    assert record.key == key
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
    validators = NamespacedValidator(
        {"dummy": DummyValidator()}, strict_validation=True
    )

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


# Tests for strict_validation mode (GitHub Issue #1070)
class TestStrictValidation:
    """Tests for the strict_validation feature that validates all DHT records."""

    def test_strict_validation_disabled_allows_non_namespaced_keys(self):
        """With strict_validation=False (default), non-namespaced keys are accepted."""
        validators = NamespacedValidator({"dummy": DummyValidator()})

        # Non-namespaced key should be accepted (uses fallback BlankValidator)
        validators.validate("plain-key", b"some-value")  # Should not raise

    def test_strict_validation_enabled_rejects_non_namespaced_keys(self):
        """With strict_validation=True, non-namespaced keys are rejected."""
        validators = NamespacedValidator(
            {"dummy": DummyValidator()},
            strict_validation=True,
        )

        # Non-namespaced key should be rejected
        with pytest.raises(InvalidRecordType, match="strict validation"):
            validators.validate("plain-key", b"some-value")

    def test_strict_validation_enabled_accepts_valid_namespaced_keys(self):
        """With strict_validation=True, valid namespaced keys are accepted."""
        validators = NamespacedValidator(
            {"dummy": DummyValidator()},
            strict_validation=True,
        )

        # Valid namespaced key should be accepted
        validators.validate("/dummy/somekey", b"valid-data")  # Should not raise

    def test_strict_validation_enabled_rejects_unknown_namespace(self):
        """With strict_validation=True, unknown namespaces are rejected."""
        validators = NamespacedValidator(
            {"dummy": DummyValidator()},
            strict_validation=True,
        )

        # Key with unregistered namespace should be rejected
        with pytest.raises(InvalidRecordType, match="No validator registered"):
            validators.validate("/unknown/somekey", b"some-value")

    def test_strict_validation_select_with_non_namespaced_key(self):
        """Test select() behavior with non-namespaced keys."""
        # Without strict validation - should return first value
        validators = NamespacedValidator({"dummy": DummyValidator()})
        idx = validators.select("plain-key", [b"a", b"b", b"c"])
        assert idx == 0

        # With strict validation - should raise
        validators_strict = NamespacedValidator(
            {"dummy": DummyValidator()},
            strict_validation=True,
        )
        with pytest.raises(InvalidRecordType, match="strict validation"):
            validators_strict.select("plain-key", [b"a", b"b", b"c"])

    def test_strict_validation_can_be_toggled(self):
        """Test that strict_validation can be enabled/disabled dynamically."""
        validators = NamespacedValidator({"dummy": DummyValidator()})

        # Initially permissive
        validators.validate("plain-key", b"value")  # Should not raise

        # Enable strict mode
        validators.strict_validation = True
        with pytest.raises(InvalidRecordType, match="strict validation"):
            validators.validate("plain-key", b"value")

        # Disable strict mode
        validators.strict_validation = False
        validators.validate("plain-key", b"value")  # Should not raise again

    def test_custom_fallback_validator(self):
        """Test that custom fallback validators work correctly."""

        class RejectAllValidator(Validator):
            def validate(self, key: str, value: bytes) -> None:
                raise ValueError("Rejected by fallback")

            def select(self, key: str, values: list[bytes]) -> int:
                return 0

        validators = NamespacedValidator(
            {"dummy": DummyValidator()},
            strict_validation=False,
            fallback_validator=RejectAllValidator(),
        )

        # Namespaced key uses dummy validator
        validators.validate("/dummy/key", b"valid-data")  # Should not raise

        # Non-namespaced key uses custom fallback that rejects
        with pytest.raises(ValueError, match="Rejected by fallback"):
            validators.validate("plain-key", b"value")


# ─────────────────────────────────────────────────────────────────────────────
# verify_record — multi-key-type coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyRecord:
    """
    verify_record must accept signatures from every key type that libp2p
    serialises via crypto_pb2.PublicKey (Ed25519, Secp256k1, RSA).

    Previously the implementation hard-coded Ed25519PublicKey.from_bytes,
    causing it to silently return False for RSA and Secp256k1 peers and
    breaking DHT interoperability with non-Ed25519 nodes.
    """

    def _round_trip(self, key_pair) -> None:  # noqa: ANN001
        """Sign with *key_pair* and assert verify_record returns True."""
        key = b"/test/mykey"
        value = b"hello world"
        sig, author = sign_record(key_pair.private_key, key, value)
        assert verify_record(sig, author, key, value), (
            f"verify_record returned False for key type "
            f"{key_pair.private_key.get_type()}"
        )

    def _tampered_fails(self, key_pair) -> None:  # noqa: ANN001
        """Tampered payload must make verify_record return False."""
        key = b"/test/mykey"
        value = b"hello world"
        sig, author = sign_record(key_pair.private_key, key, value)
        assert not verify_record(sig, author, key, b"tampered"), (
            f"verify_record accepted tampered value for key type "
            f"{key_pair.private_key.get_type()}"
        )

    def test_ed25519_valid_signature(self) -> None:
        from libp2p.crypto.ed25519 import create_new_key_pair as ed_kp

        self._round_trip(ed_kp())

    def test_ed25519_tampered_value_rejected(self) -> None:
        from libp2p.crypto.ed25519 import create_new_key_pair as ed_kp

        self._tampered_fails(ed_kp())

    def test_secp256k1_valid_signature(self) -> None:
        from libp2p.crypto.secp256k1 import create_new_key_pair as secp_kp

        self._round_trip(secp_kp())

    def test_secp256k1_tampered_value_rejected(self) -> None:
        from libp2p.crypto.secp256k1 import create_new_key_pair as secp_kp

        self._tampered_fails(secp_kp())

    def test_rsa_valid_signature(self) -> None:
        from libp2p.crypto.rsa import create_new_key_pair as rsa_kp

        self._round_trip(rsa_kp())

    def test_rsa_tampered_value_rejected(self) -> None:
        from libp2p.crypto.rsa import create_new_key_pair as rsa_kp

        self._tampered_fails(rsa_kp())

    def test_garbage_author_bytes_returns_false(self) -> None:
        """Completely invalid author bytes must return False, not raise."""
        assert not verify_record(b"sig", b"not-a-valid-protobuf", b"key", b"value")

    def test_wrong_key_returns_false(self) -> None:
        """Signature verified against a different key must return False."""
        from libp2p.crypto.ed25519 import create_new_key_pair as ed_kp

        kp1 = ed_kp()
        kp2 = ed_kp()
        key = b"/test/k"
        value = b"v"
        sig, _ = sign_record(kp1.private_key, key, value)
        _, author2 = sign_record(kp2.private_key, key, value)
        assert not verify_record(sig, author2, key, value)
