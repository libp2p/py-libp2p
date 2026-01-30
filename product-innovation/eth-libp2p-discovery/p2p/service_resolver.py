from dataclasses import dataclass
from typing import Optional

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.peer.peerinfo import PeerInfo

from p2p.record import ServiceRecord, verify_record
from p2p.dht import DHTNode
from p2p.constants import MAX_RESOLVED_PEERS

@dataclass
class ServiceResolver:
    dht: DHTNode
    owner_public_key: Ed25519PublicKey

    async def resolve(self, dht_key: bytes) -> Optional[PeerInfo]:
        try:
            dht_key_hex = dht_key.hex()
            raw = await self.dht.get_value(dht_key_hex)
            if not raw:
                return None

            record = ServiceRecord.deserialize(raw)

            if not verify_record(record, self.owner_public_key):
                return None

            return PeerInfo(
                peer_id=record.peer_id,
                addrs=record.multiaddrs[:MAX_RESOLVED_PEERS],
            )
        except Exception as e:
            return None
