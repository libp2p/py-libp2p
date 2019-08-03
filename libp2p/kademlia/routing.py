import asyncio
from collections import OrderedDict
import heapq
import operator
import time

from .utils import OrderedSet, bytes_to_bit_string, shared_prefix


class KBucket:
    """
    each node keeps a list of (ip, udp_port, node_id)
    for nodes of distance between 2^i and 2^(i+1)
    this list that every node keeps is a k-bucket
    each k-bucket implements a last seen eviction
    policy except that live nodes are never removed
    """

    def __init__(self, rangeLower, rangeUpper, ksize):
        self.range = (rangeLower, rangeUpper)
        self.nodes = OrderedDict()
        self.replacement_nodes = OrderedSet()
        self.touch_last_updated()
        self.ksize = ksize

    def touch_last_updated(self):
        self.last_updated = time.monotonic()

    def get_nodes(self):
        return list(self.nodes.values())

    def split(self):
        midpoint = (self.range[0] + self.range[1]) / 2
        one = KBucket(self.range[0], midpoint, self.ksize)
        two = KBucket(midpoint + 1, self.range[1], self.ksize)
        for node in self.nodes.values():
            bucket = one if node.xor_id <= midpoint else two
            bucket.nodes[node.peer_id_bytes] = node
        return (one, two)

    def remove_node(self, node):
        if node.peer_id_bytes not in self.nodes:
            return

        # delete node, and see if we can add a replacement
        del self.nodes[node.peer_id_bytes]
        if self.replacement_nodes:
            newnode = self.replacement_nodes.pop()
            self.nodes[newnode.peer_id_bytes] = newnode

    def has_in_range(self, node):
        return self.range[0] <= node.xor_id <= self.range[1]

    def is_new_node(self, node):
        return node.peer_id_bytes not in self.nodes

    def add_node(self, node):
        """
        Add a C{Node} to the C{KBucket}.  Return True if successful,
        False if the bucket is full.

        If the bucket is full, keep track of node in a replacement list,
        per section 4.1 of the paper.
        """
        if node.peer_id_bytes in self.nodes:
            del self.nodes[node.peer_id_bytes]
            self.nodes[node.peer_id_bytes] = node
        elif len(self) < self.ksize:
            self.nodes[node.peer_id_bytes] = node
        else:
            self.replacement_nodes.push(node)
            return False
        return True

    def depth(self):
        vals = self.nodes.values()
        sprefix = shared_prefix([bytes_to_bit_string(n.peer_id_bytes) for n in vals])
        return len(sprefix)

    def head(self):
        return list(self.nodes.values())[0]

    def __getitem__(self, node_id):
        return self.nodes.get(node_id, None)

    def __len__(self):
        return len(self.nodes)


class TableTraverser:
    def __init__(self, table, startNode):
        index = table.get_bucket_for(startNode)
        table.buckets[index].touch_last_updated()
        self.current_nodes = table.buckets[index].get_nodes()
        self.left_buckets = table.buckets[:index]
        self.right_buckets = table.buckets[(index + 1) :]
        self.left = True

    def __iter__(self):
        return self

    def __next__(self):
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
    def __init__(self, protocol, ksize, node):
        """
        @param node: The node that represents this server.  It won't
        be added to the routing table, but will be needed later to
        determine which buckets to split or not.
        """
        self.node = node
        self.protocol = protocol
        self.ksize = ksize
        self.flush()

    def flush(self):
        self.buckets = [KBucket(0, 2 ** 160, self.ksize)]

    def split_bucket(self, index):
        one, two = self.buckets[index].split()
        self.buckets[index] = one
        self.buckets.insert(index + 1, two)

    def lonely_buckets(self):
        """
        Get all of the buckets that haven't been updated in over
        an hour.
        """
        hrago = time.monotonic() - 3600
        return [b for b in self.buckets if b.last_updated < hrago]

    def remove_contact(self, node):
        index = self.get_bucket_for(node)
        self.buckets[index].remove_node(node)

    def is_new_node(self, node):
        index = self.get_bucket_for(node)
        return self.buckets[index].is_new_node(node)

    def add_contact(self, node):
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

    def get_bucket_for(self, node):
        """
        Get the index of the bucket that the given node would fall into.
        """
        for index, bucket in enumerate(self.buckets):
            if node.xor_id < bucket.range[1]:
                return index
        # we should never be here, but make linter happy
        return None

    def find_neighbors(self, node, k=None, exclude=None):
        k = k or self.ksize
        nodes = []
        for neighbor in TableTraverser(self, node):
            notexcluded = exclude is None or not neighbor.same_home_as(exclude)
            if neighbor.peer_id_bytes != node.peer_id_bytes and notexcluded:
                heapq.heappush(nodes, (node.distance_to(neighbor), neighbor))
            if len(nodes) == k:
                break

        return list(map(operator.itemgetter(1), heapq.nsmallest(k, nodes)))
