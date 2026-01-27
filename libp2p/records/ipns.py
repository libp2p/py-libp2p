from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING

import multihash

from libp2p.records.pb.ipns_pb2 import IpnsEntry
from libp2p.records.pubkey import unmarshal_public_key
from libp2p.records.utils import InvalidRecordType, split_key
from libp2p.records.validator import Validator

if TYPE_CHECKING:
    from libp2p.crypto.keys import PublicKey

logger = logging.getLogger(__name__)

# IPNS spec constants: https://specs.ipfs.tech/ipns/ipns-record/
MAX_RECORD_SIZE = 10 * 1024  # 10 KiB per spec section 4.2.1
SIGNATURE_PREFIX = b"ipns-signature:"  # V2 signature prefix
VALIDITY_TYPE_EOL = 0  # End of Life - the only supported validity type
IDENTITY_MULTIHASH_CODE = 0x00  # For Ed25519 keys inlined in IPNS name


class IPNSValidator(Validator):
    """
    IPNS record validator per https://specs.ipfs.tech/ipns/ipns-record/

    IPNS provides mutable pointers to content-addressed data. Records are
    signed with Ed25519 (default) or RSA keys and validated using the V2
    signature format with DAG-CBOR encoded data.
    """

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate an IPNS record per spec section 5.3 (Record Verification).

        Steps:
        1. Check record size <= 10 KiB
        2. Confirm signatureV2 and data fields are present
        3. Extract public key from record or IPNS name
        4. Deserialize data as DAG-CBOR
        5. Verify signatureV2 against "ipns-signature:" + CBOR data
        6. If V1 fields present, confirm they match CBOR values
        7. Check validity expiration (RFC3339 timestamp)

        Raises:
            InvalidRecordType: If any validation step fails

        """
        ns, name_hash = split_key(key)
        if ns != "ipns":
            raise InvalidRecordType("namespace not 'ipns'")

        if len(value) > MAX_RECORD_SIZE:
            raise InvalidRecordType(
                f"IPNS record exceeds size limit: {len(value)} > {MAX_RECORD_SIZE}"
            )

        try:
            entry = IpnsEntry()
            entry.ParseFromString(value)
        except Exception as e:
            raise InvalidRecordType(f"Failed to parse IPNS record: {e}")

        if not entry.signatureV2:
            raise InvalidRecordType("Missing signatureV2 (required for V2 records)")
        if not entry.data:
            raise InvalidRecordType("Missing data field (required for V2 records)")

        pubkey = self._extract_public_key(entry, name_hash)
        cbor_data = self._decode_cbor_data(entry.data)
        self._verify_signature(pubkey, entry.data, entry.signatureV2)
        self._validate_v1_v2_consistency(entry, cbor_data)
        self._check_validity(cbor_data)

        logger.debug("IPNS record validated: %s", key)

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

    def _decode_cbor_data(self, data: bytes) -> dict:
        """Decode DAG-CBOR data from IpnsEntry.data field."""
        try:
            import cbor2
            return cbor2.loads(data)
        except ImportError:
            raise InvalidRecordType(
                "cbor2 package required for IPNS validation"
            )
        except Exception as e:
            raise InvalidRecordType(f"Failed to decode DAG-CBOR data: {e}")

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

    def _validate_v1_v2_consistency(self, entry: IpnsEntry, cbor_data: dict) -> None:
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

    def _check_validity(self, cbor_data: dict) -> None:
        """
        Check record expiration per ValidityType=0 (EOL).

        Validity field contains RFC3339 timestamp with nanosecond precision.
        """
        validity_type = cbor_data.get("ValidityType", VALIDITY_TYPE_EOL)

        if validity_type == VALIDITY_TYPE_EOL:
            validity = cbor_data.get("Validity")
            if not validity:
                raise InvalidRecordType("Missing Validity field in CBOR data")

            try:
                if isinstance(validity, bytes):
                    validity = validity.decode("ascii")

                # Convert RFC3339 'Z' suffix to '+00:00' for fromisoformat
                validity_str = validity.replace("Z", "+00:00")

                # Truncate nanoseconds to microseconds (Python limitation)
                if "." in validity_str:
                    # Split at the decimal point
                    base, frac_and_tz = validity_str.split(".", 1)
                    # Find where the fractional seconds end
                    for i, c in enumerate(frac_and_tz):
                        if not c.isdigit():
                            frac = frac_and_tz[:i]
                            tz = frac_and_tz[i:]
                            break
                    else:
                        frac = frac_and_tz
                        tz = ""
                    # Truncate to 6 digits (microseconds)
                    frac = frac[:6].ljust(6, "0")
                    validity_str = f"{base}.{frac}{tz}"

                expiry = datetime.fromisoformat(validity_str)

                # Ensure timezone-aware comparison
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)

                if now > expiry:
                    raise InvalidRecordType(f"IPNS record expired at {validity}")

            except InvalidRecordType:
                raise
            except Exception as e:
                raise InvalidRecordType(f"Invalid validity timestamp: {e}")
        else:
            raise InvalidRecordType(f"Unknown ValidityType: {validity_type}")

    def select(self, key: str, values: list[bytes]) -> int:
        """
        Select the best IPNS record from candidates.

        Selection: higher sequence wins; tie-breaker is longer validity.
        """
        if not values:
            raise ValueError("Cannot select from empty value list")

        best_idx = 0
        best_seq = -1
        best_validity: bytes | str | None = None

        for i, value in enumerate(values):
            try:
                entry = IpnsEntry()
                entry.ParseFromString(value)

                if entry.data:
                    cbor_data = self._decode_cbor_data(entry.data)
                    seq = cbor_data.get("Sequence", 0)
                    validity = cbor_data.get("Validity", b"")
                else:
                    seq = entry.sequence
                    validity = entry.validity

                if seq > best_seq:
                    best_idx = i
                    best_seq = seq
                    best_validity = validity
                elif seq == best_seq:
                    if validity and (not best_validity or validity > best_validity):
                        best_idx = i
                        best_validity = validity

            except Exception as e:
                logger.debug("Skipping invalid record during selection: %s", e)
                continue

        return best_idx
