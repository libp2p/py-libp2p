from dataclasses import dataclass
from typing import Optional
import trio

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.peer.peerinfo import PeerInfo
from libp2p.kad_dht.kad_dht import KadDHT

from p2p.record import ServiceRecord, verify_record
from p2p.constants import MAX_RESOLVED_PEERS, DHT_GET_TIMEOUT
from p2p.logging_config import setup_logging

log = setup_logging("resolver")

@dataclass
class ServiceResolver:
    dht: KadDHT
    owner_public_key: Ed25519PublicKey

    async def resolve(self, dht_key: str) -> Optional[PeerInfo]:
        try:
            raw = None
            with trio.move_on_after(DHT_GET_TIMEOUT):
                raw = await self.dht.get_value(dht_key)
            
            if not raw:
                log.warning(f"Value not found for key {dht_key}")
                return None

            record = ServiceRecord.deserialize(raw)

            if not verify_record(record, self.owner_public_key):
                log.warning("Record signature verification failed")
                return None

            return PeerInfo(
                peer_id=record.peer_id,
                addrs=record.multiaddrs[:MAX_RESOLVED_PEERS],
            )
        except Exception as e:
            log.error(f"Resolution failed: {e}")
            return None
