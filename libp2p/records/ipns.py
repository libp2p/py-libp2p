from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
import logging
import re
from typing import TYPE_CHECKING, Any

import multihash

from libp2p.records.pb.ipns_pb2 import IpnsEntry
from libp2p.records.pubkey import unmarshal_public_key
from libp2p.records.utils import InvalidRecordType, split_key
from libp2p.records.validator import Validator

if TYPE_CHECKING:
    from libp2p.crypto.keys import PublicKey

logger = logging.getLogger(__name__)

# IPNS Spec Constants
# Reference: https://specs.ipfs.tech/ipns/ipns-record/

# Record size limit per spec section 4.2.1
MAX_RECORD_SIZE = 10 * 1024  # 10 KiB

# V2 signature prefix per spec section 4.2.2
SIGNATURE_PREFIX = b"ipns-signature:"

# Validity types per spec section 4.2.1
VALIDITY_TYPE_EOL = 0  # End of Life - the only supported validity type

# Multihash codes for key extraction
IDENTITY_MULTIHASH_CODE = 0x00  # For Ed25519 keys inlined in IPNS name

# CBOR field names (case-sensitive per DAG-CBOR spec)
CBOR_FIELD_VALUE = "Value"
CBOR_FIELD_VALIDITY = "Validity"
CBOR_FIELD_VALIDITY_TYPE = "ValidityType"
CBOR_FIELD_SEQUENCE = "Sequence"
CBOR_FIELD_TTL = "TTL"

# Required CBOR fields per IPNS spec
REQUIRED_CBOR_FIELDS = frozenset(
    {
        CBOR_FIELD_VALUE,
        CBOR_FIELD_VALIDITY,
        CBOR_FIELD_VALIDITY_TYPE,
        CBOR_FIELD_SEQUENCE,
    }
)

# Valid IPNS value prefixes per spec
VALID_VALUE_PREFIXES = (b"/ipfs/", b"/ipns/", b"/dnslink/")

# Maximum sequence number (uint64 max)
MAX_SEQUENCE = 2**64 - 1

# Maximum TTL value (uint64 max, in nanoseconds)
MAX_TTL = 2**64 - 1

# RFC3339 timestamp pattern for validation
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$"
)


class ValidityType(IntEnum):
    """IPNS record validity types per spec."""

    EOL = 0


@dataclass(frozen=True)
class ParsedIPNSRecord:
    """
    Parsed and validated IPNS record data.

    This provides a structured view of the IPNS record after validation,
    useful for debugging and inspection.
    """

    value: bytes
    validity: datetime
    validity_type: ValidityType
    sequence: int
    ttl: int | None
    public_key_inlined: bool
    has_v1_fields: bool


