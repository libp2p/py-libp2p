from lru import LRU
from .pb import rpc_pb2
from .pubsub_router_interface import IPubsubRouter


class GossipSub(IPubsubRouter):
    # pylint: disable=no-member

    def __init__(self, protocols, mcache_size=128):
        self.protocols = protocols
        self.pubsub = None

        # Create topic --> list of peers mappings
        self.mesh = {}
        self.fanout = {}

        # Create message cache
        self.mcache = LRU(mcache_size)

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

    def add_peer(self, peer_id, protocol_id):
        """
        Notifies the router that a new peer has been connected
        :param peer_id: id of peer to add
        """

    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """

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

    async def mesh_heartbeat(self):
        pass

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
