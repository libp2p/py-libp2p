import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import cbor2
from libp2p.crypto.keys import PrivateKey
from libp2p.peer.id import ID
from libp2p.records.pb.ipns_pb2 import IpnsEntry

from py_ipfs_lite.exceptions import RoutingError

logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = b"ipns-signature:"


def _format_rfc3339(dt: datetime) -> str:
    # Example: 2024-05-10T12:00:00.000000000Z
    # Note: Python's isoformat uses +00:00, we want Z
    base = dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return base.replace("+00:00", "000Z")


def create_ipns_record(
    private_key: PrivateKey, value: str, sequence: int, lifetime_hours: int = 24
) -> bytes:
    """Create a signed IPNS record."""
    if not (0 <= sequence <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError(
            "Sequence number must be a 64-bit unsigned integer " "(0 to 2^64-1)"
        )
    if not (1 <= lifetime_hours <= 876000):
        raise ValueError("lifetime_hours must be between 1 and 876000 (100 years)")

    value_bytes = value.encode("utf-8")

    # Calculate validity
    now = datetime.now(timezone.utc)
    validity_dt = now + timedelta(hours=lifetime_hours)
    validity_str = _format_rfc3339(validity_dt)
    validity_bytes = validity_str.encode("utf-8")

    # Create CBOR data (V2)
    cbor_data_dict = {
        "Value": value_bytes,
        "Validity": validity_bytes,
        "ValidityType": 0,  # EOL
        "Sequence": sequence,
    }
    cbor_bytes = cbor2.dumps(cbor_data_dict)

    # Sign V2
    data_to_sign = SIGNATURE_PREFIX + cbor_bytes
    signature_v2 = private_key.sign(data_to_sign)

    # Sign V1 (legacy)
    data_v1 = value_bytes + validity_bytes + b"0"
    signature_v1 = private_key.sign(data_v1)

    entry = IpnsEntry()
    entry.value = value_bytes
    entry.validity = validity_bytes
    entry.validityType = 0
    entry.signatureV1 = signature_v1
    entry.signatureV2 = signature_v2
    entry.sequence = sequence
    entry.data = cbor_bytes

    # For Ed25519, the public key is usually inlined in the PeerID.
    # But if not, or to be safe, we can include it.
    entry.pubKey = private_key.get_public_key().serialize()

    return entry.SerializeToString()


async def publish_name(
    routing: Any,
    private_key: PrivateKey,
    peer_id: ID,
    value: str,
    sequence: int,
    lifetime_hours: int = 24,
) -> None:
    """Publish an IPNS record to the DHT."""
    record_bytes = create_ipns_record(private_key, value, sequence, lifetime_hours)
    # The DHT key for IPNS in py-libp2p must be a string.
    # We use base58 representation of the peer ID.
    dht_key = f"/ipns/{peer_id.to_base58()}"
    await routing.put_value(dht_key, record_bytes)
    logger.info(f"Published IPNS record for {peer_id.to_base58()} -> {value}")


from libp2p.crypto.serialization import deserialize_public_key


def validate_ipns_record(record_bytes: bytes, expected_peer_id: ID) -> IpnsEntry:
    """Validate the signature, expiry, and pubkey of an IPNS record."""
    entry = IpnsEntry()
    entry.ParseFromString(record_bytes)

    # 1. Check Public Key
    if not entry.pubKey:
        pubkey = expected_peer_id.extract_public_key()
        if pubkey is None:
            raise RoutingError(
                "IPNS record missing pubKey and Peer ID does not inline it"
            )
    else:
        try:
            pubkey = deserialize_public_key(entry.pubKey)
        except Exception as e:
            raise RoutingError(f"Failed to deserialize IPNS pubKey: {e}")

        if ID.from_pubkey(pubkey) != expected_peer_id:
            raise RoutingError("IPNS record pubKey does not match the expected Peer ID")

    # 2. Check Signature
    if entry.signatureV2 and entry.data:
        data_to_sign = SIGNATURE_PREFIX + entry.data
        if not pubkey.verify(data_to_sign, entry.signatureV2):
            raise RoutingError("IPNS V2 signature is invalid")

        # V2 requires that the signed CBOR data matches the raw fields!
        try:
            import cbor2

            cbor_dict = cbor2.loads(entry.data)
            if entry.value != cbor_dict.get("Value"):
                raise RoutingError("IPNS V2 signature is invalid: value mismatch")
            if entry.validity != cbor_dict.get("Validity"):
                raise RoutingError("IPNS V2 signature is invalid: validity mismatch")
            if entry.validityType != cbor_dict.get("ValidityType"):
                raise RoutingError("IPNS V2 signature is invalid: validityType mismatch")
            if entry.sequence != cbor_dict.get("Sequence"):
                raise RoutingError("IPNS V2 signature is invalid: sequence mismatch")
            if "TTL" in cbor_dict and entry.ttl != cbor_dict["TTL"]:
                raise RoutingError("IPNS V2 signature is invalid: ttl mismatch")
        except Exception as e:
            if isinstance(e, RoutingError):
                raise
            raise RoutingError(f"Failed to parse IPNS V2 CBOR data: {e}")

    elif entry.signatureV1:
        data_to_sign = (
            entry.value + entry.validity + str(entry.validityType).encode("utf-8")
        )
        if not pubkey.verify(data_to_sign, entry.signatureV1):
            raise RoutingError("IPNS V1 signature is invalid")
    else:
        raise RoutingError("IPNS record is missing signatures")

    # 3. Check Expiry
    validity_str = entry.validity.decode("utf-8")
    if validity_str.endswith("Z"):
        validity_str = validity_str[:-1] + "+00:00"
    if "." in validity_str:
        base, frac_tz = validity_str.split(".", 1)
        if "+" in frac_tz:
            frac, tz = frac_tz.split("+", 1)
            tz = "+" + tz
        elif "-" in frac_tz:
            frac, tz = frac_tz.split("-", 1)
            tz = "-" + tz
        else:
            frac = frac_tz
            tz = ""
        frac = frac[:6]
        validity_str = f"{base}.{frac}{tz}"

    try:
        validity_dt = datetime.fromisoformat(validity_str)
        if validity_dt < datetime.now(timezone.utc):
            raise RoutingError("IPNS record has expired")
    except (ValueError, TypeError):
        logger.warning(
            f"Failed to parse IPNS validity date: {entry.validity.decode('utf-8')}"
        )
        raise RoutingError("Invalid IPNS validity format")

    return entry


async def _resolve_entry(routing: Any, peer_id: ID) -> IpnsEntry:
    dht_key = f"/ipns/{peer_id.to_base58()}"
    record_bytes = await routing.get_value(dht_key)
    if not record_bytes:
        raise RoutingError(f"Could not resolve name: {peer_id.to_base58()}")
    return validate_ipns_record(record_bytes, peer_id)


async def resolve_name(routing: Any, peer_id: ID) -> str:
    """Resolve an IPNS record from the DHT and verify its signature."""
    entry = await _resolve_entry(routing, peer_id)
    return entry.value.decode("utf-8")
