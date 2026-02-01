from dataclasses import dataclass, field
from typing import List, Optional, Any
import trio

from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.peerinfo import PeerInfo
from p2p.constants import DHT_GET_TIMEOUT

def create_dht(host: Any, dht_mode: DHTMode = DHTMode.SERVER) -> KadDHT:
    return KadDHT(host, dht_mode, enable_random_walk=True)

async def dht_put_value(dht: KadDHT, key: str, value: bytes) -> None:
    await dht.put_value(key, value)

async def dht_get_value(dht: KadDHT, key: str) -> Optional[bytes]:
    try:
        with trio.move_on_after(DHT_GET_TIMEOUT):
            return await dht.get_value(key)
    except Exception:
        pass
    return None