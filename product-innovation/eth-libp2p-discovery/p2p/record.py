from dataclasses import dataclass
from typing import List
import time
import json
import hashlib

from libp2p.peer.id import ID
from multiaddr import Multiaddr
from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from p2p.config import RECORD_VERSION, RECORD_MAX_AGE_SECONDS

@dataclass
class ServiceRecord:
    service_id: bytes                
    peer_id: ID                      
    multiaddrs: List[Multiaddr]     
    timestamp: int                  
    signature: bytes                

    def to_payload(self) -> bytes:
        payload = {
            "version": RECORD_VERSION,
            "service_id": self.service_id.hex(),
            "peer_id": self.peer_id.pretty(),
            "multiaddrs": [str(m) for m in self.multiaddrs],
            "timestamp": self.timestamp,
        }

        return json.dumps(payload, sort_keys=True).encode()

    def serialize(self) -> bytes:
        return json.dumps(
            {
                "payload": self.to_payload().hex(),
                "signature": self.signature.hex(),
            }
        ).encode()

    @staticmethod
    def deserialize(raw: bytes) -> "ServiceRecord":
        data = json.loads(raw.decode())

        payload = bytes.fromhex(data["payload"])
        parsed = json.loads(payload.decode())

        return ServiceRecord(
            service_id=bytes.fromhex(parsed["service_id"]),
            peer_id=ID.from_base58(parsed["peer_id"]),
            multiaddrs=[Multiaddr(m) for m in parsed["multiaddrs"]],
            timestamp=parsed["timestamp"],
            signature=bytes.fromhex(data["signature"]),
        )


def sign_record(
    service_id: bytes,
    peer_id: ID,
    multiaddrs: List[Multiaddr],
    private_key: Ed25519PrivateKey,
) -> ServiceRecord:
    record = ServiceRecord(
        service_id=service_id,
        peer_id=peer_id,
        multiaddrs=multiaddrs,
        timestamp=int(time.time()),
        signature=b"",
    )

    signature = private_key.sign(record.to_payload())
    record.signature = signature

    return record


def verify_record(
    record: ServiceRecord,
    public_key: Ed25519PublicKey,
    max_age_seconds: int = RECORD_MAX_AGE_SECONDS,
) -> bool:
    try:
        public_key.verify(record.signature, record.to_payload())

        now = int(time.time())
        if now - record.timestamp > max_age_seconds:
            return False

        return True
    except Exception:
        return False


def derive_dht_key(service_id: bytes) -> bytes:
    return hashlib.sha256(b"service-discovery:" + service_id).digest()