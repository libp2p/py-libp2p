import cbor2
from datetime import datetime, timezone, timedelta
import logging

from py_ipfs_lite.exceptions import RoutingError
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.records.pb.ipns_pb2 import IpnsEntry
from libp2p.peer.id import ID

logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = b"ipns-signature:"

def _format_rfc3339(dt: datetime) -> str:
    # Example: 2024-05-10T12:00:00.000000000Z
    # Note: Python's isoformat uses +00:00, we want Z
    base = dt.astimezone(timezone.utc).isoformat(timespec='microseconds')
    return base.replace("+00:00", "000Z")

def create_ipns_record(private_key: PrivateKey, value: str, sequence: int, lifetime_hours: int = 24) -> bytes:
    """Create a signed IPNS record."""
    value_bytes = value.encode('utf-8')
    
    # Calculate validity
    now = datetime.now(timezone.utc)
    validity_dt = now + timedelta(hours=lifetime_hours)
    validity_str = _format_rfc3339(validity_dt)
    validity_bytes = validity_str.encode('utf-8')
    
    # Create CBOR data (V2)
    cbor_data_dict = {
        "Value": value_bytes,
        "Validity": validity_bytes,
        "ValidityType": 0, # EOL
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

async def publish_name(routing, private_key: PrivateKey, peer_id: ID, value: str, sequence: int, lifetime_hours: int = 24) -> None:
    """Publish an IPNS record to the DHT."""
    record_bytes = create_ipns_record(private_key, value, sequence, lifetime_hours)
    # The DHT key for IPNS is /ipns/<peer-id-bytes>
    dht_key = b"/ipns/" + peer_id.to_bytes()
    await routing.put_value(dht_key, record_bytes)
    logger.info(f"Published IPNS record for {peer_id.to_base58()} -> {value}")

async def resolve_name(routing, peer_id: ID) -> str:
    """Resolve an IPNS record from the DHT."""
    dht_key = b"/ipns/" + peer_id.to_bytes()
    record_bytes = await routing.get_value(dht_key)
    if not record_bytes:
        raise RoutingError(f"Could not resolve name: {peer_id.to_base58()}")
        
    entry = IpnsEntry()
    entry.ParseFromString(record_bytes)
    
    # For a full implementation, we should validate the signature here
    # libp2p.records.ipns.IPNSValidator can do this if hooked up.
    
    return entry.value.decode('utf-8')
