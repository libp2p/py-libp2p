from dataclasses import dataclass, field
from typing import List, Optional, Any
import asyncio

from multiaddr import Multiaddr
from libp2p.crypto.ed25519 import Ed25519PrivateKey

from p2p.record import (
    sign_record,
    derive_dht_key,
    ServiceRecord,
)
from p2p.config import RECORD_REFRESH_INTERVAL
from p2p.dht import DHTNode


@dataclass
class ServicePublisher:
    dht: DHTNode
    service_id: bytes
    private_key: Ed25519PrivateKey

    _task: Optional[asyncio.Task] = field(init=False, default=None)

    async def publish_once(
        self,
        peer_id: Any,
        multiaddrs: List[Multiaddr]
    ) -> None:
        record: ServiceRecord = sign_record(
            service_id=self.service_id,
            peer_id=peer_id,
            multiaddrs=multiaddrs,
            private_key=self.private_key,
        )
        key = derive_dht_key(self.service_id)
        await self.dht.put_value(key, record.serialize())

    async def start_auto_publish(
        self,
        peer_id: Any,
        multiaddrs: List[Multiaddr],
    ) -> None:
        async def _loop():
            while True:
                await self.publish_once(peer_id, multiaddrs)
                await asyncio.sleep(RECORD_REFRESH_INTERVAL)

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
