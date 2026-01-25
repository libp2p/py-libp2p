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

# Constants from the IPNS specification
MAX_RECORD_SIZE = 10 * 1024  # 10 KiB maximum record size
SIGNATURE_PREFIX = b"ipns-signature:"  # Prefix for V2 signature verification
VALIDITY_TYPE_EOL = 0  # End of Life validity type

# Identity multihash code (used for inlined Ed25519 keys)
IDENTITY_MULTIHASH_CODE = 0x00


class IPNSValidator(Validator):
    """
    Validator for IPNS records following the IPNS Record Specification.

    IPNS (InterPlanetary Naming System) provides cryptographically verifiable,
    mutable pointers to content-addressed data in IPFS.

    This validator implements the verification steps outlined in:
    https://specs.ipfs.tech/ipns/ipns-record/#record-verification
    """

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate an IPNS record.

        Verification steps (per IPNS spec):
        1. Check record size <= 10 KiB
        2. Parse protobuf and confirm signatureV2 and data are present
        3. Extract public key (from record or inlined in IPNS name)
        4. Deserialize data as DAG-CBOR
        5. Verify signatureV2 against "ipns-signature:" + CBOR data
        6. Validate V1 fields match V2 CBOR (if present)
        7. Check validity (expiration time)

        Args:
            key: The IPNS key (e.g., "/ipns/<multihash>")
            value: The serialized IpnsEntry protobuf

        Raises:
            InvalidRecordType: If validation fails at any step

        """
        # Step 0: Validate namespace
        ns, name_hash = split_key(key)
        if ns != "ipns":
            raise InvalidRecordType("namespace not 'ipns'")

        # Step 1: Check size limit
        if len(value) > MAX_RECORD_SIZE:
            raise InvalidRecordType(
                f"IPNS record exceeds size limit: {len(value)} > {MAX_RECORD_SIZE}"
            )

        # Step 2: Parse protobuf
        try:
            entry = IpnsEntry()
            entry.ParseFromString(value)
        except Exception as e:
            raise InvalidRecordType(f"Failed to parse IPNS record: {e}")

        # Step 3: Check required V2 fields
        if not entry.signatureV2:
            raise InvalidRecordType("Missing signatureV2 (required for V2 records)")
        if not entry.data:
            raise InvalidRecordType("Missing data field (required for V2 records)")

        # Step 4: Extract public key
        pubkey = self._extract_public_key(entry, name_hash)

        # Step 5: Deserialize DAG-CBOR data
        cbor_data = self._decode_cbor_data(entry.data)

        # Step 6: Verify signatureV2
        self._verify_signature(pubkey, entry.data, entry.signatureV2)

        # Step 7: Validate V1 fields match V2 CBOR (if present)
        self._validate_v1_v2_consistency(entry, cbor_data)

        # Step 8: Check validity (expiration)
        self._check_validity(cbor_data)

        logger.debug("IPNS record validation successful for key: %s", key)

    def _extract_public_key(self, entry: IpnsEntry, name_hash: str) -> PublicKey:
        """
        Extract public key from record or inlined in IPNS name.

        For Ed25519 keys, the public key is typically inlined in the IPNS name
        using an identity multihash. For larger keys like RSA, the public key
        is stored in the pubKey field of the record.

        Args:
            entry: The parsed IpnsEntry protobuf
            name_hash: The hex-encoded hash portion of the IPNS key

        Returns:
            The extracted public key

        Raises:
            InvalidRecordType: If public key cannot be extracted or doesn't match

        """
        from libp2p.peer.id import ID

        # If pubKey is in the record (for RSA keys)
        if entry.pubKey:
            try:
                pubkey = unmarshal_public_key(entry.pubKey)
                # Verify it matches the IPNS name
                derived_id = ID.from_pubkey(pubkey)
                if derived_id.to_bytes().hex() != name_hash:
                    raise InvalidRecordType("Public key does not match IPNS name")
                return pubkey
            except InvalidRecordType:
                raise
            except Exception as e:
                raise InvalidRecordType(f"Failed to unmarshal pubKey: {e}")

        # Otherwise, try to extract from inlined identity multihash
        try:
            name_bytes = bytes.fromhex(name_hash)
            mh = multihash.decode(name_bytes)

            # Check if it's an identity multihash (Ed25519 inlined)
            if mh.code == IDENTITY_MULTIHASH_CODE:
                return unmarshal_public_key(mh.digest)
            else:
                raise InvalidRecordType(
                    "Public key not in record and not inlined in name "
                    f"(multihash code: {mh.code})"
                )
        except InvalidRecordType:
            raise
        except Exception as e:
            raise InvalidRecordType(f"Failed to extract public key from name: {e}")

    def _decode_cbor_data(self, data: bytes) -> dict:
        """
        Decode DAG-CBOR data from the record.

        Args:
            data: Raw CBOR bytes from IpnsEntry.data

        Returns:
            Decoded CBOR data as a dictionary

        Raises:
            InvalidRecordType: If CBOR decoding fails

        """
        try:
            import cbor2

            return cbor2.loads(data)
        except ImportError:
            raise InvalidRecordType(
                "cbor2 package required for IPNS validation. "
                "Install with: pip install cbor2"
            )
        except Exception as e:
            raise InvalidRecordType(f"Failed to decode DAG-CBOR data: {e}")

    def _verify_signature(
        self, pubkey: PublicKey, data: bytes, signature: bytes
    ) -> None:
        """
        Verify the V2 signature.

        The signature is over: "ipns-signature:" prefix + raw CBOR data

        Args:
            pubkey: The public key to verify with
            data: The raw CBOR data (IpnsEntry.data)
            signature: The signatureV2 bytes

        Raises:
            InvalidRecordType: If signature verification fails

        """
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
        Ensure V1 protobuf fields match V2 CBOR data (if present).

        This prevents tampering where an attacker might modify legacy V1 fields
        while keeping a valid V2 signature.

        Args:
            entry: The parsed IpnsEntry protobuf
            cbor_data: The decoded CBOR data

        Raises:
            InvalidRecordType: If V1 and V2 fields don't match

        """
        # Check value field
        if entry.value:
            cbor_value = cbor_data.get("Value", b"")
            if isinstance(cbor_value, str):
                cbor_value = cbor_value.encode("utf-8")
            if entry.value != cbor_value:
                raise InvalidRecordType("V1 value doesn't match V2 CBOR Value")

        # Check validity field
        if entry.validity:
            cbor_validity = cbor_data.get("Validity", b"")
            if isinstance(cbor_validity, str):
                cbor_validity = cbor_validity.encode("utf-8")
            if entry.validity != cbor_validity:
                raise InvalidRecordType("V1 validity doesn't match V2 CBOR Validity")

        # Check validityType field
        if entry.validityType != 0 or "ValidityType" in cbor_data:
            cbor_validity_type = cbor_data.get("ValidityType", 0)
            if entry.validityType != cbor_validity_type:
                raise InvalidRecordType(
                    "V1 validityType doesn't match V2 CBOR ValidityType"
                )

        # Check sequence field
        if entry.sequence != 0 or "Sequence" in cbor_data:
            cbor_sequence = cbor_data.get("Sequence", 0)
            if entry.sequence != cbor_sequence:
                raise InvalidRecordType("V1 sequence doesn't match V2 CBOR Sequence")

        # Check ttl field
        if entry.ttl != 0 or "TTL" in cbor_data:
            cbor_ttl = cbor_data.get("TTL", 0)
            if entry.ttl != cbor_ttl:
                raise InvalidRecordType("V1 ttl doesn't match V2 CBOR TTL")

    def _check_validity(self, cbor_data: dict) -> None:
        """
        Check if record has expired based on ValidityType.

        For ValidityType=0 (EOL), the Validity field contains an RFC3339
        timestamp indicating when the record expires.

        Args:
            cbor_data: The decoded CBOR data

        Raises:
            InvalidRecordType: If record has expired or validity check fails

        """
        validity_type = cbor_data.get("ValidityType", VALIDITY_TYPE_EOL)

        if validity_type == VALIDITY_TYPE_EOL:
            validity = cbor_data.get("Validity")
            if not validity:
                raise InvalidRecordType("Missing Validity field in CBOR data")

            try:
                # Parse RFC3339 timestamp
                if isinstance(validity, bytes):
                    validity = validity.decode("ascii")

                # Handle various RFC3339 formats
                # Replace 'Z' with '+00:00' for fromisoformat compatibility
                validity_str = validity.replace("Z", "+00:00")

                # Python's fromisoformat doesn't handle nanoseconds well,
                # so we truncate to microseconds if needed
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
        Select the best IPNS record from a list of candidates.

        Selection criteria (per IPNS spec):
        1. Higher sequence number wins
        2. If equal sequence, longer validity (later expiration) wins

        Args:
            key: The IPNS key
            values: List of serialized IpnsEntry records

        Returns:
            Index of the best record in the values list

        Raises:
            ValueError: If values list is empty

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

                # Get sequence from CBOR data (preferred) or V1 field
                if entry.data:
                    cbor_data = self._decode_cbor_data(entry.data)
                    seq = cbor_data.get("Sequence", 0)
                    validity = cbor_data.get("Validity", b"")
                else:
                    seq = entry.sequence
                    validity = entry.validity

                # Compare: higher sequence wins
                if seq > best_seq:
                    best_idx = i
                    best_seq = seq
                    best_validity = validity
                elif seq == best_seq:
                    # Equal sequence: longer validity (later expiration) wins
                    if validity and (not best_validity or validity > best_validity):
                        best_idx = i
                        best_validity = validity

            except Exception as e:
                # Skip invalid records during selection
                logger.debug("Skipping invalid record during selection: %s", e)
                continue

        return best_idx
