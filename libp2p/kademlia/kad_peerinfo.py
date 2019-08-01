import heapq
import random

from operator import itemgetter
from multiaddr import Multiaddr
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData
from .utils import digest
from typing import List, TYPE_CHECKING, Iterator, Any, Tuple, Set, Sequence, Union

if TYPE_CHECKING:
    from libp2p.host.host_interface import IHost

P_IP = "ip4"
P_UDP = "udp"


class KadPeerInfo(PeerInfo):
    xor_id: int
    ip: str
    port: int

    def __init__(self, peer_id: ID, peer_data: PeerData = None) -> None:
        super().__init__(peer_id, peer_data)

        self.xor_id = peer_id.get_xor_id()

        # pylint: disable=invalid-name
        self.ip = self.addrs[0].value_for_protocol(P_IP) if peer_data else None
        self.port = int(self.addrs[0].value_for_protocol(P_UDP)) if peer_data else None

    def same_home_as(self, node: "KadPeerInfo") -> bool:
        return sorted(self.addrs) == sorted(node.addrs)

    def distance_to(self, node: "KadPeerInfo") -> int:
        """
        Get the distance between this node and another.
        """
        return self.xor_id ^ node.xor_id

    def __iter__(self) -> Iterator[Any]:
        """
        Enables use of Node as a tuple - i.e., tuple(node) works.
        """
        return iter([self.peer_id_raw, self.ip, self.port])

    def __repr__(self) -> str:
        return repr([self.xor_id, self.ip, self.port, self.peer_id])

    def __str__(self) -> str:
        return "%s:%s" % (self.ip, str(self.port))

    def encode(self) -> str:
        return f"{str(self.peer_id)}\n/ip4/{str(self.ip)}/udp/{str(self.port)}"


class KadPeerHeap:
    """
    A heap of peers ordered by distance to a given node.
    """

    node: "KadPeerInfo"
    heap: List[Tuple[int, "KadPeerInfo"]]
    contacted: Set[bytes]
    maxsize: int

    def __init__(self, node: "KadPeerInfo", maxsize: int) -> None:
        """
        Constructor.

        @param node: The node to measure all distnaces from.
        @param maxsize: The maximum size that this heap can grow to.
        """
        self.node = node
        self.heap = []
        self.contacted = set()
        self.maxsize = maxsize

    def remove(self, peers: Set["KadPeerInfo"]) -> None:
        """
        Remove a list of peer ids from this heap.  Note that while this
        heap retains a constant visible size (based on the iterator), it's
        actual size may be quite a bit larger than what's exposed.  Therefore,
        removal of nodes may not change the visible size as previously added
        nodes suddenly become visible.
        """
        peers = set(peers)
        if not peers:
            return
        nheap: List[Tuple[int, "KadPeerInfo"]] = []
        for distance, node in self.heap:
            if node not in peers:
                heapq.heappush(nheap, (distance, node))
        self.heap = nheap

    def get_node(self, node_id: bytes) -> "KadPeerInfo":
        for _, node in self.heap:
            if node.peer_id_raw == node_id:
                return node
        return None

    def have_contacted_all(self) -> bool:
        return len(self.get_uncontacted()) == 0

    def get_ids(self) -> List[bytes]:
        return [n.peer_id_raw for n in self]

    def mark_contacted(self, node: "KadPeerInfo") -> None:
        self.contacted.add(node.peer_id_raw)

    def popleft(self) -> "KadPeerInfo":
        return heapq.heappop(self.heap)[1] if self else None

    def push(self, nodes: Union["KadPeerInfo", Sequence["KadPeerInfo"]]) -> None:
        """
        Push nodes onto heap.

        @param nodes: This can be a single item or a C{list}.
        """
        nodes_list: Sequence["KadPeerInfo"]
        if not isinstance(nodes, list):
            # typing doesn't know nodes is already list
            nodes_list = [nodes]  # type: ignore
        else:
            nodes_list = nodes

        for node in nodes_list:
            if node not in self:
                distance = self.node.distance_to(node)
                heapq.heappush(self.heap, (distance, node))

    def __len__(self) -> int:
        return min(len(self.heap), self.maxsize)

    def __iter__(self) -> Iterator["KadPeerInfo"]:
        nodes = heapq.nsmallest(self.maxsize, self.heap)
        for _, node in nodes:
            yield node

    def __contains__(self, node: "KadPeerInfo") -> bool:
        for _, other in self.heap:
            if node.peer_id_raw == other.peer_id_raw:
                return True
        return False

    def get_uncontacted(self) -> List["KadPeerInfo"]:
        return [n for n in self if n.peer_id_raw not in self.contacted]


def create_kad_peerinfo(
    raw_node_id: bytes = None, sender_ip: str = None, sender_port: int = None
) -> "KadPeerInfo":
    node_id = ID(raw_node_id) if raw_node_id else ID(digest(random.getrandbits(255)))
    peer_data = None
    if sender_ip and sender_port:
        peer_data = PeerData()  # pylint: disable=no-value-for-parameter
        addr = [Multiaddr(f"/{P_IP}/{str(sender_ip)}/{P_UDP}/{str(sender_port)}")]
        peer_data.add_addrs(addr)

    return KadPeerInfo(node_id, peer_data)
