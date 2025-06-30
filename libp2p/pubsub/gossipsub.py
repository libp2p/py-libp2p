from ast import (
    literal_eval,
)
from collections import (
    defaultdict,
)
from collections.abc import (
    Iterable,
    Sequence,
)
import logging
import random
import time
from typing import (
    Any,
    DefaultDict,
)

import trio

from libp2p.abc import (
    IPubsubRouter,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
    peer_info_from_bytes,
    peer_info_to_bytes,
)
from libp2p.peer.peerstore import (
    PERMANENT_ADDR_TTL,
)
from libp2p.pubsub import (
    floodsub,
)
from libp2p.tools.async_service import (
    Service,
)

from .exceptions import (
    NoPubsubAttached,
)
from .mcache import (
    MessageCache,
)
from .pb import (
    rpc_pb2,
)
from .pubsub import (
    Pubsub,
)

PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
PROTOCOL_ID_V11 = TProtocol("/meshsub/1.1.0")

logger = logging.getLogger("libp2p.pubsub.gossipsub")


class GossipSub(IPubsubRouter, Service):
    protocols: list[TProtocol]
    pubsub: Pubsub | None

    degree: int
    degree_high: int
    degree_low: int

    time_to_live: int

    mesh: dict[str, set[ID]]
    fanout: dict[str, set[ID]]

    # The protocol peer supports
    peer_protocol: dict[ID, TProtocol]

    time_since_last_publish: dict[str, int]

    mcache: MessageCache

    heartbeat_initial_delay: float
    heartbeat_interval: int

    direct_peers: dict[ID, PeerInfo]
    direct_connect_initial_delay: float
    direct_connect_interval: int

    do_px: bool
    px_peers_count: int
    back_off: dict[str, dict[ID, int]]
    prune_back_off: int
    unsubscribe_back_off: int

    def __init__(
        self,
        protocols: Sequence[TProtocol],
        degree: int,
        degree_low: int,
        degree_high: int,
        direct_peers: Sequence[PeerInfo] | None = None,
        time_to_live: int = 60,
        gossip_window: int = 3,
        gossip_history: int = 5,
        heartbeat_initial_delay: float = 0.1,
        heartbeat_interval: int = 120,
        direct_connect_initial_delay: float = 0.1,
        direct_connect_interval: int = 300,
        do_px: bool = False,
        px_peers_count: int = 16,
        prune_back_off: int = 60,
        unsubscribe_back_off: int = 10,
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
        self.peer_protocol = {}

        # Create message cache
        self.mcache = MessageCache(gossip_window, gossip_history)

        # Create heartbeat timer
        self.heartbeat_initial_delay = heartbeat_initial_delay
        self.heartbeat_interval = heartbeat_interval

        # Create direct peers
        self.direct_peers = dict()
        for direct_peer in direct_peers or []:
            self.direct_peers[direct_peer.peer_id] = direct_peer
        self.direct_connect_interval = direct_connect_interval
        self.direct_connect_initial_delay = direct_connect_initial_delay
        self.time_since_last_publish = {}

        self.do_px = do_px
        self.px_peers_count = px_peers_count
        self.back_off = dict()
        self.prune_back_off = prune_back_off
        self.unsubscribe_back_off = unsubscribe_back_off

    async def run(self) -> None:
        self.manager.run_daemon_task(self.heartbeat)
        if len(self.direct_peers) > 0:
            self.manager.run_daemon_task(self.direct_connect_heartbeat)
        await self.manager.wait_finished()

    # Interface functions

    def get_protocols(self) -> list[TProtocol]:
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

        if len(self.direct_peers) > 0:
            for pi in self.direct_peers:
                self.pubsub.host.get_peerstore().add_addrs(
                    pi, self.direct_peers[pi].addrs, PERMANENT_ADDR_TTL
                )

        logger.debug("attached to pusub")

    def add_peer(self, peer_id: ID, protocol_id: TProtocol | None) -> None:
        """
        Notifies the router that a new peer has been connected.

        :param peer_id: id of peer to add
        :param protocol_id: router protocol the peer speaks, e.g., floodsub, gossipsub
        """
        logger.debug("adding peer %s with protocol %s", peer_id, protocol_id)

        if protocol_id is None:
            raise ValueError("Protocol cannot be None")

        if protocol_id not in (PROTOCOL_ID, floodsub.PROTOCOL_ID):
            # We should never enter here. Becuase the `protocol_id` is registered by
            #   your pubsub instance in multistream-select, but it is not the protocol
            #   that gossipsub supports. In this case, probably we registered gossipsub
            #   to a wrong `protocol_id` in multistream-select, or wrong versions.
            raise ValueError(f"Protocol={protocol_id} is not supported.")
        self.peer_protocol[peer_id] = protocol_id

    def remove_peer(self, peer_id: ID) -> None:
        """
        Notifies the router that a peer has been disconnected.

        :param peer_id: id of peer to remove
        """
        logger.debug("removing peer %s", peer_id)

        for topic in self.mesh:
            self.mesh[topic].discard(peer_id)
        for topic in self.fanout:
            self.fanout[topic].discard(peer_id)

        self.peer_protocol.pop(peer_id, None)

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
        """Invoked to forward a new message that has been validated."""
        self.mcache.put(pubsub_msg)

        peers_gen = self._get_peers_to_send(
            pubsub_msg.topicIDs,
            msg_forwarder=msg_forwarder,
            origin=ID(pubsub_msg.from_id),
        )
        rpc_msg = rpc_pb2.RPC(publish=[pubsub_msg])

        logger.debug("publishing message %s", pubsub_msg)

        for peer_id in peers_gen:
            if self.pubsub is None:
                raise NoPubsubAttached
            if peer_id not in self.pubsub.peers:
                continue
            stream = self.pubsub.peers[peer_id]

            # TODO: Go use `sendRPC`, which possibly piggybacks gossip/control messages.
            await self.pubsub.write_msg(stream, rpc_msg)

        for topic in pubsub_msg.topicIDs:
            self.time_since_last_publish[topic] = int(time.time())

    def _get_peers_to_send(
        self, topic_ids: Iterable[str], msg_forwarder: ID, origin: ID
    ) -> Iterable[ID]:
        """
        Get the eligible peers to send the data to.

        :param msg_forwarder: the peer id of the peer who forwards the message to me.
        :param origin: peer id of the peer the message originate from.
        :return: a generator of the peer ids who we send data to.
        """
        send_to: set[ID] = set()
        for topic in topic_ids:
            if self.pubsub is None:
                raise NoPubsubAttached
            if topic not in self.pubsub.peer_topics:
                continue

            # direct peers
            _direct_peers: set[ID] = {_peer for _peer in self.direct_peers}
            send_to.update(_direct_peers)

            # floodsub peers
            floodsub_peers: set[ID] = {
                peer_id
                for peer_id in self.pubsub.peer_topics[topic]
                if self.peer_protocol[peer_id] == floodsub.PROTOCOL_ID
            }
            send_to.update(floodsub_peers)

            # gossipsub peers
            gossipsub_peers: set[ID] = set()
            if topic in self.mesh:
                gossipsub_peers = self.mesh[topic]
            else:
                # When we publish to a topic that we have not subscribe to, we randomly
                # pick `self.degree` number of peers who have subscribed to the topic
                # and add them as our `fanout` peers.
                topic_in_fanout: bool = topic in self.fanout
                fanout_peers: set[ID] = self.fanout[topic] if topic_in_fanout else set()
                fanout_size = len(fanout_peers)
                if not topic_in_fanout or (
                    topic_in_fanout and fanout_size < self.degree
                ):
                    if topic in self.pubsub.peer_topics:
                        # Combine fanout peers with selected peers
                        fanout_peers.update(
                            self._get_in_topic_gossipsub_peers_from_minus(
                                topic, self.degree - fanout_size, fanout_peers
                            )
                        )
                self.fanout[topic] = fanout_peers
                gossipsub_peers = fanout_peers
            send_to.update(gossipsub_peers)
        # Excludes `msg_forwarder` and `origin`
        yield from send_to.difference([msg_forwarder, origin])

    async def join(self, topic: str) -> None:
        """
        Join notifies the router that we want to receive and forward messages
        in a topic. It is invoked after the subscription announcement.

        :param topic: topic to join
        """
        if self.pubsub is None:
            raise NoPubsubAttached

        logger.debug("joining topic %s", topic)

        if topic in self.mesh:
            return
        # Create mesh[topic] if it does not yet exist
        self.mesh[topic] = set()

        topic_in_fanout: bool = topic in self.fanout
        fanout_peers: set[ID] = set()

        if topic_in_fanout:
            for peer in self.fanout[topic]:
                if self._check_back_off(peer, topic):
                    continue
                fanout_peers.add(peer)

        fanout_size = len(fanout_peers)
        if not topic_in_fanout or (topic_in_fanout and fanout_size < self.degree):
            # There are less than D peers (let this number be x)
            # in the fanout for a topic (or the topic is not in the fanout).
            # Selects the remaining number of peers (D-x) from peers.gossipsub[topic].
            if self.pubsub is not None and topic in self.pubsub.peer_topics:
                selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree - fanout_size, fanout_peers, True
                )
                # Combine fanout peers with selected peers
                fanout_peers.update(selected_peers)

        # Add fanout peers to mesh and notifies them with a GRAFT(topic) control message
        for peer in fanout_peers:
            self.mesh[topic].add(peer)
            await self.emit_graft(topic, peer)

        self.fanout.pop(topic, None)
        self.time_since_last_publish.pop(topic, None)

    async def leave(self, topic: str) -> None:
        # Note: the comments here are the near-exact algorithm description from the spec
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.

        :param topic: topic to leave
        """
        logger.debug("leaving topic %s", topic)

        if topic not in self.mesh:
            return
        # Notify the peers in mesh[topic] with a PRUNE(topic) message
        for peer in self.mesh[topic]:
            await self.emit_prune(topic, peer, self.do_px, True)
            self._add_back_off(peer, topic, True)

        # Forget mesh[topic]
        self.mesh.pop(topic, None)

    async def _emit_control_msgs(
        self,
        peers_to_graft: dict[ID, list[str]],
        peers_to_prune: dict[ID, list[str]],
        peers_to_gossip: dict[ID, dict[str, list[str]]],
    ) -> None:
        graft_msgs: list[rpc_pb2.ControlGraft] = []
        prune_msgs: list[rpc_pb2.ControlPrune] = []
        ihave_msgs: list[rpc_pb2.ControlIHave] = []
        # Starting with GRAFT messages
        for peer, topics in peers_to_graft.items():
            for topic in topics:
                graft_msg: rpc_pb2.ControlGraft = rpc_pb2.ControlGraft(topicID=topic)
                graft_msgs.append(graft_msg)

            # If there are also PRUNE messages to send to this peer
            if peer in peers_to_prune:
                for topic in peers_to_prune[peer]:
                    prune_msg: rpc_pb2.ControlPrune = rpc_pb2.ControlPrune(
                        topicID=topic
                    )
                    prune_msgs.append(prune_msg)
                del peers_to_prune[peer]

            # If there are also IHAVE messages to send to this peer
            if peer in peers_to_gossip:
                for topic in peers_to_gossip[peer]:
                    ihave_msg: rpc_pb2.ControlIHave = rpc_pb2.ControlIHave(
                        messageIDs=peers_to_gossip[peer][topic], topicID=topic
                    )
                    ihave_msgs.append(ihave_msg)
                del peers_to_gossip[peer]

            control_msg = self.pack_control_msgs(ihave_msgs, graft_msgs, prune_msgs)
            await self.emit_control_message(control_msg, peer)

        # Next with PRUNE messages
        for peer, topics in peers_to_prune.items():
            prune_msgs = []
            for topic in topics:
                prune_msg = rpc_pb2.ControlPrune(topicID=topic)
                prune_msgs.append(prune_msg)

            # If there are also IHAVE messages to send to this peer
            if peer in peers_to_gossip:
                ihave_msgs = []
                for topic in peers_to_gossip[peer]:
                    ihave_msg = rpc_pb2.ControlIHave(
                        messageIDs=peers_to_gossip[peer][topic], topicID=topic
                    )
                    ihave_msgs.append(ihave_msg)
                del peers_to_gossip[peer]

            control_msg = self.pack_control_msgs(ihave_msgs, None, prune_msgs)
            await self.emit_control_message(control_msg, peer)

        # Fianlly IHAVE messages
        for peer in peers_to_gossip:
            ihave_msgs = []
            for topic in peers_to_gossip[peer]:
                ihave_msg = rpc_pb2.ControlIHave(
                    messageIDs=peers_to_gossip[peer][topic], topicID=topic
                )
                ihave_msgs.append(ihave_msg)

            control_msg = self.pack_control_msgs(ihave_msgs, None, None)
            await self.emit_control_message(control_msg, peer)

    # Heartbeat
    async def heartbeat(self) -> None:
        """
        Call individual heartbeats.

        Note: the heartbeats are called with awaits because each heartbeat depends on
        the state changes in the preceding heartbeat
        """
        # Start after a delay. Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/01b9825fbee1848751d90a8469e3f5f43bac8466/gossipsub.go#L410  # noqa: E501
        await trio.sleep(self.heartbeat_initial_delay)
        while True:
            # Maintain mesh and keep track of which peers to send GRAFT or PRUNE to
            peers_to_graft, peers_to_prune = self.mesh_heartbeat()
            # Maintain fanout
            self.fanout_heartbeat()
            # Get the peers to send IHAVE to
            peers_to_gossip = self.gossip_heartbeat()
            # Pack(piggyback) GRAFT, PRUNE and IHAVE for the same peer into
            # one control message and send it
            await self._emit_control_msgs(
                peers_to_graft, peers_to_prune, peers_to_gossip
            )

            self.mcache.shift()

            await trio.sleep(self.heartbeat_interval)

    async def direct_connect_heartbeat(self) -> None:
        """
        Connect to direct peers.
        """
        await trio.sleep(self.direct_connect_initial_delay)
        while True:
            for direct_peer in self.direct_peers:
                if self.pubsub is None:
                    raise NoPubsubAttached
                if direct_peer not in self.pubsub.peers:
                    try:
                        await self.pubsub.host.connect(self.direct_peers[direct_peer])
                    except Exception as e:
                        logger.debug(
                            "failed to connect to a direct peer %s: %s",
                            direct_peer,
                            e,
                        )
            await trio.sleep(self.direct_connect_interval)

    def mesh_heartbeat(
        self,
    ) -> tuple[DefaultDict[ID, list[str]], DefaultDict[ID, list[str]]]:
        peers_to_graft: DefaultDict[ID, list[str]] = defaultdict(list)
        peers_to_prune: DefaultDict[ID, list[str]] = defaultdict(list)
        for topic in self.mesh:
            if self.pubsub is None:
                raise NoPubsubAttached
            # Skip if no peers have subscribed to the topic
            if topic not in self.pubsub.peer_topics:
                continue

            num_mesh_peers_in_topic = len(self.mesh[topic])
            if num_mesh_peers_in_topic < self.degree_low:
                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]  # noqa: E501
                selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree - num_mesh_peers_in_topic, self.mesh[topic], True
                )

                for peer in selected_peers:
                    # Add peer to mesh[topic]
                    self.mesh[topic].add(peer)

                    # Emit GRAFT(topic) control message to peer
                    peers_to_graft[peer].append(topic)

            if num_mesh_peers_in_topic > self.degree_high:
                # Select |mesh[topic]| - D peers from mesh[topic]
                selected_peers = self.select_from_minus(
                    num_mesh_peers_in_topic - self.degree, self.mesh[topic], set()
                )
                for peer in selected_peers:
                    # Remove peer from mesh[topic]
                    self.mesh[topic].discard(peer)

                    # Emit PRUNE(topic) control message to peer
                    peers_to_prune[peer].append(topic)
        return peers_to_graft, peers_to_prune

    def _handle_topic_heartbeat(
        self,
        topic: str,
        current_peers: set[ID],
        is_fanout: bool = False,
        peers_to_gossip: DefaultDict[ID, dict[str, list[str]]] | None = None,
    ) -> tuple[set[ID], bool]:
        """
        Helper method to handle heartbeat for a single topic,
        supporting both fanout and gossip.

        :param topic: The topic to handle
        :param current_peers: Current set of peers in the topic
        :param is_fanout: Whether this is a fanout topic (affects expiration check)
        :param peers_to_gossip: Optional dictionary to store peers to gossip to
        :return: Tuple of (updated_peers, should_remove_topic)
        """
        if self.pubsub is None:
            raise NoPubsubAttached

        # Skip if no peers have subscribed to the topic
        if topic not in self.pubsub.peer_topics:
            return current_peers, False

        # For fanout topics, check if we should remove the topic
        if is_fanout:
            if self.time_since_last_publish.get(topic, 0) + self.time_to_live < int(
                time.time()
            ):
                return set(), True

        # Check if peers are still in the topic and remove the ones that are not
        in_topic_peers: set[ID] = {
            peer for peer in current_peers if peer in self.pubsub.peer_topics[topic]
        }

        # If we need more peers to reach target degree
        if len(in_topic_peers) < self.degree:
            # Select additional peers from peers.gossipsub[topic]
            selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                topic, self.degree - len(in_topic_peers), in_topic_peers, True
            )
            # Add the selected peers
            in_topic_peers.update(selected_peers)

        # Handle gossip if requested
        if peers_to_gossip is not None:
            msg_ids = self.mcache.window(topic)
            if msg_ids:
                # Select D peers from peers.gossipsub[topic] excluding current peers
                peers_to_emit_ihave_to = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree, current_peers, True
                )
                msg_id_strs = [str(msg_id) for msg_id in msg_ids]
                for peer in peers_to_emit_ihave_to:
                    peers_to_gossip[peer][topic] = msg_id_strs

        return in_topic_peers, False

    def fanout_heartbeat(self) -> None:
        """
        Maintain fanout topics by:
        1. Removing expired topics
        2. Removing peers that are no longer in the topic
        3. Adding new peers if needed to maintain the target degree
        """
        for topic in list(self.fanout):
            updated_peers, should_remove = self._handle_topic_heartbeat(
                topic, self.fanout[topic], is_fanout=True
            )
            if should_remove:
                del self.fanout[topic]
            else:
                self.fanout[topic] = updated_peers

    def gossip_heartbeat(self) -> DefaultDict[ID, dict[str, list[str]]]:
        peers_to_gossip: DefaultDict[ID, dict[str, list[str]]] = defaultdict(dict)

        # Handle mesh topics
        for topic in self.mesh:
            self._handle_topic_heartbeat(
                topic, self.mesh[topic], peers_to_gossip=peers_to_gossip
            )

        # Handle fanout topics that aren't in mesh
        for topic in self.fanout:
            if topic not in self.mesh:
                self._handle_topic_heartbeat(
                    topic, self.fanout[topic], peers_to_gossip=peers_to_gossip
                )

        return peers_to_gossip

    @staticmethod
    def select_from_minus(
        num_to_select: int, pool: Iterable[Any], minus: Iterable[Any]
    ) -> list[Any]:
        """
        Select at most num_to_select subset of elements from the set
        (pool - minus) randomly.
        :param num_to_select: number of elements to randomly select
        :param pool: list of items to select from (excluding elements in minus)
        :param minus: elements to be excluded from selection pool
        :return: list of selected elements
        """
        # Create selection pool, which is selection_pool = pool - minus
        if minus:
            # Create a new selection pool by removing elements of minus
            selection_pool: list[Any] = [x for x in pool if x not in minus]
        else:
            # Don't create a new selection_pool if we are not subbing anything
            selection_pool = list(pool)

        # If num_to_select > size(selection_pool), then return selection_pool (which has
        # the most possible elements s.t. the number of elements is less than
        # num_to_select)
        if num_to_select >= len(selection_pool):
            return selection_pool

        # Random selection
        selection: list[Any] = random.sample(selection_pool, num_to_select)

        return selection

    def _get_in_topic_gossipsub_peers_from_minus(
        self,
        topic: str,
        num_to_select: int,
        minus: Iterable[ID],
        backoff_check: bool = False,
    ) -> list[ID]:
        if self.pubsub is None:
            raise NoPubsubAttached
        gossipsub_peers_in_topic = {
            peer_id
            for peer_id in self.pubsub.peer_topics[topic]
            if self.peer_protocol[peer_id] == PROTOCOL_ID
        }
        if backoff_check:
            # filter out peers that are in back off for this topic
            gossipsub_peers_in_topic = {
                peer_id
                for peer_id in gossipsub_peers_in_topic
                if self._check_back_off(peer_id, topic) is False
            }
        return self.select_from_minus(num_to_select, gossipsub_peers_in_topic, minus)

    def _add_back_off(
        self, peer: ID, topic: str, is_unsubscribe: bool, backoff_duration: int = 0
    ) -> None:
        """
        Add back off for a peer in a topic.
        :param peer: peer to add back off for
        :param topic: topic to add back off for
        :param is_unsubscribe: whether this is an unsubscribe operation
        :param backoff_duration: duration of back off in seconds, if 0, use default
        """
        if topic not in self.back_off:
            self.back_off[topic] = dict()

        backoff_till = int(time.time())
        if backoff_duration > 0:
            backoff_till += backoff_duration
        else:
            if is_unsubscribe:
                backoff_till += self.unsubscribe_back_off
            else:
                backoff_till += self.prune_back_off

        if peer not in self.back_off[topic]:
            self.back_off[topic][peer] = backoff_till
        else:
            self.back_off[topic][peer] = max(self.back_off[topic][peer], backoff_till)

    def _check_back_off(self, peer: ID, topic: str) -> bool:
        """
        Check if a peer is in back off for a topic and cleanup expired back off entries.
        :param peer: peer to check
        :param topic: topic to check
        :return: True if the peer is in back off, False otherwise
        """
        if topic not in self.back_off or peer not in self.back_off[topic]:
            return False
        if self.back_off[topic].get(peer, 0) > int(time.time()):
            return True
        else:
            del self.back_off[topic][peer]
            return False

    async def _do_px(self, px_peers: list[rpc_pb2.PeerInfo]) -> None:
        if len(px_peers) > self.px_peers_count:
            px_peers = px_peers[: self.px_peers_count]

        for peer in px_peers:
            peer_id: ID = ID(peer.peerID)

            if self.pubsub and peer_id in self.pubsub.peers:
                continue

            try:
                peer_info = peer_info_from_bytes(peer.signedPeerRecord)
                try:
                    if self.pubsub is None:
                        raise NoPubsubAttached
                    await self.pubsub.host.connect(peer_info)
                except Exception as e:
                    logger.warning(
                        "failed to connect to px peer %s: %s",
                        peer_id,
                        e,
                    )
                    continue
            except Exception as e:
                logger.warning(
                    "failed to parse peer info from px peer %s: %s",
                    peer_id,
                    e,
                )
                continue

    # RPC handlers

    async def handle_ihave(
        self, ihave_msg: rpc_pb2.ControlIHave, sender_peer_id: ID
    ) -> None:
        """Checks the seen set and requests unknown messages with an IWANT message."""
        if self.pubsub is None:
            raise NoPubsubAttached
        # Get list of all seen (seqnos, from) from the (seqno, from) tuples in
        # seen_messages cache
        seen_seqnos_and_peers = [
            seqno_and_from for seqno_and_from in self.pubsub.seen_messages.cache.keys()
        ]

        # Add all unknown message ids (ids that appear in ihave_msg but not in
        # seen_seqnos) to list of messages we want to request
        # FIXME: Update type of message ID
        msg_ids_wanted: list[Any] = [
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
        Forwards all request messages that are present in mcache to the
        requesting peer.
        """
        # FIXME: Update type of message ID
        # FIXME: Find a better way to parse the msg ids
        msg_ids: list[Any] = [literal_eval(msg) for msg in iwant_msg.messageIDs]
        msgs_to_forward: list[rpc_pb2.Message] = []
        for msg_id_iwant in msg_ids:
            # Check if the wanted message ID is present in mcache
            msg: rpc_pb2.Message | None = self.mcache.get(msg_id_iwant)

            # Cache hit
            if msg:
                # Add message to list of messages to forward to requesting peers
                msgs_to_forward.append(msg)

        # Forward messages to requesting peer
        # Should this just be publishing? No, because then the message will forwarded to
        # peers in the topics contained in the messages.
        # We should
        # 1) Package these messages into a single packet
        packet: rpc_pb2.RPC = rpc_pb2.RPC()

        packet.publish.extend(msgs_to_forward)

        if self.pubsub is None:
            raise NoPubsubAttached

        # 3) Get the stream to this peer
        if sender_peer_id not in self.pubsub.peers:
            logger.debug(
                "Fail to responed to iwant request from %s: peer record not exist",
                sender_peer_id,
            )
            return
        peer_stream = self.pubsub.peers[sender_peer_id]

        # 4) And write the packet to the stream
        await self.pubsub.write_msg(peer_stream, packet)

    async def handle_graft(
        self, graft_msg: rpc_pb2.ControlGraft, sender_peer_id: ID
    ) -> None:
        topic: str = graft_msg.topicID

        # Add peer to mesh for topic
        if topic in self.mesh:
            for direct_peer in self.direct_peers:
                if direct_peer == sender_peer_id:
                    logger.warning(
                        "GRAFT: ignoring request from direct peer %s", sender_peer_id
                    )
                    await self.emit_prune(topic, sender_peer_id, False, False)
                    return

            if self._check_back_off(sender_peer_id, topic):
                logger.warning(
                    "GRAFT: ignoring request from %s, back off until %d",
                    sender_peer_id,
                    self.back_off[topic][sender_peer_id],
                )
                self._add_back_off(sender_peer_id, topic, False)
                await self.emit_prune(topic, sender_peer_id, False, False)
                return

            if sender_peer_id not in self.mesh[topic]:
                self.mesh[topic].add(sender_peer_id)
        else:
            # Respond with PRUNE if not subscribed to the topic
            await self.emit_prune(topic, sender_peer_id, self.do_px, False)

    async def handle_prune(
        self, prune_msg: rpc_pb2.ControlPrune, sender_peer_id: ID
    ) -> None:
        topic: str = prune_msg.topicID
        backoff_till: int = prune_msg.backoff
        px_peers: list[rpc_pb2.PeerInfo] = []
        for peer in prune_msg.peers:
            px_peers.append(peer)

        # Remove peer from mesh for topic
        if topic in self.mesh:
            if backoff_till > 0:
                self._add_back_off(sender_peer_id, topic, False, backoff_till)
            else:
                self._add_back_off(sender_peer_id, topic, False)

            self.mesh[topic].discard(sender_peer_id)

        if px_peers:
            await self._do_px(px_peers)

    # RPC emitters

    def pack_control_msgs(
        self,
        ihave_msgs: list[rpc_pb2.ControlIHave] | None,
        graft_msgs: list[rpc_pb2.ControlGraft] | None,
        prune_msgs: list[rpc_pb2.ControlPrune] | None,
    ) -> rpc_pb2.ControlMessage:
        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        if ihave_msgs:
            control_msg.ihave.extend(ihave_msgs)
        if graft_msgs:
            control_msg.graft.extend(graft_msgs)
        if prune_msgs:
            control_msg.prune.extend(prune_msgs)
        return control_msg

    async def emit_ihave(self, topic: str, msg_ids: Any, to_peer: ID) -> None:
        """Emit ihave message, sent to to_peer, for topic and msg_ids."""
        ihave_msg: rpc_pb2.ControlIHave = rpc_pb2.ControlIHave()
        ihave_msg.messageIDs.extend(msg_ids)
        ihave_msg.topicID = topic

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.ihave.extend([ihave_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_iwant(self, msg_ids: Any, to_peer: ID) -> None:
        """Emit iwant message, sent to to_peer, for msg_ids."""
        iwant_msg: rpc_pb2.ControlIWant = rpc_pb2.ControlIWant()
        iwant_msg.messageIDs.extend(msg_ids)

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.iwant.extend([iwant_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_graft(self, topic: str, id: ID) -> None:
        """Emit graft message, sent to to_peer, for topic."""
        graft_msg: rpc_pb2.ControlGraft = rpc_pb2.ControlGraft()
        graft_msg.topicID = topic

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.graft.extend([graft_msg])

        await self.emit_control_message(control_msg, id)

    async def emit_prune(
        self, topic: str, to_peer: ID, do_px: bool, is_unsubscribe: bool
    ) -> None:
        """Emit graft message, sent to to_peer, for topic."""
        prune_msg: rpc_pb2.ControlPrune = rpc_pb2.ControlPrune()
        prune_msg.topicID = topic

        back_off_duration = self.prune_back_off
        if is_unsubscribe:
            back_off_duration = self.unsubscribe_back_off

        prune_msg.backoff = back_off_duration

        if do_px:
            exchange_peers = self._get_in_topic_gossipsub_peers_from_minus(
                topic, self.px_peers_count, [to_peer]
            )
            for peer in exchange_peers:
                if self.pubsub is None:
                    raise NoPubsubAttached
                peer_info = self.pubsub.host.get_peerstore().peer_info(peer)
                signed_peer_record: rpc_pb2.PeerInfo = rpc_pb2.PeerInfo()
                signed_peer_record.peerID = peer.to_bytes()
                signed_peer_record.signedPeerRecord = peer_info_to_bytes(peer_info)
                prune_msg.peers.append(signed_peer_record)

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.prune.extend([prune_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_control_message(
        self, control_msg: rpc_pb2.ControlMessage, to_peer: ID
    ) -> None:
        if self.pubsub is None:
            raise NoPubsubAttached
        # Add control message to packet
        packet: rpc_pb2.RPC = rpc_pb2.RPC()
        packet.control.CopyFrom(control_msg)

        # Get stream for peer from pubsub
        if to_peer not in self.pubsub.peers:
            logger.debug(
                "Fail to emit control message to %s: peer record not exist", to_peer
            )
            return
        peer_stream = self.pubsub.peers[to_peer]

        # Write rpc to stream
        await self.pubsub.write_msg(peer_stream, packet)
