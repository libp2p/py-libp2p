from dataclasses import dataclass, field
from typing import List, Optional, Any
import asyncio
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.peerinfo import PeerInfo
from p2p.config import DHT_GET_TIMEOUT

@dataclass
class DHTNode:
    host: Any
    dht: Optional[KadDHT] = field(init=False, default=None)
    dht_mode: DHTMode = DHTMode.SERVER

    async def start(self, bootstrap_peers: Optional[List[PeerInfo]] = None) -> None:
        self.dht = KadDHT(self.host, self.dht_mode)

        if bootstrap_peers:
            for peer in bootstrap_peers:
                await self.host.connect(peer)
            await self.dht.bootstrap(bootstrap_peers)

    async def stop(self) -> None:
        if self.dht and hasattr(self.dht, "stop"):
            await self.dht.stop()
        self.dht = None

    async def put_value(self, key: str, value: bytes) -> None:
        if not self.dht:
            raise RuntimeError("DHT not started")
        await self.dht.put_value(key, value)

    async def get_value(self, key: str) -> Optional[bytes]:
        if not self.dht:
            raise RuntimeError("DHT not started")
        try:
            return await asyncio.wait_for(
                self.dht.get_value(key),
                timeout=DHT_GET_TIMEOUT
            )
        except asyncio.TimeoutError:
            return None
