from ast import literal_eval
import asyncio
import random
from typing import Any, Dict, Iterable, List, Sequence, Set

from libp2p.peer.id import ID
from libp2p.typing import TProtocol

from .mcache import MessageCache
from .pb import rpc_pb2
from .pubsub import Pubsub
from .pubsub_router_interface import IPubsubRouter


class GossipSub(IPubsubRouter):

    protocols: List[TProtocol]
    pubsub: Pubsub

    degree: int
    degree_high: int
    degree_low: int

    time_to_live: int

    mesh: Dict[str, List[ID]]
    fanout: Dict[str, List[ID]]

    peers_to_protocol: Dict[ID, str]

    time_since_last_publish: Dict[str, int]

    peers_gossipsub: List[ID]
    peers_floodsub: List[ID]

    mcache: MessageCache

    heartbeat_interval: int

    def __init__(
        self,
        protocols: Sequence[TProtocol],
        degree: int,
        degree_low: int,
        degree_high: int,
        time_to_live: int,
        gossip_window: int = 3,
        gossip_history: int = 5,
        heartbeat_interval: int = 120,
    ) -> None:
        self.protocols = list(protocols)
        self.pubsub = None

        # Store target degree, upper degree bound, and lower degree bound
        self.degree = degree
        self.degree_low = degree_low
        self.degree_high = degree_high

        # Store time to live (for topics in fanout)
        self.time_to_live = time_to_live

        # Create topic --> list of peers mappings
        self.mesh = {}
        self.fanout = {}

        # Create peer --> protocol mapping
        self.peers_to_protocol = {}

        # Create topic --> time since last publish map
        self.time_since_last_publish = {}

        self.peers_gossipsub = []
        self.peers_floodsub = []

        # Create message cache
        self.mcache = MessageCache(gossip_window, gossip_history)

        # Create heartbeat timer
        self.heartbeat_interval = heartbeat_interval

    # Interface functions

    def get_protocols(self) -> List[TProtocol]:
        """
        :return: the list of protocols supported by the router
        """
        return self.protocols

    def attach(self, pubsub: Pubsub) -> None:
        """
        Attach is invoked by the PubSub constructor to attach the router to a
        freshly initialized PubSub instance.
        :param pubsub: pubsub instance to attach to
        """
        self.pubsub = pubsub

        # Start heartbeat now that we have a pubsub instance
        # TODO: Start after delay
        asyncio.ensure_future(self.heartbeat())

    def add_peer(self, peer_id: ID, protocol_id: TProtocol) -> None:
        """
        Notifies the router that a new peer has been connected
        :param peer_id: id of peer to add
        :param protocol_id: router protocol the peer speaks, e.g., floodsub, gossipsub
        """

        # Add peer to the correct peer list
        peer_type = GossipSub.get_peer_type(protocol_id)

        self.peers_to_protocol[peer_id] = protocol_id

        if peer_type == "gossip":
            self.peers_gossipsub.append(peer_id)
        elif peer_type == "flood":
            self.peers_floodsub.append(peer_id)

    def remove_peer(self, peer_id: ID) -> None:
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """
        del self.peers_to_protocol[peer_id]

        if peer_id in self.peers_gossipsub:
            self.peers_gossipsub.remove(peer_id)
        if peer_id in self.peers_gossipsub:
            self.peers_floodsub.remove(peer_id)

    async def handle_rpc(self, rpc: rpc_pb2.RPC, sender_peer_id: ID) -> None:
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        :param rpc: RPC message
        :param sender_peer_id: id of the peer who sent the message
        """
        control_message = rpc.control

        # Relay each rpc control message to the appropriate handler
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

    async def publish(self, msg_forwarder: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """
        Invoked to forward a new message that has been validated.
        """
        self.mcache.put(pubsub_msg)

        peers_gen = self._get_peers_to_send(
            pubsub_msg.topicIDs,
            msg_forwarder=msg_forwarder,
            origin=ID(pubsub_msg.from_id),
        )
        rpc_msg = rpc_pb2.RPC(publish=[pubsub_msg])
        for peer_id in peers_gen:
            stream = self.pubsub.peers[peer_id]
            # FIXME: We should add a `WriteMsg` similar to write delimited messages.
            #   Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/master/comm.go#L107
            # TODO: Go use `sendRPC`, which possibly piggybacks gossip/control messages.
            await stream.write(rpc_msg.SerializeToString())

    def _get_peers_to_send(
        self, topic_ids: Iterable[str], msg_forwarder: ID, origin: ID
    ) -> Iterable[ID]:
        """
        Get the eligible peers to send the data to.
        :param msg_forwarder: the peer id of the peer who forwards the message to me.
        :param origin: peer id of the peer the message originate from.
        :return: a generator of the peer ids who we send data to.
        """
        send_to: Set[ID] = set()
        for topic in topic_ids:
            if topic not in self.pubsub.peer_topics:
                continue

            # floodsub peers
            for peer_id in self.pubsub.peer_topics[topic]:
                # FIXME: `gossipsub.peers_floodsub` can be changed to `gossipsub.peers` in go.
                #   This will improve the efficiency when searching for a peer's protocol id.
                if peer_id in self.peers_floodsub:
                    send_to.add(peer_id)

            # gossipsub peers
            in_topic_gossipsub_peers: List[ID] = None
            # TODO: Do we need to check `topic in self.pubsub.my_topics`?
            if topic in self.mesh:
                in_topic_gossipsub_peers = self.mesh[topic]
            else:
                # TODO(robzajac): Is topic DEFINITELY supposed to be in fanout if we are not
                #   subscribed?
                # I assume there could be short periods between heartbeats where topic may not
                # be but we should check that this path gets hit appropriately

                if (topic not in self.fanout) or (len(self.fanout[topic]) == 0):
                    # If no peers in fanout, choose some peers from gossipsub peers in topic.
                    self.fanout[topic] = self._get_in_topic_gossipsub_peers_from_minus(
                        topic, self.degree, []
                    )
                in_topic_gossipsub_peers = self.fanout[topic]
            for peer_id in in_topic_gossipsub_peers:
                send_to.add(peer_id)
        # Excludes `msg_forwarder` and `origin`
        yield from send_to.difference([msg_forwarder, origin])

    async def join(self, topic: str) -> None:
        # Note: the comments here are the near-exact algorithm description from the spec
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """
        if topic in self.mesh:
            return
        # Create mesh[topic] if it does not yet exist
        self.mesh[topic] = []

        topic_in_fanout: bool = topic in self.fanout
        fanout_peers: List[ID] = self.fanout[topic] if topic_in_fanout else []
        fanout_size = len(fanout_peers)
        if not topic_in_fanout or (topic_in_fanout and fanout_size < self.degree):
            # There are less than D peers (let this number be x)
            # in the fanout for a topic (or the topic is not in the fanout).
            # Selects the remaining number of peers (D-x) from peers.gossipsub[topic].
            if topic in self.pubsub.peer_topics:
                selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree - fanout_size, fanout_peers
                )
                # Combine fanout peers with selected peers
                fanout_peers += selected_peers

        # Add fanout peers to mesh and notifies them with a GRAFT(topic) control message.
        for peer in fanout_peers:
            if peer not in self.mesh[topic]:
                self.mesh[topic].append(peer)
                await self.emit_graft(topic, peer)

        if topic_in_fanout:
            del self.fanout[topic]

    async def leave(self, topic: str) -> None:
        # Note: the comments here are the near-exact algorithm description from the spec
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """
        if topic not in self.mesh:
            return
        # Notify the peers in mesh[topic] with a PRUNE(topic) message
        for peer in self.mesh[topic]:
            await self.emit_prune(topic, peer)

        # Forget mesh[topic]
        self.mesh.pop(topic, None)

    # Interface Helper Functions
    @staticmethod
    def get_peer_type(protocol_id: str) -> str:
        # TODO: Do this in a better, more efficient way
        if "gossipsub" in protocol_id:
            return "gossip"
        if "floodsub" in protocol_id:
            return "flood"
        return "unknown"

    async def deliver_messages_to_peers(
        self, peers: List[ID], msg_sender: ID, origin_id: ID, serialized_packet: bytes
    ) -> None:
        for peer_id_in_topic in peers:
            # Forward to all peers that are not the
            # message sender and are not the message origin

            if peer_id_in_topic not in (msg_sender, origin_id):
                stream = self.pubsub.peers[peer_id_in_topic]

                # Publish the packet
                await stream.write(serialized_packet)

    # Heartbeat
    async def heartbeat(self) -> None:
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

    async def mesh_heartbeat(self) -> None:
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.mesh:
            # Skip if no peers have subscribed to the topic
            if topic not in self.pubsub.peer_topics:
                continue

            num_mesh_peers_in_topic = len(self.mesh[topic])
            if num_mesh_peers_in_topic < self.degree_low:
                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]
                selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree - num_mesh_peers_in_topic, self.mesh[topic]
                )

                fanout_peers_not_in_mesh: List[ID] = [
                    peer for peer in selected_peers if peer not in self.mesh[topic]
                ]
                for peer in fanout_peers_not_in_mesh:
                    # Add peer to mesh[topic]
                    self.mesh[topic].append(peer)

                    # Emit GRAFT(topic) control message to peer
                    await self.emit_graft(topic, peer)

            if num_mesh_peers_in_topic > self.degree_high:
                # Select |mesh[topic]| - D peers from mesh[topic]
                selected_peers = GossipSub.select_from_minus(
                    num_mesh_peers_in_topic - self.degree, self.mesh[topic], []
                )
                for peer in selected_peers:
                    # Remove peer from mesh[topic]
                    self.mesh[topic].remove(peer)

                    # Emit PRUNE(topic) control message to peer
                    await self.emit_prune(topic, peer)

    async def fanout_heartbeat(self) -> None:
        # Note: the comments here are the exact pseudocode from the spec
        for topic in self.fanout:
            # If time since last published > ttl
            # TODO: there's no way time_since_last_publish gets set anywhere yet
            if self.time_since_last_publish[topic] > self.time_to_live:
                # Remove topic from fanout
                del self.fanout[topic]
                del self.time_since_last_publish[topic]
            else:
                num_fanout_peers_in_topic = len(self.fanout[topic])

                # If |fanout[topic]| < D
                if num_fanout_peers_in_topic < self.degree:
                    # Select D - |fanout[topic]| peers from peers.gossipsub[topic] - fanout[topic]
                    selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                        topic,
                        self.degree - num_fanout_peers_in_topic,
                        self.fanout[topic],
                    )
                    # Add the peers to fanout[topic]
                    self.fanout[topic].extend(selected_peers)

    async def gossip_heartbeat(self) -> None:
        for topic in self.mesh:
            msg_ids = self.mcache.window(topic)
            if msg_ids:
                # TODO: Make more efficient, possibly using a generator?
                # Get all pubsub peers in a topic and only add them if they are gossipsub peers too
                if topic in self.pubsub.peer_topics:
                    # Select D peers from peers.gossipsub[topic]
                    peers_to_emit_ihave_to = self._get_in_topic_gossipsub_peers_from_minus(
                        topic, self.degree, []
                    )

                    for peer in peers_to_emit_ihave_to:
                        # TODO: this line is a monster, can hopefully be simplified
                        if (
                            topic not in self.mesh or (peer not in self.mesh[topic])
                        ) and (
                            topic not in self.fanout or (peer not in self.fanout[topic])
                        ):
                            msg_id_strs = [str(msg_id) for msg_id in msg_ids]
                            await self.emit_ihave(topic, msg_id_strs, peer)

        # TODO: Refactor and Dedup. This section is the roughly the same as the above.
        # Do the same for fanout, for all topics not already hit in mesh
        for topic in self.fanout:
            if topic not in self.mesh:
                msg_ids = self.mcache.window(topic)
                if msg_ids:
                    # TODO: Make more efficient, possibly using a generator?
                    # Get all pubsub peers in topic and only add if they are gossipsub peers also
                    if topic in self.pubsub.peer_topics:
                        # Select D peers from peers.gossipsub[topic]
                        peers_to_emit_ihave_to = self._get_in_topic_gossipsub_peers_from_minus(
                            topic, self.degree, []
                        )
                        for peer in peers_to_emit_ihave_to:
                            if (
                                peer not in self.mesh[topic]
                                and peer not in self.fanout[topic]
                            ):

                                msg_id_strs = [str(msg) for msg in msg_ids]
                                await self.emit_ihave(topic, msg_id_strs, peer)

        self.mcache.shift()

    @staticmethod
    def select_from_minus(
        num_to_select: int, pool: Sequence[Any], minus: Sequence[Any]
    ) -> List[Any]:
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
            selection_pool: List[Any] = [x for x in pool if x not in minus]
        else:
            # Don't create a new selection_pool if we are not subbing anything
            selection_pool = list(pool)

        # If num_to_select > size(selection_pool), then return selection_pool (which has the most
        # possible elements s.t. the number of elements is less than num_to_select)
        if num_to_select > len(selection_pool):
            return selection_pool

        # Random selection
        selection: List[Any] = random.sample(selection_pool, num_to_select)

        return selection

    def _get_in_topic_gossipsub_peers_from_minus(
        self, topic: str, num_to_select: int, minus: Sequence[ID]
    ) -> List[ID]:
        gossipsub_peers_in_topic = [
            peer_id
            for peer_id in self.pubsub.peer_topics[topic]
            if peer_id in self.peers_gossipsub
        ]
        return self.select_from_minus(
            num_to_select, gossipsub_peers_in_topic, list(minus)
        )

    # RPC handlers

    async def handle_ihave(
        self, ihave_msg: rpc_pb2.ControlIHave, sender_peer_id: ID
    ) -> None:
        """
        Checks the seen set and requests unknown messages with an IWANT message.
        """
        # Get list of all seen (seqnos, from) from the (seqno, from) tuples in seen_messages cache
        seen_seqnos_and_peers = [
            seqno_and_from for seqno_and_from in self.pubsub.seen_messages.keys()
        ]

        # Add all unknown message ids (ids that appear in ihave_msg but not in seen_seqnos) to list
        # of messages we want to request
        # FIXME: Update type of message ID
        msg_ids_wanted: List[Any] = [
            msg_id
            for msg_id in ihave_msg.messageIDs
            if literal_eval(msg_id) not in seen_seqnos_and_peers
        ]

        # Request messages with IWANT message
        if msg_ids_wanted:
            await self.emit_iwant(msg_ids_wanted, sender_peer_id)

    async def handle_iwant(
        self, iwant_msg: rpc_pb2.ControlIWant, sender_peer_id: ID
    ) -> None:
        """
        Forwards all request messages that are present in mcache to the requesting peer.
        """
        # FIXME: Update type of message ID
        # FIXME: Find a better way to parse the msg ids
        msg_ids: List[Any] = [literal_eval(msg) for msg in iwant_msg.messageIDs]
        msgs_to_forward: List[rpc_pb2.Message] = []
        for msg_id_iwant in msg_ids:
            # Check if the wanted message ID is present in mcache
            msg: rpc_pb2.Message = self.mcache.get(msg_id_iwant)

            # Cache hit
            if msg:
                # Add message to list of messages to forward to requesting peers
                msgs_to_forward.append(msg)

        # Forward messages to requesting peer
        # Should this just be publishing? No
        # because then the message will forwarded to peers in the topics contained in the messages.
        # We should
        # 1) Package these messages into a single packet
        packet: rpc_pb2.RPC = rpc_pb2.RPC()

        packet.publish.extend(msgs_to_forward)

        # 2) Serialize that packet
        rpc_msg: bytes = packet.SerializeToString()

        # 3) Get the stream to this peer
        peer_stream = self.pubsub.peers[sender_peer_id]

        # 4) And write the packet to the stream
        await peer_stream.write(rpc_msg)

    async def handle_graft(
        self, graft_msg: rpc_pb2.ControlGraft, sender_peer_id: ID
    ) -> None:
        topic: str = graft_msg.topicID

        # Add peer to mesh for topic
        if topic in self.mesh:
            if sender_peer_id not in self.mesh[topic]:
                self.mesh[topic].append(sender_peer_id)
        else:
            # Respond with PRUNE if not subscribed to the topic
            await self.emit_prune(topic, sender_peer_id)

    async def handle_prune(
        self, prune_msg: rpc_pb2.ControlPrune, sender_peer_id: ID
    ) -> None:
        topic: str = prune_msg.topicID

        # Remove peer from mesh for topic, if peer is in topic
        if topic in self.mesh and sender_peer_id in self.mesh[topic]:
            self.mesh[topic].remove(sender_peer_id)

    # RPC emitters

    async def emit_ihave(self, topic: str, msg_ids: Any, to_peer: ID) -> None:
        """
        Emit ihave message, sent to to_peer, for topic and msg_ids
        """

        ihave_msg: rpc_pb2.ControlIHave = rpc_pb2.ControlIHave()
        ihave_msg.messageIDs.extend(msg_ids)
        ihave_msg.topicID = topic

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.ihave.extend([ihave_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_iwant(self, msg_ids: Any, to_peer: ID) -> None:
        """
        Emit iwant message, sent to to_peer, for msg_ids
        """

        iwant_msg: rpc_pb2.ControlIWant = rpc_pb2.ControlIWant()
        iwant_msg.messageIDs.extend(msg_ids)

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.iwant.extend([iwant_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_graft(self, topic: str, to_peer: ID) -> None:
        """
        Emit graft message, sent to to_peer, for topic
        """

        graft_msg: rpc_pb2.ControlGraft = rpc_pb2.ControlGraft()
        graft_msg.topicID = topic

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.graft.extend([graft_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_prune(self, topic: str, to_peer: ID) -> None:
        """
        Emit graft message, sent to to_peer, for topic
        """

        prune_msg: rpc_pb2.ControlPrune = rpc_pb2.ControlPrune()
        prune_msg.topicID = topic

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.prune.extend([prune_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_control_message(
        self, control_msg: rpc_pb2.ControlMessage, to_peer: ID
    ) -> None:
        # Add control message to packet
        packet: rpc_pb2.RPC = rpc_pb2.RPC()
        packet.control.CopyFrom(control_msg)

        rpc_msg: bytes = packet.SerializeToString()

        # Get stream for peer from pubsub
        peer_stream = self.pubsub.peers[to_peer]

        # Write rpc to stream
        await peer_stream.write(rpc_msg)
