import random
import asyncio

from ast import literal_eval
from .pb import rpc_pb2
from .pubsub_router_interface import IPubsubRouter
from .mcache import MessageCache


class GossipSub(IPubsubRouter):
    # pylint: disable=no-member
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-public-methods

    def __init__(self, protocols, degree, degree_low, degree_high, time_to_live, gossip_window=3,
                 gossip_history=5, heartbeat_interval=120):
        # pylint: disable=too-many-arguments
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
        self.mcache = MessageCache(gossip_window, gossip_history)

        # Create heartbeat timer
        self.heartbeat_interval = heartbeat_interval

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
        peer_type = GossipSub.get_peer_type(protocol_id)
        peer_id_str = str(peer_id)
        if peer_type == "gossip":
            self.peers_gossipsub.append(peer_id_str)
        elif peer_type == "flood":
            self.peers_floodsub.append(peer_id_str)

    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """
        peer_id_str = str(peer_id)
        self.peers_to_protocol.remove(peer_id_str)

    async def handle_rpc(self, rpc, sender_peer_id):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        :param rpc: rpc message
        """
        control_message = rpc.control

        # Relay each rpc control  to the appropriate handler
        if control_message.ihave:
            for ihave in control_message.ihave:
                await self.handle_ihave(ihave, sender_peer_id)
        if control_message.iwant:
            for iwant in control_message.iwant:
                await self.handle_iwant(iwant, sender_peer_id)
        if control_message.graft:
            for graft in control_message.graft:
                await self.handle_graft(graft, sender_peer_id)
        if control_message.prune:
            for prune in control_message.prune:
                await self.handle_prune(prune, sender_peer_id)

    async def publish(self, sender_peer_id, rpc_message):
        # pylint: disable=too-many-locals
        """
        Invoked to forward a new message that has been validated.
        """

        packet = rpc_pb2.RPC()
        packet.ParseFromString(rpc_message)
        msg_sender = str(sender_peer_id)

        # Deliver to self if self was origin
        # Note: handle_talk checks if self is subscribed to topics in message
        for message in packet.publish:
            # Add RPC message to cache
            self.mcache.put(message)

            decoded_from_id = message.from_id.decode('utf-8')
            new_packet = rpc_pb2.RPC()
            new_packet.publish.extend([message])
            new_packet_serialized = new_packet.SerializeToString()

            # Deliver to self if needed
            if msg_sender == decoded_from_id and msg_sender == str(self.pubsub.host.get_id()):
                id_in_seen_msgs = (message.seqno, message.from_id)

                if id_in_seen_msgs not in self.pubsub.seen_messages:
                    self.pubsub.seen_messages[id_in_seen_msgs] = 1

                await self.pubsub.handle_talk(message)

            # Deliver to peers
            for topic in message.topicIDs:
                # If topic has floodsub peers, deliver to floodsub peers
                # TODO: This can be done more efficiently. Do it more efficiently.
                floodsub_peers_in_topic = []
                if topic in self.pubsub.peer_topics:
                    for peer in self.pubsub.peer_topics[topic]:
                        if str(peer) in self.peers_floodsub:
                            floodsub_peers_in_topic.append(peer)

                await self.deliver_messages_to_peers(floodsub_peers_in_topic, msg_sender,
                                                     decoded_from_id, new_packet_serialized)

                # If you are subscribed to topic, send to mesh, otherwise send to fanout
                if topic in self.pubsub.my_topics and topic in self.mesh:
                    await self.deliver_messages_to_peers(self.mesh[topic], msg_sender,
                                                         decoded_from_id, new_packet_serialized)
                else:
                    # Send to fanout peers
                    if topic not in self.fanout:
                        # If no peers in fanout, choose some peers from gossipsub peers in topic
                        gossipsub_peers_in_topic = [peer for peer in self.pubsub.peer_topics[topic]
                                                    if peer in self.peers_gossipsub]

                        selected = \
                            GossipSub.select_from_minus(self.degree, gossipsub_peers_in_topic, [])
                        self.fanout[topic] = selected

                    # TODO: Is topic DEFINITELY supposed to be in fanout if we are not subscribed?
                    # I assume there could be short periods between heartbeats where topic may not
                    # be but we should check that this path gets hit appropriately

                    await self.deliver_messages_to_peers(self.fanout[topic], msg_sender,
                                                         decoded_from_id, new_packet_serialized)

    async def join(self, topic):
        # Note: the comments here are the near-exact algorithm description from the spec
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """
        # Create mesh[topic] if it does not yet exist
        if topic not in self.mesh:
            self.mesh[topic] = []

        if topic in self.fanout and len(self.fanout[topic]) == self.degree:
            # If router already has D peers from the fanout peers of a topic
            # TODO: Do we remove all peers from fanout[topic]?

            # Add them to mesh[topic], and notifies them with a
            # GRAFT(topic) control message.
            for peer in self.fanout[topic]:
                self.mesh[topic].append(peer)
                await self.emit_graft(topic, peer)
        else:
            # Otherwise, if there are less than D peers
            # (let this number be x) in the fanout for a topic (or the topic is not in the fanout),
            fanout_size = 0
            if topic in self.fanout:
                fanout_size = len(self.fanout[topic])
                # then it still adds them as above (if there are any)
                for peer in self.fanout[topic]:
                    self.mesh[topic].append(peer)
                    await self.emit_graft(topic, peer)

            if topic in self.peers_gossipsub:
                # TODO: Should we have self.fanout[topic] here or [] (as the minus variable)?
                # Selects the remaining number of peers (D-x) from peers.gossipsub[topic]
                gossipsub_peers_in_topic = [peer for peer in self.pubsub.peer_topics[topic]
                                            if peer in self.peers_gossipsub]
                selected_peers = \
                    GossipSub.select_from_minus(self.degree - fanout_size,
                                                gossipsub_peers_in_topic,
                                                self.fanout[topic] if topic in self.fanout else [])

                # And likewise adds them to mesh[topic] and notifies them with a
                # GRAFT(topic) control message.
                for peer in selected_peers:
                    self.mesh[topic].append(peer)
                    await self.emit_graft(topic, peer)

            # TODO: Do we remove all peers from fanout[topic]?

    async def leave(self, topic):
        # Note: the comments here are the near-exact algorithm description from the spec
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """
        # Notify the peers in mesh[topic] with a PRUNE(topic) message
        for peer in self.mesh[topic]:
            await self.emit_prune(topic, peer)

        # Forget mesh[topic]
        self.mesh.pop(topic, None)

    # Interface Helper Functions
    @staticmethod
    def get_peer_type(protocol_id):
        # TODO: Do this in a better, more efficient way
        if "gossipsub" in protocol_id:
            return "gossip"
        if "floodsub" in protocol_id:
            return "flood"
        return "unknown"

    async def deliver_messages_to_peers(self, peers, msg_sender, origin_id, serialized_packet):
        for peer_id_in_topic in peers:
            # Forward to all peers that are not the
            # message sender and are not the message origin

            if peer_id_in_topic not in (msg_sender, origin_id):
                stream = self.pubsub.peers[peer_id_in_topic]

                # Publish the packet
                await stream.write(serialized_packet)

    # Heartbeat
    async def heartbeat(self):
        """
        Call individual heartbeats.
        Note: the heartbeats are called with awaits because each heartbeat depends on the
        state changes in the preceding heartbeat
        """
        while True:

            await self.mesh_heartbeat()
            await self.fanout_heartbeat()
            await self.gossip_heartbeat()

            await asyncio.sleep(self.heartbeat_interval)

    async def mesh_heartbeat(self):
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.mesh:

            num_mesh_peers_in_topic = len(self.mesh[topic])
            if num_mesh_peers_in_topic < self.degree_low:

                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]
                selected_peers = GossipSub.select_from_minus(self.degree - num_mesh_peers_in_topic,
                                                             self.peers_gossipsub, self.mesh[topic])

                for peer in selected_peers:
                    # Add peer to mesh[topic]
                    self.mesh[topic].append(peer)

                    # Emit GRAFT(topic) control message to peer
                    await self.emit_graft(topic, peer)

            if num_mesh_peers_in_topic > self.degree_high:
                # Select |mesh[topic]| - D peers from mesh[topic]
                selected_peers = GossipSub.select_from_minus(num_mesh_peers_in_topic - self.degree,
                                                             self.mesh[topic], [])
                for peer in selected_peers:
                    # Remove peer from mesh[topic]
                    self.mesh[topic].remove(peer)

                    # Emit PRUNE(topic) control message to peer
                    await self.emit_prune(topic, peer)

    async def fanout_heartbeat(self):
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.fanout:
            # If time since last published > ttl
            # TODO: there's no way time_since_last_publish gets set anywhere yet
            if self.time_since_last_publish[topic] > self.time_to_live:
                # Remove topic from fanout
                self.fanout.remove(topic)
                self.time_since_last_publish.remove(topic)
            else:
                num_fanout_peers_in_topic = len(self.fanout[topic])

                # If |fanout[topic]| < D
                if num_fanout_peers_in_topic < self.degree:
                    # Select D - |fanout[topic]| peers from peers.gossipsub[topic] - fanout[topic]
                    gossipsub_peers_in_topic = [peer for peer in self.pubsub.peer_topics[topic]
                                                if peer in self.peers_gossipsub]
                    selected_peers = \
                        GossipSub.select_from_minus(self.degree - num_fanout_peers_in_topic,
                                                    gossipsub_peers_in_topic, self.fanout[topic])

                    # Add the peers to fanout[topic]
                    self.fanout[topic].extend(selected_peers)

    async def gossip_heartbeat(self):
        # pylint: disable=too-many-nested-blocks
        for topic in self.mesh:
            msg_ids = self.mcache.window(topic)
            if msg_ids:
                # TODO: Make more efficient, possibly using a generator?
                # Get all pubsub peers in a topic and only add them if they are gossipsub peers too
                if topic in self.pubsub.peer_topics:
                    gossipsub_peers_in_topic = [peer for peer in self.pubsub.peer_topics[topic]
                                                if peer in self.peers_gossipsub]

                    # Select D peers from peers.gossipsub[topic]
                    peers_to_emit_ihave_to = \
                        GossipSub.select_from_minus(self.degree, gossipsub_peers_in_topic, [])

                    for peer in peers_to_emit_ihave_to:
                        # TODO: this line is a monster, can hopefully be simplified
                        if (topic not in self.mesh or (peer not in self.mesh[topic]))\
                                and (topic not in self.fanout or (peer not in self.fanout[topic])):
                            msg_ids = [str(msg) for msg in msg_ids]
                            await self.emit_ihave(topic, msg_ids, peer)

        # Do the same for fanout, for all topics not already hit in mesh
        for topic in self.fanout:
            if topic not in self.mesh:
                msg_ids = self.mcache.window(topic)
                if msg_ids:
                    # TODO: Make more efficient, possibly using a generator?
                    # Get all pubsub peers in topic and only add if they are gossipsub peers also
                    if topic in self.pubsub.peer_topics:
                        gossipsub_peers_in_topic = [peer for peer in self.pubsub.peer_topics[topic]
                                                    if peer in self.peers_gossipsub]

                        # Select D peers from peers.gossipsub[topic]
                        peers_to_emit_ihave_to = \
                            GossipSub.select_from_minus(self.degree, gossipsub_peers_in_topic, [])
                        for peer in peers_to_emit_ihave_to:
                            if peer not in self.mesh[topic] and peer not in self.fanout[topic]:

                                msg_ids = [str(msg) for msg in msg_ids]
                                await self.emit_ihave(topic, msg_ids, peer)

        self.mcache.shift()

    @staticmethod
    def select_from_minus(num_to_select, pool, minus):
        """
        Select at most num_to_select subset of elements from the set (pool - minus) randomly.
        :param num_to_select: number of elements to randomly select
        :param pool: list of items to select from (excluding elements in minus)
        :param minus: elements to be excluded from selection pool
        :return: list of selected elements
        """
        # Create selection pool, which is selection_pool = pool - minus
        if minus:
            # Create a new selection pool by removing elements of minus
            selection_pool = [x for x in pool if x not in minus]
        else:
            # Don't create a new selection_pool if we are not subbing anything
            selection_pool = pool

        # If num_to_select > size(selection_pool), then return selection_pool (which has the most
        # possible elements s.t. the number of elements is less than num_to_select)
        if num_to_select > len(selection_pool):
            return selection_pool

        # Random selection
        selection = random.sample(selection_pool, num_to_select)

        return selection

    # RPC handlers

    async def handle_ihave(self, ihave_msg, sender_peer_id):
        """
        Checks the seen set and requests unknown messages with an IWANT message.
        """
        # from_id_bytes = ihave_msg.from_id

        from_id_str = sender_peer_id

        # Get list of all seen (seqnos, from) from the (seqno, from) tuples in seen_messages cache
        seen_seqnos_and_peers = [seqno_and_from
                                 for seqno_and_from in self.pubsub.seen_messages.keys()]

        # Add all unknown message ids (ids that appear in ihave_msg but not in seen_seqnos) to list
        # of messages we want to request
        msg_ids_wanted = [msg_id for msg_id in ihave_msg.messageIDs
                          if literal_eval(msg_id) not in seen_seqnos_and_peers]

        # Request messages with IWANT message
        if msg_ids_wanted:
            await self.emit_iwant(msg_ids_wanted, from_id_str)

    async def handle_iwant(self, iwant_msg, sender_peer_id):
        """
        Forwards all request messages that are present in mcache to the requesting peer.
        """
        from_id_str = sender_peer_id

        msg_ids = [literal_eval(msg) for msg in iwant_msg.messageIDs]
        msgs_to_forward = []
        for msg_id_iwant in msg_ids:
            # Check if the wanted message ID is present in mcache
            msg = self.mcache.get(msg_id_iwant)

            # Cache hit
            if msg:
                # Add message to list of messages to forward to requesting peers
                msgs_to_forward.append(msg)

        # Forward messages to requesting peer
        # Should this just be publishing? No
        # because then the message will forwarded to peers in the topics contained in the messages.
        # We should
        # 1) Package these messages into a single packet
        packet = rpc_pb2.RPC()

        packet.publish.extend(msgs_to_forward)

        # 2) Serialize that packet
        rpc_msg = packet.SerializeToString()

        # 3) Get the stream to this peer
        # TODO: Should we pass in from_id or from_id_str here?
        peer_stream = self.pubsub.peers[from_id_str]

        # 4) And write the packet to the stream
        await peer_stream.write(rpc_msg)

    async def handle_graft(self, graft_msg, sender_peer_id):
        topic = graft_msg.topicID

        from_id_str = sender_peer_id

        # Add peer to mesh for topic
        if topic in self.mesh:
            self.mesh[topic].append(from_id_str)
        else:
            self.mesh[topic] = [from_id_str]

    async def handle_prune(self, prune_msg, sender_peer_id):
        topic = prune_msg.topicID

        from_id_str = sender_peer_id

        # Remove peer from mesh for topic, if peer is in topic
        if topic in self.mesh and from_id_str in self.mesh[topic]:
            self.mesh[topic].remove(from_id_str)

    # RPC emitters

    async def emit_ihave(self, topic, msg_ids, to_peer):
        """
        Emit ihave message, sent to to_peer, for topic and msg_ids
        """

        ihave_msg = rpc_pb2.ControlIHave()
        ihave_msg.messageIDs.extend(msg_ids)
        ihave_msg.topicID = topic

        control_msg = rpc_pb2.ControlMessage()
        control_msg.ihave.extend([ihave_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_iwant(self, msg_ids, to_peer):
        """
        Emit iwant message, sent to to_peer, for msg_ids
        """

        iwant_msg = rpc_pb2.ControlIWant()
        iwant_msg.messageIDs.extend(msg_ids)

        control_msg = rpc_pb2.ControlMessage()
        control_msg.iwant.extend([iwant_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_graft(self, topic, to_peer):
        """
        Emit graft message, sent to to_peer, for topic
        """

        graft_msg = rpc_pb2.ControlGraft()
        graft_msg.topicID = topic

        control_msg = rpc_pb2.ControlMessage()
        control_msg.graft.extend([graft_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_prune(self, topic, to_peer):
        """
        Emit graft message, sent to to_peer, for topic
        """

        prune_msg = rpc_pb2.ControlPrune()
        prune_msg.topicID = topic

        control_msg = rpc_pb2.ControlMessage()
        control_msg.prune.extend([prune_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_control_message(self, control_msg, to_peer):
        # Add control message to packet
        packet = rpc_pb2.RPC()
        packet.control.CopyFrom(control_msg)

        rpc_msg = packet.SerializeToString()

        # Get stream for peer from pubsub
        peer_stream = self.pubsub.peers[to_peer]

        # Write rpc to stream
        await peer_stream.write(rpc_msg)
