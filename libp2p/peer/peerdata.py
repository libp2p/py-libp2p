from typing import Any, Dict, List, Sequence

from multiaddr import Multiaddr

from .peerdata_interface import IPeerData


class PeerData(IPeerData):

    metadata: Dict[Any, Any]
    protocols: List[str]
    addrs: List[Multiaddr]

    def __init__(self) -> None:
        self.metadata = {}
        self.protocols = []
        self.addrs = []

    def get_protocols(self) -> List[str]:
        return self.protocols

    def add_protocols(self, protocols: Sequence[str]) -> None:
        self.protocols.extend(list(protocols))

    def set_protocols(self, protocols: Sequence[str]) -> None:
        self.protocols = list(protocols)

    def add_addrs(self, addrs: Sequence[Multiaddr]) -> None:
        self.addrs.extend(addrs)

    def get_addrs(self) -> List[Multiaddr]:
        return self.addrs

    def clear_addrs(self) -> None:
        self.addrs = []

    def put_metadata(self, key: str, val: Any) -> None:
        self.metadata[key] = val

    def get_metadata(self, key: str) -> Any:
        if key in self.metadata:
            return self.metadata[key]
        raise PeerDataError("key not found")


class PeerDataError(KeyError):
    """Raised when a key is not found in peer metadata"""
