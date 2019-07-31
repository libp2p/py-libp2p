import heapq
import time
import operator
import asyncio

from collections import OrderedDict
from .utils import OrderedSet, shared_prefix, bytes_to_bit_string


from typing import (
    Tuple,
    Any,
    TYPE_CHECKING,
    Sequence,
    List,
    Union,
)
if TYPE_CHECKING:
    from .kad_peerinfo import KadPeerInfo
    from libp2p.peer.id import ID
    from multiaddr import Multiaddr
    from .protocol import KademliaProtocol


class KBucket:
    """
    each node keeps a list of (ip, udp_port, node_id)
    for nodes of distance between 2^i and 2^(i+1)
    this list that every node keeps is a k-bucket
    each k-bucket implements a last seen eviction
    policy except that live nodes are never removed
    """
    range: Tuple[int, int]
    nodes: 'OrderedDict[bytes, KadPeerInfo]'
    replacement_nodes: 'OrderedSet[KadPeerInfo]'
    ksize: int
    last_updated: float

    def __init__(self, rangeLower: int, rangeUpper: int, ksize: int) -> None:
        self.range = (rangeLower, rangeUpper)
        self.nodes = OrderedDict()
        self.replacement_nodes = OrderedSet()
        self.touch_last_updated()
        self.ksize = ksize

    def touch_last_updated(self) -> None:
        self.last_updated = time.monotonic()

    def get_nodes(self) -> List['KadPeerInfo']:
        return list(self.nodes.values())

    def split(self) -> Tuple['KBucket', 'KBucket']:
        midpoint = (self.range[0] + self.range[1]) // 2
        one = KBucket(self.range[0], midpoint, self.ksize)
        two = KBucket(midpoint + 1, self.range[1], self.ksize)
        for node in self.nodes.values():
            bucket = one if node.xor_id <= midpoint else two
            bucket.nodes[node.peer_id_raw] = node
        return (one, two)

    def remove_node(self, node: 'KadPeerInfo') -> None:
        if node.peer_id_raw not in self.nodes:
            return

        # delete node, and see if we can add a replacement
        del self.nodes[node.peer_id_raw]
        if self.replacement_nodes:
            newnode = self.replacement_nodes.pop()
            self.nodes[newnode.peer_id_raw] = newnode

    def has_in_range(self, node: 'KadPeerInfo') -> bool:
        return self.range[0] <= node.xor_id <= self.range[1]

    def is_new_node(self, node: 'KadPeerInfo') -> bool:
        return node.peer_id_raw not in self.nodes

    def add_node(self, node: 'KadPeerInfo') -> bool:
        """
        Add a C{Node} to the C{KBucket}.  Return True if successful,
        False if the bucket is full.

        If the bucket is full, keep track of node in a replacement list,
        per section 4.1 of the paper.
        """
        if node.peer_id_raw in self.nodes:
            del self.nodes[node.peer_id_raw]
            self.nodes[node.peer_id_raw] = node
        elif len(self) < self.ksize:
            self.nodes[node.peer_id_raw] = node
        else:
            self.replacement_nodes.push(node)
            return False
        return True

    def depth(self) -> int:
        vals = self.nodes.values()
        sprefix = shared_prefix([bytes_to_bit_string(n.peer_id_raw) for n in vals])
        return len(sprefix)

    def head(self) -> 'KadPeerInfo':
        return list(self.nodes.values())[0]

    def __getitem__(self, node_id: bytes) -> 'KadPeerInfo':
        return self.nodes.get(node_id, None)

    def __len__(self) -> int:
        return len(self.nodes)


class TableTraverser:
    current_nodes: List['KadPeerInfo']
    left_buckets: List['KBucket']
    right_buckets: List['KBucket']
    left: bool

    def __init__(self, table: 'RoutingTable', startNode: 'KadPeerInfo') -> None:
        index = table.get_bucket_for(startNode)
        table.buckets[index].touch_last_updated()
        self.current_nodes = table.buckets[index].get_nodes()
        self.left_buckets = table.buckets[:index]
        self.right_buckets = table.buckets[(index + 1) :]
        self.left = True

    def __iter__(self) -> 'TableTraverser':
        return self

    def __next__(self) -> 'KadPeerInfo':
        """
        Pop an item from the left subtree, then right, then left, etc.
        """
        if self.current_nodes:
            return self.current_nodes.pop()

        if self.left and self.left_buckets:
            self.current_nodes = self.left_buckets.pop().get_nodes()
            self.left = False
            return next(self)

        if self.right_buckets:
            self.current_nodes = self.right_buckets.pop(0).get_nodes()
            self.left = True
            return next(self)

        raise StopIteration


class RoutingTable:
    node: 'KadPeerInfo'
    protocol: 'KademliaProtocol'
    ksize: int
    buckets: List['KBucket']

    def __init__(self, protocol: 'KademliaProtocol', ksize: int, node: 'KadPeerInfo') -> None:
        """
        @param node: The node that represents this server.  It won't
        be added to the routing table, but will be needed later to
        determine which buckets to split or not.
        """
        self.node = node
        self.protocol = protocol
        self.ksize = ksize
        self.flush()

    def flush(self) -> None:
        self.buckets = [KBucket(0, 2 ** 160, self.ksize)]

    def split_bucket(self, index: int) -> None:
        one, two = self.buckets[index].split()
        self.buckets[index] = one
        self.buckets.insert(index + 1, two)

    def lonely_buckets(self) -> List['KBucket']:
        """
        Get all of the buckets that haven't been updated in over
        an hour.
        """
        hrago = time.monotonic() - 3600
        return [b for b in self.buckets if b.last_updated < hrago]

    def remove_contact(self, node: 'KadPeerInfo') -> None:
        index = self.get_bucket_for(node)
        self.buckets[index].remove_node(node)

    def is_new_node(self, node: 'KadPeerInfo') -> bool:
        index = self.get_bucket_for(node)
        return self.buckets[index].is_new_node(node)

    def add_contact(self, node: 'KadPeerInfo') -> None:
        index = self.get_bucket_for(node)
        bucket = self.buckets[index]

        # this will succeed unless the bucket is full
        if bucket.add_node(node):
            return

        # Per section 4.2 of paper, split if the bucket has the node
        # in its range or if the depth is not congruent to 0 mod 5
        if bucket.has_in_range(self.node) or bucket.depth() % 5 != 0:
            self.split_bucket(index)
            self.add_contact(node)
        else:
            asyncio.ensure_future(self.protocol.call_ping(bucket.head()))

    def get_bucket_for(self, node: 'KadPeerInfo') -> int:
        """
        Get the index of the bucket that the given node would fall into.
        """
        for index, bucket in enumerate(self.buckets):
            if node.xor_id < bucket.range[1]:
                return index
        # we should never be here, but make linter happy
        return None

    def find_neighbors(self,
                       node: 'KadPeerInfo',
                       k: int = None,
                       exclude: 'Multiaddr' = None) -> List['KadPeerInfo']:
        k = k or self.ksize
        nodes: List['KadPeerInfo'] = []
        for neighbor in TableTraverser(self, node):
            notexcluded = exclude is None or not neighbor.same_home_as(exclude)
            if neighbor.peer_id != node.peer_id and notexcluded:
                heapq.heappush(nodes, (node.distance_to(neighbor), neighbor))
            if len(nodes) == k:
                break

        return list(map(operator.itemgetter(1), heapq.nsmallest(k, nodes)))
