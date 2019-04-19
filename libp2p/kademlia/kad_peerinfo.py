import heapq
import multihash
from operator import itemgetter
from libp2p.peer.peerinfo import PeerInfo


class KadPeerInfo(PeerInfo):
    def __init__(self, peer_id, peer_data=None):
        super(KadPeerInfo, self).__init__(peer_id, peer_data)
        print ("Kad Peer Info")
        print (peer_id)
        print (peer_data)
        sha1 = multihash.Func.sha1
        mh_digest = multihash.digest(peer_id.pretty().encode('utf-8'), sha1)
        self.peer_id = peer_id.pretty()
        self.long_id = int.from_bytes(mh_digest.encode(), byteorder='big')

    def same_home_as(self, node):
        #TODO: handle more than one addr
        return self.addrs[0] == node.addrs[0]

    def distance_to(self, node):
        """
        Get the distance between this node and another.
        """
        return self.long_id ^ node.long_id

    def __iter__(self):
        """
        Enables use of Node as a tuple - i.e., tuple(node) works.
        """
        return iter([self.peer_id.pretty(), str(self.addrs[0])])

    def __repr__(self):
        return repr([self.long_id, str(self.addrs[0])])

    def __str__(self):
        return str(self.addrs[0])

class KadPeerHeap:
    """
    A heap of peers ordered by distance to a given node.
    """
    def __init__(self, node, maxsize):
        """
        Constructor.

        @param node: The node to measure all distnaces from.
        @param maxsize: The maximum size that this heap can grow to.
        """
        self.node = node
        self.heap = []
        self.contacted = set()
        self.maxsize = maxsize

    def remove(self, peers):
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
        nheap = []
        for distance, node in self.heap:
            if node.peer_id not in peers:
                heapq.heappush(nheap, (distance, node))
        self.heap = nheap

    def get_node(self, node_id):
        for _, node in self.heap:
            if node.peer_id == node_id:
                return node
        return None

    def have_contacted_all(self):
        return len(self.get_uncontacted()) == 0

    def get_ids(self):
        return [n.peer_id for n in self]

    def mark_contacted(self, node):
        self.contacted.add(node.peer_id)

    def popleft(self):
        return heapq.heappop(self.heap)[1] if self else None

    def push(self, nodes):
        """
        Push nodes onto heap.

        @param nodes: This can be a single item or a C{list}.
        """
        if not isinstance(nodes, list):
            nodes = [nodes]

        for node in nodes:
            if node not in self:
                distance = self.node.distance_to(node)
                heapq.heappush(self.heap, (distance, node))

    def __len__(self):
        return min(len(self.heap), self.maxsize)

    def __iter__(self):
        nodes = heapq.nsmallest(self.maxsize, self.heap)
        return iter(map(itemgetter(1), nodes))

    def __contains__(self, node):
        for _, other in self.heap:
            if node.peer_id == other.peer_id:
                return True
        return False

    def get_uncontacted(self):
        return [n for n in self if n.peer_id not in self.contacted]
