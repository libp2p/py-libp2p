from aio_timers import Timer
from lru import LRU
from .pb import rpc_pb2
from .pubsub_router_interface import IPubsubRouter
import random


class GossipSub(IPubsubRouter):
    # pylint: disable=no-member

    def __init__(self, protocols, mcache_size=128, heartbeat_interval=120, degree, degree_low, degree_high):
        self.protocols = protocols
        self.pubsub = None

        # Store target degree, upper degree bound, and lower degree bound
        self.degree = degree
        self.degree_high = degree_high
        self.degree_low = degree_low

        # Create topic --> list of peers mappings
        self.mesh = {}
        self.fanout = {}

        # Create peers map (peer --> protocol)
        self.peers_to_protocol = {}

        # Create message cache
        self.mcache = LRU(mcache_size)

        # Create heartbeat timer
        self.heartbeat_timer = Timer(heartbeat_interval, self.heartbeat)

    # Interface functions

    def get_protocols(self):
        """
        :return: the list of protocols supported by the router
        """
        return self.protocols

    def attach(self, pubsub):
        """
        Attach is invoked by the PubSub constructor to attach the router to a
        freshly initialized PubSub instance.
        :param pubsub: pubsub instance to attach to
        """
        self.pubsub = pubsub

        # Start heartbeat now that we have a pubsub instance
        # TODO: Start after delay
        asyncio.ensure_future(self.heartbeat())

    def add_peer(self, peer_id, protocol_id):
        """
        Notifies the router that a new peer has been connected
        :param peer_id: id of peer to add
        """
        self.peers_to_protocol[peer_id] = protocol_id

    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """
        self.peers_to_protocol.remove(peer_id)

    def handle_rpc(self, rpc):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        :param rpc: rpc message
        """

        control_message = rpc.control

        # Relay each rpc control  to the appropriate handler
        if control_message.ihave:
            for ihave in control_message.ihave:
                await self.handle_ihave(ihave)
        if control_message.iwant:
            for iwant in control_message.iwant:
                await self.handle_iwant(iwant)
        if control_message.graft:
            for graft in control_message.graft:
                await self.handle_graft(graft)
        if control_message.prune:
            for prune in control_message.prune:
                await self.handle_prune(prune)

    async def publish(self, sender_peer_id, rpc_message):
        """
        Invoked to forward a new message that has been validated.
        """

    def join(self, topic):
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """

    def leave(self, topic):
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """

    # Heartbeat
    async def heartbeat(self):
        # Call individual heartbeats
        # Note: the heartbeats are called with awaits because each heartbeat depends on the 
        # state changes in the preceding heartbeat
        await self.mesh_heartbeat()
        await self.fanout_heartbeat()
        await self.gossip_heartbeat()

        # Restart timer
        self.heartbeat_timer = Timer(heartbeat_interval, self.heartbeat)

        # TODO: Check if this is right way to use timer
        asyncio.ensure_future(self.heartbeat_timer.wait())

    async def mesh_heartbeat(self):
        for topic in mesh:
            mesh_peers_in_topic = len(mesh[topic])
            if mesh_peers_in_topic < degree_low:
                gossipsub_peers = self.get_gossipsub_peers()

                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]
                # ; i.e. not including those peers that are already in the topic mesh.
                selected_peers = self.select_from_minus(self.degree - mesh_peers_in_topic, \
                    gossipsub_peers, mesh[topic])
                for peer in selected_peers:
                    # Add peer to mesh[topic]
                    mesh[topic].append(peer)

                    # Emit GRAFT(topic) control message to peer
                    # TODO: emit message
            if mesh_peers_in_topic > degree_high:
                # Select |mesh[topic]| - D peers from mesh[topic]
                selected_peers = self.select_from_minus(mesh_peers_in_topic - self.degree, mesh[topic], [])
                for peer in selected_peers:
                    # Remove peer from mesh[topic]
                    mesh[topic].remove(peer)

                    # Emit PRUNE(topic) control message to peer
                    # TODO: emit message

    def get_gossipsub_peers(self):
        # TODO: implement
        pass

    def select_from_minus(self, num_to_select, pool, minus):
        """
        Select subset of elements randomly 
        :param num_to_select: number of elements to randomly select
        :param pool: list of items to select from (excluding elements in minus)
        :param minus: elements to be excluded from selection pool
        :return: list of selected elements
        """
        # Create selection pool, which is selection_pool = pool - minus
        selection_pool = None
        if len(minus) > 0:
            # Create a new selection pool by removing elements of minus
            selection_pool = [x for x in pool if x not in minus]
        else:
            # Don't create a new selection_pool if we are not subbing anything
            selection_pool = pool

        # Random selection
        selection = random.sample(selection_pool, num_to_select)

        return selection



    async def fanout_heartbeat(self):
        pass

    async def gossip_heartbeat(self):
        pass

    # RPC handlers

    async def handle_ihave(self, ihave_msg):
        pass

    async def handle_iwant(self, ihave_msg):
        pass

    async def handle_graft(self, ihave_msg):
        pass

    async def handle_prune(self, ihave_msg):
        pass