class IPNSValidator(Validator):
    """
    IPNS record validator per https://specs.ipfs.tech/ipns/ipns-record/

    IPNS provides mutable pointers to content-addressed data. Records are
    signed with Ed25519 (default) or RSA keys and validated using the V2
    signature format with DAG-CBOR encoded data.

    Features:
    - Full V2 record validation with DAG-CBOR
    - Backward compatibility with V1 fields
    - Public key extraction from name or record
    - RFC3339 timestamp validation with nanosecond support
    - Sequence-based record selection
    - Comprehensive error messages for debugging
    """

    def __init__(self, *, check_expiration: bool = True) -> None:
        """
        Initialize the IPNS validator.

        Args:
            check_expiration: Whether to check if records are expired.
                             Set to False for testing or historical analysis.

        """
        self._check_expiration = check_expiration

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate an IPNS record per spec section 5.3 (Record Verification).

        Validation steps:
        1. Verify namespace is 'ipns'
        2. Check record size <= 10 KiB
        3. Parse protobuf and verify required V2 fields (signatureV2, data)
        4. Extract public key from record or IPNS name
        5. Decode and validate DAG-CBOR data structure
        6. Verify signatureV2 against "ipns-signature:" + CBOR data
        7. Validate CBOR field types and values
        8. If V1 fields present, confirm they match CBOR values
        9. Check validity expiration (RFC3339 timestamp)

        Args:
            key: The IPNS key in format "/ipns/<multihash>"
            value: The serialized IpnsEntry protobuf bytes

        Raises:
            InvalidRecordType: If any validation step fails

        """
        ns, name_hash = split_key(key)
        if ns != "ipns":
            raise InvalidRecordType(f"Invalid namespace: expected 'ipns', got '{ns}'")

        if len(value) > MAX_RECORD_SIZE:
            raise InvalidRecordType(
                f"IPNS record exceeds size limit: {len(value)} > "
                f"{MAX_RECORD_SIZE} bytes"
            )

        if len(value) == 0:
            raise InvalidRecordType("IPNS record is empty")

        try:
            entry = IpnsEntry()
            entry.ParseFromString(value)
        except Exception as e:
            raise InvalidRecordType(f"Failed to parse IPNS record protobuf: {e}")

        # Verify required V2 fields
        if not entry.signatureV2:
            raise InvalidRecordType(
                "Missing signatureV2 field (required for V2 records)"
            )
        if not entry.data:
            raise InvalidRecordType("Missing data field (required for V2 records)")

        pubkey = self._extract_public_key(entry, name_hash)

        cbor_data = self._decode_cbor_data(entry.data)

        self._validate_cbor_structure(cbor_data)

        self._verify_signature(pubkey, entry.data, entry.signatureV2)

        self._validate_v1_v2_consistency(entry, cbor_data)

        self._check_validity(cbor_data)

        logger.debug("IPNS record validated successfully: %s", key)

    def validate_with_details(self, key: str, value: bytes) -> ParsedIPNSRecord:
        """
        Validate an IPNS record and return parsed details.

        This is useful for debugging or when you need information about
        the validated record.

        Args:
            key: The IPNS key in format "/ipns/<multihash>"
            value: The serialized IpnsEntry protobuf bytes

        Returns:
            ParsedIPNSRecord with the validated record details

        Raises:
            InvalidRecordType: If validation fails

        """
        self.validate(key, value)

        entry = IpnsEntry()
        entry.ParseFromString(value)
        cbor_data = self._decode_cbor_data(entry.data)

        validity_bytes = cbor_data.get(CBOR_FIELD_VALIDITY, b"")
        if isinstance(validity_bytes, bytes):
            validity_str = validity_bytes.decode("ascii")
        else:
            validity_str = validity_bytes
        validity_dt = self._parse_rfc3339(validity_str)

        _, name_hash = split_key(key)
        name_bytes = bytes.fromhex(name_hash)
        mh = multihash.decode(name_bytes)
        public_key_inlined = mh.func == IDENTITY_MULTIHASH_CODE

        has_v1_fields = bool(
            entry.value or entry.validity or entry.sequence or entry.ttl
        )

        return ParsedIPNSRecord(
            value=cbor_data.get(CBOR_FIELD_VALUE, b""),
            validity=validity_dt,
            validity_type=ValidityType(
                cbor_data.get(CBOR_FIELD_VALIDITY_TYPE, VALIDITY_TYPE_EOL)
            ),
            sequence=cbor_data.get(CBOR_FIELD_SEQUENCE, 0),
            ttl=cbor_data.get(CBOR_FIELD_TTL),
            public_key_inlined=public_key_inlined,
            has_v1_fields=has_v1_fields,
        )

    def _extract_public_key(self, entry: IpnsEntry, name_hash: str) -> PublicKey:
        """
        Extract public key from record's pubKey field or from IPNS name.

        Ed25519 keys are typically inlined in the IPNS name using identity
        multihash. RSA and other large keys are stored in pubKey field.
        """
        from libp2p.peer.id import ID

        if entry.pubKey:
            try:
                pubkey = unmarshal_public_key(entry.pubKey)
                derived_id = ID.from_pubkey(pubkey)
                if derived_id.to_bytes().hex() != name_hash:
                    raise InvalidRecordType("Public key does not match IPNS name")
                return pubkey
            except InvalidRecordType:
                raise
            except Exception as e:
                raise InvalidRecordType(f"Failed to unmarshal pubKey: {e}")

        # Try extracting from identity multihash (inlined Ed25519)
        try:
            name_bytes = bytes.fromhex(name_hash)
            mh = multihash.decode(name_bytes)

            if mh.func == IDENTITY_MULTIHASH_CODE:
                return unmarshal_public_key(mh.digest)
            else:
                raise InvalidRecordType(
                    f"Public key not inlined in name (multihash code: {mh.func})"
                )
        except InvalidRecordType:
            raise
        except Exception as e:
            raise InvalidRecordType(f"Failed to extract public key from name: {e}")

    def _decode_cbor_data(self, data: bytes) -> dict[str, Any]:
        """
        Decode DAG-CBOR data from IpnsEntry.data field.

        DAG-CBOR is a subset of CBOR with deterministic encoding requirements.
        """
        if len(data) == 0:
            raise InvalidRecordType("CBOR data field is empty")

        try:
            import cbor2

            decoded = cbor2.loads(data)
            if not isinstance(decoded, dict):
                raise InvalidRecordType(
                    f"CBOR data must be a map, got {type(decoded).__name__}"
                )
            return decoded
        except ImportError:
            raise InvalidRecordType("cbor2 package required for IPNS validation")
        except InvalidRecordType:
            raise
        except Exception as e:
            raise InvalidRecordType(f"Failed to decode DAG-CBOR data: {e}")

    def _validate_cbor_structure(self, cbor_data: dict[str, Any]) -> None:
        """
        Validate CBOR data structure and field types per IPNS spec.

        Required fields: Value, Validity, ValidityType, Sequence
        Optional fields: TTL

        Field types:
        - Value: bytes (content path)
        - Validity: bytes (RFC3339 timestamp)
        - ValidityType: int (0 = EOL)
        - Sequence: int (uint64)
        - TTL: int (optional, nanoseconds)
        """
        for field in REQUIRED_CBOR_FIELDS:
            if field not in cbor_data:
                raise InvalidRecordType(f"Missing required CBOR field: '{field}'")

        value = cbor_data[CBOR_FIELD_VALUE]
        if not isinstance(value, (bytes, str)):
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_VALUE}' must be bytes or str, "
                f"got {type(value).__name__}"
            )
        value_bytes = value if isinstance(value, bytes) else value.encode("utf-8")
        if len(value_bytes) == 0:
            raise InvalidRecordType(f"CBOR '{CBOR_FIELD_VALUE}' cannot be empty")

        if not any(value_bytes.startswith(prefix) for prefix in VALID_VALUE_PREFIXES):
            logger.warning(
                "IPNS value doesn't start with expected prefix (/ipfs/, /ipns/, "
                "/dnslink/): %s",
                value_bytes[:50],
            )

        validity = cbor_data[CBOR_FIELD_VALIDITY]
        if not isinstance(validity, (bytes, str)):
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_VALIDITY}' must be bytes or str, "
                f"got {type(validity).__name__}"
            )
        validity_str = (
            validity.decode("ascii") if isinstance(validity, bytes) else validity
        )
        if not RFC3339_PATTERN.match(validity_str):
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_VALIDITY}' is not a valid RFC3339 timestamp: "
                f"{validity_str}"
            )

        validity_type = cbor_data[CBOR_FIELD_VALIDITY_TYPE]
        if not isinstance(validity_type, int):
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_VALIDITY_TYPE}' must be int, "
                f"got {type(validity_type).__name__}"
            )
        if validity_type != VALIDITY_TYPE_EOL:
            raise InvalidRecordType(
                f"Unsupported ValidityType: {validity_type} (only EOL=0 is supported)"
            )

        sequence = cbor_data[CBOR_FIELD_SEQUENCE]
        if not isinstance(sequence, int):
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_SEQUENCE}' must be int, "
                f"got {type(sequence).__name__}"
            )
        if sequence < 0:
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_SEQUENCE}' must be non-negative, got {sequence}"
            )
        if sequence > MAX_SEQUENCE:
            raise InvalidRecordType(
                f"CBOR '{CBOR_FIELD_SEQUENCE}' exceeds maximum uint64 value"
            )

        # Validate optional TTL field
        if CBOR_FIELD_TTL in cbor_data:
            ttl = cbor_data[CBOR_FIELD_TTL]
            if not isinstance(ttl, int):
                raise InvalidRecordType(
                    f"CBOR '{CBOR_FIELD_TTL}' must be int, got {type(ttl).__name__}"
                )
            if ttl < 0:
                raise InvalidRecordType(
                    f"CBOR '{CBOR_FIELD_TTL}' must be non-negative, got {ttl}"
                )
            if ttl > MAX_TTL:
                raise InvalidRecordType(
                    f"CBOR '{CBOR_FIELD_TTL}' exceeds maximum uint64 value"
                )

    def _verify_signature(
        self, pubkey: PublicKey, data: bytes, signature: bytes
    ) -> None:
        """Verify signatureV2 over "ipns-signature:" + CBOR data."""
        signature_payload = SIGNATURE_PREFIX + data

        try:
            if not pubkey.verify(signature_payload, signature):
                raise InvalidRecordType("Invalid signatureV2: verification failed")
        except InvalidRecordType:
            raise
        except Exception as e:
            raise InvalidRecordType(f"Signature verification error: {e}")

    def _validate_v1_v2_consistency(
        self, entry: IpnsEntry, cbor_data: dict[str, Any]
    ) -> None:
        """
        Ensure legacy V1 fields match signed V2 CBOR data when present.

        Per the spec, V2-only records are valid without V1 fields. When V1 fields
        are present (non-default values), they must match the signed CBOR data
        to prevent tampering. signatureV1 is never used for verification.
        """
        # Check value if V1 has it set (non-empty bytes)
        if entry.value:
            cbor_value = cbor_data.get("Value", b"")
            if isinstance(cbor_value, str):
                cbor_value = cbor_value.encode("utf-8")
            if entry.value != cbor_value:
                raise InvalidRecordType("V1 value doesn't match V2 CBOR Value")

        # Check validity if V1 has it set
        if entry.validity:
            cbor_validity = cbor_data.get("Validity", b"")
            if isinstance(cbor_validity, str):
                cbor_validity = cbor_validity.encode("utf-8")
            if entry.validity != cbor_validity:
                raise InvalidRecordType("V1 validity doesn't match V2 CBOR Validity")

        # Check sequence if V1 has non-zero value (0 is both valid and default)
        if entry.sequence != 0 and entry.sequence != cbor_data.get("Sequence", 0):
            raise InvalidRecordType("V1 sequence doesn't match V2 CBOR Sequence")

        # Check ttl if V1 has non-zero value
        if entry.ttl != 0 and entry.ttl != cbor_data.get("TTL", 0):
            raise InvalidRecordType("V1 ttl doesn't match V2 CBOR TTL")

    def _check_validity(self, cbor_data: dict[str, Any]) -> None:
        """
        Check record expiration per ValidityType=0 (EOL).

        Validity field contains RFC3339 timestamp with nanosecond precision.
        Only checks expiration if check_expiration is enabled.
        """
        if not self._check_expiration:
            return

        validity_type = cbor_data.get(CBOR_FIELD_VALIDITY_TYPE, VALIDITY_TYPE_EOL)

        if validity_type == VALIDITY_TYPE_EOL:
            validity = cbor_data.get(CBOR_FIELD_VALIDITY)
            if not validity:
                raise InvalidRecordType(
                    f"Missing '{CBOR_FIELD_VALIDITY}' field in CBOR data"
                )

            try:
                if isinstance(validity, bytes):
                    validity_str = validity.decode("ascii")
                else:
                    validity_str = validity

                expiry = self._parse_rfc3339(validity_str)
                now = datetime.now(timezone.utc)

                if now > expiry:
                    time_since_expiry = now - expiry
                    raise InvalidRecordType(
                        f"IPNS record expired at {validity_str} "
                        f"({time_since_expiry} ago)"
                    )

            except InvalidRecordType:
                raise
            except Exception as e:
                raise InvalidRecordType(f"Invalid validity timestamp: {e}")
        else:
            raise InvalidRecordType(
                f"Unsupported ValidityType: {validity_type} (only EOL=0 is supported)"
            )

    def _parse_rfc3339(self, timestamp: str) -> datetime:
        """
        Parse an RFC3339 timestamp with nanosecond precision support.

        Python's datetime only supports microseconds, so we truncate
        nanoseconds to microseconds.

        Args:
            timestamp: RFC3339 formatted timestamp string

        Returns:
            Timezone-aware datetime object

        Raises:
            ValueError: If timestamp format is invalid

        """
        # Convert RFC3339 'Z' suffix to '+00:00' for fromisoformat
        validity_str = timestamp.replace("Z", "+00:00")

        # Truncate nanoseconds to microseconds (Python limitation)
        if "." in validity_str:
            # Split at the decimal point
            base, frac_and_tz = validity_str.split(".", 1)
            # Find where the fractional seconds end
            frac = ""
            tz = ""
            for i, c in enumerate(frac_and_tz):
                if not c.isdigit():
                    frac = frac_and_tz[:i]
                    tz = frac_and_tz[i:]
                    break
            else:
                frac = frac_and_tz
                tz = ""
            frac = frac[:6].ljust(6, "0")
            validity_str = f"{base}.{frac}{tz}"

        expiry = datetime.fromisoformat(validity_str)

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        return expiry

    def select(self, key: str, values: list[bytes]) -> int:
        """
        Select the best IPNS record from candidates per spec.

        Selection algorithm (per IPNS spec section 5.4):
        1. Higher sequence number wins
        2. If sequences are equal, later validity timestamp wins
        3. Invalid records are skipped

        Args:
            key: The IPNS key (used for context, not validation here)
            values: List of serialized IPNS records to compare

        Returns:
            Index of the best record in the values list

        Raises:
            ValueError: If values list is empty

        """
        if not values:
            raise ValueError("Cannot select from empty value list")

        if len(values) == 1:
            return 0

        best_idx = 0
        best_seq: int = -1
        best_validity_dt: datetime | None = None
        valid_count = 0
        for i, value in enumerate(values):
            try:
                entry = IpnsEntry()
                entry.ParseFromString(value)

                # Prefer V2 CBOR data over legacy V1 fields
                if entry.data:
                    cbor_data = self._decode_cbor_data(entry.data)
                    seq = cbor_data.get(CBOR_FIELD_SEQUENCE, 0)
                    validity_raw = cbor_data.get(CBOR_FIELD_VALIDITY, b"")
                else:
                    # Fallback to V1 fields for older records
                    seq = entry.sequence
                    validity_raw = entry.validity

                if isinstance(validity_raw, bytes):
                    validity_str = validity_raw.decode("utf-8", errors="replace")
                else:
                    validity_str = validity_raw or ""

                try:
                    validity_dt = (
                        self._parse_rfc3339(validity_str) if validity_str else None
                    )
                except Exception:
                    validity_dt = None

                valid_count += 1

                if seq > best_seq:
                    best_idx = i
                    best_seq = seq
                    best_validity_dt = validity_dt
                elif seq == best_seq and validity_dt is not None:
                    if best_validity_dt is None or validity_dt > best_validity_dt:
                        best_idx = i
                        best_validity_dt = validity_dt

            except Exception as e:
                logger.debug(
                    "Skipping invalid record at index %d during selection: %s", i, e
                )
                continue

        if valid_count == 0:
            logger.warning("No valid records found during selection, returning index 0")

        return best_idx
