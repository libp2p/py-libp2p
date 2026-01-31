from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import cbor2

from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    create_new_key_pair as create_ed25519_keypair,
)
from libp2p.crypto.pb import crypto_pb2
from libp2p.peer.id import ID
from libp2p.records.ipns import (
    MAX_RECORD_SIZE,
    SIGNATURE_PREFIX,
    VALIDITY_TYPE_EOL,
    IPNSValidator,
)
from libp2p.records.pb.ipns_pb2 import IpnsEntry
from libp2p.records.utils import InvalidRecordType


class TestIPNSValidator:
    """Tests for IPNSValidator class."""

    @pytest.fixture
    def validator(self) -> IPNSValidator:
        """Create an IPNS validator instance."""
        return IPNSValidator()

    @pytest.fixture
    def ed25519_keypair(self):
        """Create an Ed25519 key pair for testing."""
        keypair = create_ed25519_keypair()
        return keypair.private_key, keypair.public_key

    def _create_ipns_name(self, private_key: Ed25519PrivateKey) -> str:
        """Create an IPNS name from a private key (identity multihash of public key)."""
        peer_id = ID.from_pubkey(private_key.get_public_key())
        return peer_id.to_bytes().hex()

    def _create_valid_ipns_record(
        self,
        private_key: Ed25519PrivateKey,
        value: bytes = b"/ipfs/QmTest123",
        sequence: int = 1,
        ttl: int = 300_000_000_000,  # 5 minutes in nanoseconds
        validity_delta: timedelta = timedelta(hours=1),
    ) -> bytes:
        """
        Create a valid IPNS record for testing.

        Args:
            private_key: The Ed25519 private key to sign the record
            value: The content path (default: /ipfs/QmTest123)
            sequence: The sequence number
            ttl: Time-to-live in nanoseconds
            validity_delta: How far in the future the record expires

        Returns:
            Serialized IpnsEntry protobuf bytes

        """
        # Calculate validity timestamp (RFC3339 format)
        expiry = datetime.now(timezone.utc) + validity_delta
        validity = expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        validity_bytes = validity.encode("ascii")

        # Create DAG-CBOR data (keys must be sorted per spec)
        cbor_data = {
            "Sequence": sequence,
            "TTL": ttl,
            "Validity": validity_bytes,
            "ValidityType": VALIDITY_TYPE_EOL,
            "Value": value,
        }
        # Encode with sorted keys (DAG-CBOR requirement)
        data_bytes = cbor2.dumps(cbor_data, canonical=True)

        # Create signature over "ipns-signature:" + CBOR data
        signature_payload = SIGNATURE_PREFIX + data_bytes
        signature = private_key.sign(signature_payload)

        # Create the IpnsEntry protobuf
        entry = IpnsEntry()
        entry.value = value
        entry.validityType = IpnsEntry.ValidityType.EOL
        entry.validity = validity_bytes
        entry.sequence = sequence
        entry.ttl = ttl
        entry.signatureV2 = signature
        entry.data = data_bytes

        # For Ed25519, public key is inlined in name, so pubKey is optional
        # but we can include it for completeness
        # entry.pubKey = marshal_public_key(private_key.get_public_key())

        return entry.SerializeToString()

    def _marshal_public_key(self, public_key) -> bytes:
        """Marshal a public key to protobuf format."""
        proto_key = crypto_pb2.PublicKey()
        proto_key.key_type = crypto_pb2.KeyType.Ed25519
        proto_key.data = public_key.to_bytes()
        return proto_key.SerializeToString()

    # ==================== Basic Validation Tests ====================

    def test_validate_valid_record(self, validator, ed25519_keypair):
        """Test that a valid IPNS record passes validation."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"
        value = self._create_valid_ipns_record(private_key)

        # Should not raise any exception
        validator.validate(key, value)

    def test_validate_wrong_namespace(self, validator, ed25519_keypair):
        """Test that records with wrong namespace are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/pk/{name_hash}"  # Wrong namespace
        value = self._create_valid_ipns_record(private_key)

        with pytest.raises(InvalidRecordType, match="namespace not 'ipns'"):
            validator.validate(key, value)

    def test_validate_record_too_large(self, validator, ed25519_keypair):
        """Test that records exceeding size limit are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create an oversized record
        oversized_value = b"x" * (MAX_RECORD_SIZE + 1)

        with pytest.raises(InvalidRecordType, match="exceeds size limit"):
            validator.validate(key, oversized_value)

    def test_validate_invalid_protobuf(self, validator, ed25519_keypair):
        """Test that invalid protobuf data is rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"
        invalid_data = b"not a valid protobuf"

        with pytest.raises(InvalidRecordType, match="Failed to parse IPNS record"):
            validator.validate(key, invalid_data)

    def test_validate_missing_signature_v2(self, validator, ed25519_keypair):
        """Test that records without signatureV2 are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create entry without signatureV2
        entry = IpnsEntry()
        entry.data = cbor2.dumps({"Value": b"/ipfs/test"})
        # entry.signatureV2 is not set

        with pytest.raises(InvalidRecordType, match="Missing or empty signatureV2"):
            validator.validate(key, entry.SerializeToString())

    def test_validate_missing_data(self, validator, ed25519_keypair):
        """Test that records without data field are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create entry without data
        entry = IpnsEntry()
        entry.signatureV2 = b"fake_signature"
        # entry.data is not set

        with pytest.raises(InvalidRecordType, match="Missing or empty data field"):
            validator.validate(key, entry.SerializeToString())

    # ==================== Signature Verification Tests ====================

    def test_validate_invalid_signature(self, validator, ed25519_keypair):
        """Test that records with invalid signatures are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create a valid record first
        valid_record = self._create_valid_ipns_record(private_key)

        # Parse and corrupt the signature
        entry = IpnsEntry()
        entry.ParseFromString(valid_record)
        entry.signatureV2 = b"corrupted_signature_data_here_1234567890"

        with pytest.raises(
            InvalidRecordType, match="Invalid signatureV2|Signature verification error"
        ):
            validator.validate(key, entry.SerializeToString())

    def test_validate_wrong_key_signature(self, validator, ed25519_keypair):
        """Test that records signed with wrong key are rejected."""
        private_key, _ = ed25519_keypair
        # Create a different key pair
        other_keypair = create_ed25519_keypair()
        from libp2p.crypto.ed25519 import Ed25519PrivateKey

        other_private_key = other_keypair.private_key
        if not isinstance(other_private_key, Ed25519PrivateKey):
            other_private_key = Ed25519PrivateKey.from_bytes(
                other_private_key.to_bytes()
            )

        # Use name from first key but sign with second key
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create record signed with different key
        value = self._create_valid_ipns_record(other_private_key)

        with pytest.raises(InvalidRecordType):
            validator.validate(key, value)

    # ==================== Validity/Expiration Tests ====================

    def test_validate_expired_record(self, validator, ed25519_keypair):
        """Test that expired records are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create a record that expired 1 hour ago
        value = self._create_valid_ipns_record(
            private_key,
            validity_delta=timedelta(hours=-1),  # Expired
        )

        with pytest.raises(InvalidRecordType, match="expired"):
            validator.validate(key, value)

    def test_validate_future_valid_record(self, validator, ed25519_keypair):
        """Test that records valid far in the future are accepted."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create a record valid for 100 years (like test vectors)
        value = self._create_valid_ipns_record(
            private_key,
            validity_delta=timedelta(days=365 * 100),
        )

        # Should not raise
        validator.validate(key, value)

    # ==================== V1/V2 Consistency Tests ====================

    def test_validate_v1_v2_value_mismatch(self, validator, ed25519_keypair):
        """Test that mismatched V1/V2 values are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create a valid record
        valid_record = self._create_valid_ipns_record(
            private_key, value=b"/ipfs/correct"
        )

        # Parse and modify V1 value to be different
        entry = IpnsEntry()
        entry.ParseFromString(valid_record)
        entry.value = b"/ipfs/wrong"  # Different from CBOR data

        with pytest.raises(InvalidRecordType, match="V1 value doesn't match"):
            validator.validate(key, entry.SerializeToString())

    def test_validate_v1_v2_sequence_mismatch(self, validator, ed25519_keypair):
        """Test that mismatched V1/V2 sequence numbers are rejected."""
        private_key, _ = ed25519_keypair
        name_hash = self._create_ipns_name(private_key)
        key = f"/ipns/{name_hash}"

        # Create a valid record with sequence=1
        valid_record = self._create_valid_ipns_record(private_key, sequence=1)

        # Parse and modify V1 sequence
        entry = IpnsEntry()
        entry.ParseFromString(valid_record)
        entry.sequence = 999  # Different from CBOR

        with pytest.raises(InvalidRecordType, match="V1 sequence doesn't match"):
            validator.validate(key, entry.SerializeToString())

    # ==================== Selection Tests ====================

    def test_select_higher_sequence_wins(self, validator, ed25519_keypair):
        """Test that records with higher sequence numbers are selected."""
        private_key, _ = ed25519_keypair

        # Create records with different sequence numbers
        record1 = self._create_valid_ipns_record(private_key, sequence=1)
        record2 = self._create_valid_ipns_record(private_key, sequence=5)
        record3 = self._create_valid_ipns_record(private_key, sequence=3)

        values = [record1, record2, record3]
        best_idx = validator.select("/ipns/test", values)

        assert best_idx == 1, "Record with sequence=5 should be selected"

    def test_select_equal_sequence_longer_validity_wins(
        self, validator, ed25519_keypair
    ):
        """Test that with equal sequence, longer validity wins."""
        private_key, _ = ed25519_keypair

        # Create records with same sequence but different validity
        record1 = self._create_valid_ipns_record(
            private_key, sequence=1, validity_delta=timedelta(hours=1)
        )
        record2 = self._create_valid_ipns_record(
            private_key, sequence=1, validity_delta=timedelta(hours=24)
        )

        values = [record1, record2]
        best_idx = validator.select("/ipns/test", values)

        assert best_idx == 1, "Record with longer validity should be selected"

    def test_select_empty_list_raises(self, validator):
        """Test that selecting from empty list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot select from empty"):
            validator.select("/ipns/test", [])

    def test_select_skips_invalid_records(self, validator, ed25519_keypair):
        """Test that invalid records are skipped during selection."""
        private_key, _ = ed25519_keypair

        valid_record = self._create_valid_ipns_record(private_key, sequence=1)
        invalid_record = b"invalid protobuf data"

        values = [invalid_record, valid_record]
        best_idx = validator.select("/ipns/test", values)

        assert best_idx == 1, "Valid record should be selected"


class TestIPNSValidatorEdgeCases:
    """Edge case tests for IPNSValidator."""

    @pytest.fixture
    def validator(self) -> IPNSValidator:
        return IPNSValidator()

    def test_validate_with_explicit_pubkey(self):
        """Test validation when pubKey is explicitly provided in record."""
        validator = IPNSValidator()
        keypair = create_ed25519_keypair()
        private_key = keypair.private_key
        public_key = keypair.public_key

        # Create name from key
        peer_id = ID.from_pubkey(public_key)
        name_hash = peer_id.to_bytes().hex()
        key = f"/ipns/{name_hash}"

        # Create CBOR data
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        validity = expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        validity_bytes = validity.encode("ascii")

        cbor_data = {
            "Sequence": 1,
            "TTL": 300_000_000_000,
            "Validity": validity_bytes,
            "ValidityType": 0,
            "Value": b"/ipfs/QmTest",
        }
        data_bytes = cbor2.dumps(cbor_data, canonical=True)

        # Sign
        signature = private_key.sign(SIGNATURE_PREFIX + data_bytes)

        # Create entry with explicit pubKey
        entry = IpnsEntry()
        entry.value = b"/ipfs/QmTest"
        entry.validityType = IpnsEntry.ValidityType.EOL
        entry.validity = validity_bytes
        entry.sequence = 1
        entry.ttl = 300_000_000_000
        entry.signatureV2 = signature
        entry.data = data_bytes

        # Add explicit pubKey
        proto_key = crypto_pb2.PublicKey()
        proto_key.key_type = crypto_pb2.KeyType.Ed25519
        proto_key.data = public_key.to_bytes()
        entry.pubKey = proto_key.SerializeToString()

        # Should validate successfully
        validator.validate(key, entry.SerializeToString())

    def test_validate_nanosecond_precision_timestamp(self):
        """Test validation with nanosecond precision in validity timestamp."""
        validator = IPNSValidator()
        keypair = create_ed25519_keypair()
        private_key = keypair.private_key

        peer_id = ID.from_pubkey(private_key.get_public_key())
        name_hash = peer_id.to_bytes().hex()
        key = f"/ipns/{name_hash}"

        # Create validity with nanosecond precision (like in spec)
        validity = "2125-01-01T00:00:00.000000001Z"
        validity_bytes = validity.encode("ascii")

        cbor_data = {
            "Sequence": 1,
            "TTL": 300_000_000_000,
            "Validity": validity_bytes,
            "ValidityType": 0,
            "Value": b"/ipfs/QmTest",
        }
        data_bytes = cbor2.dumps(cbor_data, canonical=True)

        signature = private_key.sign(SIGNATURE_PREFIX + data_bytes)

        entry = IpnsEntry()
        entry.value = b"/ipfs/QmTest"
        entry.validityType = IpnsEntry.ValidityType.EOL
        entry.validity = validity_bytes
        entry.sequence = 1
        entry.ttl = 300_000_000_000
        entry.signatureV2 = signature
        entry.data = data_bytes

        # Should validate successfully (far future date)
        validator.validate(key, entry.SerializeToString())


class TestIPNSValidatorIntegration:
    """Integration tests with DHT."""

    @pytest.mark.trio
    async def test_ipns_validator_registered_in_dht(self):
        """Test that IPNSValidator is properly registered in DHT by default."""
        from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
        from libp2p.records.ipns import IPNSValidator
        from tests.utils.factories import host_pair_factory

        async with host_pair_factory() as (host_a, host_b):
            dht = KadDHT(host_a, mode=DHTMode.SERVER)
            dht.apply_fallbacks()

            # Check that IPNS validator is registered
            if dht.validator is not None and hasattr(dht.validator, "_validators"):
                assert "ipns" in dht.validator._validators
                assert isinstance(dht.validator._validators["ipns"], IPNSValidator)
                assert "pk" in dht.validator._validators


class TestIPNSSpecTestVectors:
    """
    Official IPNS test vectors from the IPNS Record Specification.
    https://specs.ipfs.tech/ipns/ipns-record/#test-vectors
    """

    FIXTURES_DIR = Path(__file__).parent / "fixtures"

    # IPNS names (CIDv1 with libp2p-key multicodec) from the spec
    from typing import Any, TypedDict

    class TestVector(TypedDict, total=False):
        file: str
        name: str
        valid: bool
        error: str
        value: str

    TEST_VECTORS: dict[str, TestVector] = {
        # V1-only record -> invalid (missing signatureV2)
        "v1_only": {
            "file": "v1_only.ipns-record",
            "name": "k51qzi5uqu5dm4tm0wt8srkg9h9suud4wuiwjimndrkydqm81cqtlb5ak6p7ku",
            "valid": False,
            "error": "signatureV2",
        },
        # V1+V2 with both signatures valid -> valid
        "v1_v2_valid": {
            "file": "v1_v2_valid.ipns-record",
            "name": "k51qzi5uqu5dlkw8pxuw9qmqayfdeh4kfebhmreauqdc6a7c3y7d5i9fi8mk9w",
            "valid": True,
            "value": "/ipfs/bafkqaddwgevxmmraojswg33smq",
        },
        # V1+V2 but V1 value differs from V2 CBOR -> invalid
        "v1_v2_broken_v1_value": {
            "file": "v1_v2_broken_v1_value.ipns-record",
            "name": "k51qzi5uqu5dlmit2tuwdvnx4sbnyqgmvbxftl0eo3f33wwtb9gr7yozae9kpw",
            "valid": False,
            "error": "V1 value doesn't match",
        },
        # V1+V2 but only signatureV1 is valid -> invalid
        "v1_v2_broken_sig_v2": {
            "file": "v1_v2_broken_sig_v2.ipns-record",
            "name": "k51qzi5uqu5diamp7qnnvs1p1gzmku3eijkeijs3418j23j077zrkok63xdm8c",
            "valid": False,
            "error": "signatureV2|Signature",
        },
        # V1+V2 but only signatureV2 is valid -> valid (V1 sig ignored)
        "v1_v2_broken_sig_v1": {
            "file": "v1_v2_broken_sig_v1.ipns-record",
            "name": "k51qzi5uqu5dilgf7gorsh9vcqqq4myo6jd4zmqkuy9pxyxi5fua3uf7axph4y",
            "valid": True,
            "value": "/ipfs/bafkqahtwgevxmmrao5uxi2bamjzg623fnyqhg2lhnzqxi5lsmuqhmmi",
        },
        # V2-only (no V1 fields) -> valid
        "v2_only": {
            "file": "v2_only.ipns-record",
            "name": "k51qzi5uqu5dit2ku9mutlfgwyz8u730on38kd10m97m36bjt66my99hb6103f",
            "valid": True,
        },
    }

    @pytest.fixture
    def validator(self) -> IPNSValidator:
        return IPNSValidator()

    def _ipns_name_to_key(self, name: str) -> str:
        """
        Convert CIDv1 IPNS name to the /ipns/<multihash> key format.

        IPNS names are CIDv1 with libp2p-key multicodec (0x72).
        We need to extract the multihash and convert to hex for our key format.
        """
        # Decode base36 CID (k prefix indicates base36)
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
        name_lower = name.lower()

        # Remove 'k' prefix if present (base36 indicator)
        if name_lower.startswith("k"):
            name_lower = name_lower[1:]

        # Decode base36
        num = 0
        for char in name_lower:
            num = num * 36 + alphabet.index(char)

        # Convert to bytes
        cid_bytes = []
        while num > 0:
            cid_bytes.append(num & 0xFF)
            num >>= 8
        cid_bytes = bytes(reversed(cid_bytes))

        # CIDv1 format: <version><codec><multihash>
        # version = 0x01, codec = 0x72 (libp2p-key)
        # Skip version (varint) and codec (varint) to get multihash
        # For these test vectors, version=1 and codec=0x72 are single bytes
        if len(cid_bytes) > 2:
            multihash_bytes = cid_bytes[2:]  # Skip version and codec
            return "/ipns/" + multihash_bytes.hex()

        return "/ipns/" + cid_bytes.hex()

    def _load_fixture(self, filename: str) -> bytes:
        """Load a test fixture file."""
        path = self.FIXTURES_DIR / filename
        return path.read_bytes()

    def test_v1_only_invalid(self, validator):
        """V1-only record should be rejected (missing signatureV2)."""
        vector = self.TEST_VECTORS["v1_only"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        with pytest.raises(InvalidRecordType, match=vector["error"]):
            validator.validate(key, record_bytes)

    def test_v1_v2_valid(self, validator):
        """V1+V2 record with both signatures valid should pass."""
        vector = self.TEST_VECTORS["v1_v2_valid"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        # Should not raise
        validator.validate(key, record_bytes)

        # Verify the value
        entry = IpnsEntry()
        entry.ParseFromString(record_bytes)
        cbor_data = cbor2.loads(entry.data)
        value = cbor_data.get("Value", b"")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        assert value == vector["value"]

    def test_v1_v2_broken_v1_value_invalid(self, validator):
        """V1+V2 record with mismatched V1 value should be rejected."""
        vector = self.TEST_VECTORS["v1_v2_broken_v1_value"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        with pytest.raises(InvalidRecordType, match=vector["error"]):
            validator.validate(key, record_bytes)

    def test_v1_v2_broken_sig_v2_invalid(self, validator):
        """V1+V2 record with only signatureV1 valid should be rejected."""
        vector = self.TEST_VECTORS["v1_v2_broken_sig_v2"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        with pytest.raises(InvalidRecordType, match=vector["error"]):
            validator.validate(key, record_bytes)

    def test_v1_v2_broken_sig_v1_valid(self, validator):
        """V1+V2 record with only signatureV2 valid should pass (V1 ignored)."""
        vector = self.TEST_VECTORS["v1_v2_broken_sig_v1"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        # Should not raise - signatureV1 is ignored per spec
        validator.validate(key, record_bytes)

    def test_v2_only_valid(self, validator):
        """V2-only record (no V1 fields) should pass."""
        vector = self.TEST_VECTORS["v2_only"]
        record_bytes = self._load_fixture(vector["file"])
        key = self._ipns_name_to_key(vector["name"])

        # Should not raise
        validator.validate(key, record_bytes)
