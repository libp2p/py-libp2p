import random
import asyncio

from aio_timers import Timer
from lru import LRU
from .pb import rpc_pb2
from .pubsub_router_interface import IPubsubRouter


class GossipSub(IPubsubRouter):
    # pylint: disable=no-member

    def __init__(self, protocols, degree, degree_low, degree_high, time_to_live, mcache_size=128,
                 heartbeat_interval=120):
        self.protocols = protocols
        self.pubsub = None

        # Store target degree, upper degree bound, and lower degree bound
        self.degree = degree
        self.degree_high = degree_high
        self.degree_low = degree_low

        # Store time to live (for topics in fanout)
        self.time_to_live = time_to_live

        # Create topic --> list of peers mappings
        self.mesh = {}
        self.fanout = {}

        # Create topic --> time since last publish map
        self.time_since_last_publish = {}

        self.peers_gossipsub = []
        self.peers_floodsub = []

        # Create message cache
        self.mcache = LRU(mcache_size)

        # Create heartbeat timer
        self.heartbeat_interval = heartbeat_interval
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
        # Add peer to the correct peer list
        peer_type = self.get_peer_type(protocol_id)
        if peer_type == "gossip":
            self.peers_gossipsub.append(peer_id)
        elif peer_type == "flood":
            self.peers_floodsub.append(peer_id)

    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """
        self.peers_to_protocol.remove(peer_id)

    async def handle_rpc(self, rpc):
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
        packet = rpc_pb2.RPC()
        packet.ParseFromString(rpc_message)
        msg_sender = str(sender_peer_id)
        # Deliver to self if self was origin
        # Note: handle_talk checks if self is subscribed to topics in message
        for message in packet.publish:
            decoded_from_id = message.from_id.decode('utf-8')
            # Deliver to self if needed
            if msg_sender == decoded_from_id and msg_sender == str(self.pubsub.host.get_id()):
                await self.pubsub.handle_talk(message)

            # Deliver to peers
            for topic in message.topicIDs:
                # If topic has floodsub peers, deliver to floodsub peers
                if topic in self.peers.floodsub:
                    await self.deliver_messages_to_peers(self.peers_floodsub[topic], msg_sender, decoded_from_id)

                # If you are subscribed to topic, send to mesh, otherwise send to fanout
                if topic in self.my_topics:
                    await self.deliver_messages_to_peers(self.mesh[topic], msg_sender, decoded_from_id)
                else:
                    await self.deliver_messages_to_peers(self.fanout[topic], msg_sender, decoded_from_id)

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

    # Interface Helper Functions

    def get_peer_type(self, protocol_id):
        # TODO: Do this in a better, more efficient way
        if "gossipsub" in protocol_id:
            return "gossip"
        elif "floodsub" in protocol_id:
            return "flood"
        else:
            return "unknown"

    async def deliver_messages_to_peers(self, peers, msg_sender, origin_id):
        for peer_id_in_topic in peers:
            # Forward to all known peers in the topic that are not the
            # message sender and are not the message origin
            if peer_id_in_topic not in (msg_sender, origin_id):
                stream = self.pubsub.peers[peer_id_in_topic]
                # Create new packet with just publish message
                new_packet = rpc_pb2.RPC()
                new_packet.publish.extend([message])

                # Publish the packet
                await stream.write(new_packet.SerializeToString())

    # Heartbeat
    async def heartbeat(self):
        """
        Call individual heartbeats.
        Note: the heartbeats are called with awaits because each heartbeat depends on the
        state changes in the preceding heartbeat
        """
        await self.mesh_heartbeat()
        await self.fanout_heartbeat()
        await self.gossip_heartbeat()

        # Restart timer
        self.heartbeat_timer = Timer(self.heartbeat_interval, self.heartbeat)

        # TODO: Check if this is right way to use timer
        asyncio.ensure_future(self.heartbeat_timer.wait())

    async def mesh_heartbeat(self):
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.mesh:
            num_mesh_peers_in_topic = len(self.mesh[topic])
            if num_mesh_peers_in_topic < self.degree_low:
                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]
                selected_peers = self.select_from_minus(self.degree - num_mesh_peers_in_topic, \
                    self.peers_gossipsub, self.mesh[topic])

                for peer in selected_peers:
                    # Add peer to mesh[topic]
                    self.mesh[topic].append(peer)

                    # Emit GRAFT(topic) control message to peer
                    await self.emit_graft(topic)

            if num_mesh_peers_in_topic > self.degree_high:
                # Select |mesh[topic]| - D peers from mesh[topic]
                selected_peers = self.select_from_minus(num_mesh_peers_in_topic - self.degree, self.mesh[topic], [])
                for peer in selected_peers:
                    # Remove peer from mesh[topic]
                    self.mesh[topic].remove(peer)

                    # Emit PRUNE(topic) control message to peer
                    await self.emit_prune(topic)

    async def fanout_heartbeat(self):
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.fanout:
            # If time since last published > ttl
            if self.time_since_last_publish[topic] > self.time_to_live:
                # Remove topic from fanout
                self.fanout.remove(topic)
                self.time_since_last_publish.remove(topic)
            else:
                num_fanout_peers_in_topic = len(self.fanout[topic])
                # If |fanout[topic]| < D
                if num_fanout_peers_in_topic < self.degree:
                    # Select D - |fanout[topic]| peers from peers.gossipsub[topic] - fanout[topic]
                    selected_peers = self.select_from_minus(self.degree - num_fanout_peers_in_topic, self.peers_gossipsub[topic], self.fanout[topic])

                    # Add the peers to fanout[topic]
                    self.fanout[topic].extend(selected_peers)


    async def gossip_heartbeat(self):
        """
        for each topic in mesh+fanout:
          let mids be mcache.window[topic]
          if mids is not empty:
            select D peers from peers.gossipsub[topic]
            for each peer not in mesh[topic] or fanout[topic]
              emit IHAVE(mids)

        shift the mcache
        """
        pass

    def select_from_minus(self, num_to_select, pool, minus):
        """
        Select subset of elements from the set (pool - minus) randomly 
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

    # RPC handlers

    async def handle_ihave(self, ihave_msg):
        pass

    async def handle_iwant(self, iwant_msg):
        pass

    async def handle_graft(self, graft_msg):
        topic = graft_msg.topicID

        # TODO: I think from_id needs to be gotten some other way because ControlMessage
        # does not have from_id attribute
        # IMPT: go does use this in a similar way: https://github.com/libp2p/go-libp2p-pubsub/blob/master/gossipsub.go#L97
        # but go seems to do RPC.from rather than getting the from in the message itself
        from_id_bytes = graft_msg.from_id

        # TODO: convert bytes to string properly, is this proper?
        from_id_str = from_id_bytes.decode()

        # Add peer to mesh for topic
        if topic in self.mesh:
            self.mesh[topic].append(from_id_str)
        else:
            self.mesh[topic] = [from_id_str]

    async def handle_prune(self, prune_msg):
        topic = prune_msg.topicID

        # TODO: I think from_id needs to be gotten some other way because ControlMessage
        # does not have from_id attribute
        # IMPT: go does use this in a similar way: https://github.com/libp2p/go-libp2p-pubsub/blob/master/gossipsub.go#L97
        # but go seems to do RPC.from rather than getting the from in the message itself
        from_id_bytes = prune_msg.from_id

        # TODO: convert bytes to string properly, is this proper?
        from_id_str = from_id_bytes.decode()

        # Remove peer from mesh for topic, if peer is in topic
        if topic in self.mesh and from_id_str in self.mesh[topic]:
            self.mesh[topic].remove(from_id_str)

    # RPC emitters

    async def emit_ihave(self, topic, msg_ids, to_peer):
        """
        Emit ihave message, sent to to_peer, for topic and msg_ids
        """
        ihave_msg = rpc_pb2.ControlIHave(
            topicID=topic,
            messageIDs=msg_ids
            )
        control_msg = rpc_pb2.ControlMessage(
            ihave=[ihave_msg],
            iwant=[],
            graft=[],
            prune=[]
            )

        await emit_control_message(control_msg, to_peer)

    async def emit_iwant(self, msg_ids, to_peer):
        """
        Emit iwant message, sent to to_peer, for msg_ids
        """
        iwant_msg = rpc_pb2.ControlIWant(
            messageIDs=msg_ids
            )
        control_msg = rpc_pb2.ControlMessage(
            ihave=[],
            iwant=[iwant_msg],
            graft=[],
            prune=[]
            )

        await emit_control_message(control_msg, to_peer)

    async def emit_graft(self, topic, to_peer):
        """
        Emit graft message, sent to to_peer, for topic
        """
        graft_msg = rpc_pb2.ControlGraft(
            topicID=topic,
            )
        control_msg = rpc_pb2.ControlMessage(
            ihave=[],
            iwant=[],
            graft=[graft_msg],
            prune=[]
            )

        await emit_control_message(control_msg, to_peer)

    async def emit_prune(self, topic, to_peer):
        """
        Emit graft message, sent to to_peer, for topic
        """
        prune_msg = rpc_pb2.ControlPrune(
            topicID=topic,
            )
        control_msg = rpc_pb2.ControlMessage(
            ihave=[],
            iwant=[],
            graft=[],
            prune=[prune_msg]
            )

        await emit_control_message(control_msg, to_peer)

    async def emit_control_message(self, control_msg, to_peer):
        packet = rpc_pb2.RPC()

        # Add control message to packet
        packet.control.extend([control_msg])
        rpc_msg = packet.SerializeToString()

        # Get stream for peer from pubsub
        peer_stream = self.pubsub.peers[to_peer]

        # Write rpc to stream
        await peer_stream.write(rpc_msg)
