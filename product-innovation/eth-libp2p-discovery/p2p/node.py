from dataclasses import dataclass, field
from typing import List, Optional
from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr
from libp2p.crypto.ed25519 import create_new_key_pair

from p2p.config import DEFAULT_LISTEN_ADDRS

@dataclass
class Libp2pNode:
    listen_addrs: Optional[List[str]] = field(default=None)
    host: Optional[object] = field(init=False, default=None)

    async def start(self) -> None:
        listen_addrs = self.listen_addrs if self.listen_addrs is not None else DEFAULT_LISTEN_ADDRS

        key_pair = create_new_key_pair()

        self.host = new_host(
            key_pair=key_pair,
            listen_addrs=[Multiaddr(addr) for addr in listen_addrs],
        )

    async def stop(self) -> None:
        if self.host:
            await self.host.close()
            self.host = None

    @property
    def peer_id(self):
        if not self.host:
            raise RuntimeError("host not started")
        return self.host.get_id()

    @property
    def peer_info(self) -> PeerInfo:
        if not self.host:
            raise RuntimeError("host not started")
        return PeerInfo(
            peer_id=self.host.get_id(),
            addrs=list(self.host.get_addrs()),
        )
