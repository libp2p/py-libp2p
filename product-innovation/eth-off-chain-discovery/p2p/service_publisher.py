from dataclasses import dataclass
from typing import List, Any

from multiaddr import Multiaddr
from libp2p.crypto.ed25519 import Ed25519PrivateKey
from libp2p.kad_dht.kad_dht import KadDHT

from p2p.record import sign_record, ServiceRecord
from p2p.logging_config import setup_logging

log = setup_logging("publisher")

@dataclass
class ServicePublisher:
    dht: KadDHT
    service_id: bytes
    private_key: Ed25519PrivateKey

    async def publish_once(self, peer_id: Any, multiaddrs: List[Multiaddr], dht_key: str) -> None:
        record: ServiceRecord = sign_record(
            service_id=self.service_id,
            peer_id=peer_id,
            multiaddrs=multiaddrs,
            private_key=self.private_key,
        )
        await self.dht.put_value(dht_key, record.serialize())
        log.debug(f"Published record with {len(multiaddrs)} addresses")