from dataclasses import dataclass, field
from typing import List, Optional
from libp2p import new_host
from libp2p.abc import IHost
from multiaddr import Multiaddr
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo

from p2p.constants import DEFAULT_LISTEN_ADDRS

@dataclass
class Libp2pNode:
    listen_addrs: Optional[List[str]] = field(default=None)
    host: Optional[IHost] = field(init=False, default=None)
    _key_pair: Optional[object] = field(init=False, default=None)

    def create_host(self) -> IHost:
        addrs = self.listen_addrs if self.listen_addrs else DEFAULT_LISTEN_ADDRS
        self._key_pair = create_new_key_pair()
        self.host = new_host(key_pair=self._key_pair)
        return self.host

    def get_listen_addrs(self) -> List[Multiaddr]:
        addrs = self.listen_addrs if self.listen_addrs else DEFAULT_LISTEN_ADDRS
        return [Multiaddr(addr) for addr in addrs]

    @property
    def peer_id(self):
        if self.host is None:
            raise RuntimeError("Host not created. Call create_host() first.")
        return self.host.get_id()

    @property
    def peer_info(self) -> PeerInfo:
        if self.host is None:
            raise RuntimeError("Host not created. Call create_host() first.")
        return PeerInfo(self.host.get_id(), self.host.get_addrs())