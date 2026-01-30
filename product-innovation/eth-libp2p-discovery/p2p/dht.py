from dataclasses import dataclass, field
from typing import List, Optional, Any
import asyncio
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.peerinfo import PeerInfo
from p2p.constants import DHT_GET_TIMEOUT

@dataclass
class DHTNode:
    host: Any
    dht: Optional[KadDHT] = field(init=False, default=None)
    dht_mode: DHTMode = DHTMode.SERVER

    async def start(self, bootstrap_peers: Optional[List[PeerInfo]] = None) -> None:
        if self.dht is not None:
            raise RuntimeError("DHT already started")
        self.dht = KadDHT(self.host, self.dht_mode)

        if bootstrap_peers:
            for peer in bootstrap_peers:
                try:
                    await self.host.connect(peer)
                except Exception:
                    pass  

    async def stop(self) -> None:
        if self.dht is not None and hasattr(self.dht, "stop"):
            try:
                await self.dht.stop()
            except Exception:
                pass
        self.dht = None

    async def put_value(self, key: str, value: bytes) -> None:
        if self.dht is None:
            raise RuntimeError("DHT not started")
        try:
            await self.dht.put_value(key, value)
        except Exception as e:
            raise RuntimeError(f"Failed to put value in DHT: {e}")

    async def get_value(self, key: str) -> Optional[bytes]:
        if self.dht is None:
            raise RuntimeError("DHT not started")
        try:
            return await asyncio.wait_for(
                self.dht.get_value(key),
                timeout=DHT_GET_TIMEOUT
            )
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None