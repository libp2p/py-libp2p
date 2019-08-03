import asyncio
import logging
import random

from rpcudp.protocol import RPCProtocol

from .kad_peerinfo import create_kad_peerinfo
from .routing import RoutingTable

log = logging.getLogger(__name__)


class KademliaProtocol(RPCProtocol):
    """
    There are four main RPCs in the Kademlia protocol
    PING, STORE, FIND_NODE, FIND_VALUE
    PING probes if a node is still online
    STORE instructs a node to store (key, value)
    FIND_NODE takes a 160-bit ID and gets back
    (ip, udp_port, node_id) for k closest nodes to target
    FIND_VALUE behaves like FIND_NODE unless a value is stored
    """

    def __init__(self, source_node, storage, ksize):
        RPCProtocol.__init__(self)
        self.router = RoutingTable(self, ksize, source_node)
        self.storage = storage
        self.source_node = source_node

    def get_refresh_ids(self):
        """
        Get ids to search for to keep old buckets up to date.
        """
        ids = []
        for bucket in self.router.lonely_buckets():
            rid = random.randint(*bucket.range).to_bytes(20, byteorder="big")
            ids.append(rid)
        return ids

    def rpc_stun(self, sender):
        return sender

    def rpc_ping(self, sender, nodeid):
        source = create_kad_peerinfo(nodeid, sender[0], sender[1])

        self.welcome_if_new(source)
        return self.source_node.peer_id_bytes

    def rpc_store(self, sender, nodeid, key, value):
        source = create_kad_peerinfo(nodeid, sender[0], sender[1])

        self.welcome_if_new(source)
        log.debug(
            "got a store request from %s, storing '%s'='%s'", sender, key.hex(), value
        )
        self.storage[key] = value
        return True

    def rpc_find_node(self, sender, nodeid, key):
        log.info("finding neighbors of %i in local table", int(nodeid.hex(), 16))
        source = create_kad_peerinfo(nodeid, sender[0], sender[1])

        self.welcome_if_new(source)
        node = create_kad_peerinfo(key)
        neighbors = self.router.find_neighbors(node, exclude=source)
        return list(map(tuple, neighbors))

    def rpc_find_value(self, sender, nodeid, key):
        source = create_kad_peerinfo(nodeid, sender[0], sender[1])

        self.welcome_if_new(source)
        value = self.storage.get(key, None)
        if value is None:
            return self.rpc_find_node(sender, nodeid, key)
        return {"value": value}

    def rpc_add_provider(self, sender, nodeid, key, provider_id):
        """
        rpc when receiving an add_provider call
        should validate received PeerInfo matches sender nodeid
        if it does, receipient must store a record in its datastore
        we store a map of content_id to peer_id (non xor)
        """
        if nodeid == provider_id:
            log.info(
                "adding provider %s for key %s in local table", provider_id, str(key)
            )
            self.storage[key] = provider_id
            return True
        return False

    def rpc_get_providers(self, sender, key):
        """
        rpc when receiving a get_providers call
        should look up key in data store and respond with records
        plus a list of closer peers in its routing table
        """
        providers = []
        record = self.storage.get(key, None)

        if record:
            providers.append(record)

        keynode = create_kad_peerinfo(key)
        neighbors = self.router.find_neighbors(keynode)
        for neighbor in neighbors:
            if neighbor.peer_id_bytes != record:
                providers.append(neighbor.peer_id_bytes)

        return providers

    async def call_find_node(self, node_to_ask, node_to_find):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.find_node(
            address, self.source_node.peer_id_bytes, node_to_find.peer_id_bytes
        )
        return self.handle_call_response(result, node_to_ask)

    async def call_find_value(self, node_to_ask, node_to_find):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.find_value(
            address, self.source_node.peer_id_bytes, node_to_find.peer_id_bytes
        )
        return self.handle_call_response(result, node_to_ask)

    async def call_ping(self, node_to_ask):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.ping(address, self.source_node.peer_id_bytes)
        return self.handle_call_response(result, node_to_ask)

    async def call_store(self, node_to_ask, key, value):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.store(address, self.source_node.peer_id_bytes, key, value)
        return self.handle_call_response(result, node_to_ask)

    async def call_add_provider(self, node_to_ask, key, provider_id):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.add_provider(
            address, self.source_node.peer_id_bytes, key, provider_id
        )

        return self.handle_call_response(result, node_to_ask)

    async def call_get_providers(self, node_to_ask, key):
        address = (node_to_ask.ip, node_to_ask.port)
        result = await self.get_providers(address, key)
        return self.handle_call_response(result, node_to_ask)

    def welcome_if_new(self, node):
        """
        Given a new node, send it all the keys/values it should be storing,
        then add it to the routing table.

        @param node: A new node that just joined (or that we just found out
        about).

        Process:
        For each key in storage, get k closest nodes.  If newnode is closer
        than the furtherst in that list, and the node for this server
        is closer than the closest in that list, then store the key/value
        on the new node (per section 2.5 of the paper)
        """
        if not self.router.is_new_node(node):
            return

        log.info("never seen %s before, adding to router", node)
        for key, value in self.storage:
            keynode = create_kad_peerinfo(key)
            neighbors = self.router.find_neighbors(keynode)
            if neighbors:
                last = neighbors[-1].distance_to(keynode)
                new_node_close = node.distance_to(keynode) < last
                first = neighbors[0].distance_to(keynode)
                this_closest = self.source_node.distance_to(keynode) < first
            if not neighbors or (new_node_close and this_closest):
                asyncio.ensure_future(self.call_store(node, key, value))
        self.router.add_contact(node)

    def handle_call_response(self, result, node):
        """
        If we get a response, add the node to the routing table.  If
        we get no response, make sure it's removed from the routing table.
        """
        if not result[0]:
            log.warning("no response from %s, removing from router", node)
            self.router.remove_contact(node)
            return result

        log.info("got successful response from %s", node)
        self.welcome_if_new(node)
        return result
