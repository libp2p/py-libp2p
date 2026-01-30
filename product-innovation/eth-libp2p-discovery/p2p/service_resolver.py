from dataclasses import dataclass
from typing import Optional

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.peer.peerinfo import PeerInfo

from p2p.record import (
    ServiceRecord,
    derive_dht_key,
    verify_record,
)
from p2p.dht import DHTNode

@dataclass
class ServiceResolver:
    dht: DHTNode
    service_id: bytes
    owner_public_key: Ed25519PublicKey

    async def resolve(self) -> Optional[PeerInfo]:
        key = derive_dht_key(self.service_id)
        raw = await self.dht.get_value(key)

        if not raw:
            return None

        try:
            record = ServiceRecord.deserialize(raw)
        except Exception:
            return None

        valid = verify_record(
            record,
            public_key=self.owner_public_key,
            max_age_seconds=RECORD_MAX_AGE_SECONDS,
        )
        if not valid:
            return None

        return PeerInfo(
            peer_id=record.peer_id,
            addrs=record.multiaddrs[:MAX_RESOLVED_PEERS],
        )
