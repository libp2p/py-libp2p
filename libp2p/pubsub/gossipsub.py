from collections import (
    defaultdict,
)
from collections.abc import (
    Awaitable,
    Callable,
    Iterable,
    Sequence,
)
import logging
import random
import statistics
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
    MessageID,
    TProtocol,
)
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import (
    PERMANENT_ADDR_TTL,
    env_to_send_in_RPC,
)
from libp2p.pubsub import (
    floodsub,
)
from libp2p.pubsub.utils import maybe_consume_signed_record
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
from .score import (
    PeerScorer,
    ScoreParams,
)
from .utils import (
    parse_message_id_safe,
    safe_parse_message_id,
)

PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
PROTOCOL_ID_V11 = TProtocol("/meshsub/1.1.0")
PROTOCOL_ID_V12 = TProtocol("/meshsub/1.2.0")
PROTOCOL_ID_V13 = TProtocol("/meshsub/1.3.0")
PROTOCOL_ID_V14 = TProtocol("/meshsub/1.4.0")
PROTOCOL_ID_V20 = TProtocol("/meshsub/2.0.0")

logger = logging.getLogger(__name__)


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

    # Gossipsub v1.2 features
    dont_send_message_ids: dict[ID, set[bytes]]
    max_idontwant_messages: (
        int  # Maximum number of message IDs to track per peer in IDONTWANT lists
    )

    # Gossipsub v2.0 adaptive features
    adaptive_gossip_enabled: bool
    network_health_score: float  # 0.0 (poor) to 1.0 (excellent)
    adaptive_degree_low: int  # Dynamic lower bound for mesh degree
    adaptive_degree_high: int  # Dynamic upper bound for mesh degree
    gossip_factor: float  # Dynamic gossip factor
    last_health_update: int  # Timestamp of last health score update

    # Security features
    spam_protection_enabled: bool
    message_rate_limits: dict[ID, dict[str, list[float]]]  # peer -> topic -> timestamps
    max_messages_per_topic_per_second: float
    equivocation_detection: dict[
        tuple[bytes, bytes], rpc_pb2.Message
    ]  # (seqno, from) -> first_msg
    eclipse_protection_enabled: bool
    min_mesh_diversity_ips: int  # Minimum number of different IPs in mesh

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
        score_params: ScoreParams | None = None,
        max_idontwant_messages: int = 10,
        adaptive_gossip_enabled: bool = True,
        spam_protection_enabled: bool = True,
        max_messages_per_topic_per_second: float = 10.0,
        eclipse_protection_enabled: bool = True,
        min_mesh_diversity_ips: int = 3,
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
        self.heartbeat_interval_base = heartbeat_interval  # For adaptive adjustment

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

        # Scoring
        self.scorer: PeerScorer | None = PeerScorer(score_params or ScoreParams())
        # Gossipsub v1.2 features
        self.dont_send_message_ids = dict()
        self.max_idontwant_messages = max_idontwant_messages

        # Gossipsub v2.0 adaptive features
        self.adaptive_gossip_enabled = adaptive_gossip_enabled
        self.network_health_score = 1.0  # Start optimistic
        self.adaptive_degree_low = degree_low
        self.adaptive_degree_high = degree_high
        self.gossip_factor = 0.25  # Default gossip factor
        self.last_health_update = int(time.time())

        # Enhanced v1.4 adaptive metrics
        self.message_delivery_success_rate = 1.0
        self.average_peer_score = 0.0
        self.mesh_stability_score = 1.0
        self.connection_churn_rate = 0.0
        self.last_metrics_update = int(time.time())

        # Tracking for adaptive calculations
        self.recent_message_deliveries: dict[str, list[float]] = defaultdict(list)
        self.recent_peer_connections: list[float] = []
        self.recent_peer_disconnections: list[float] = []

        # Security features
        self.spam_protection_enabled = spam_protection_enabled
        self.message_rate_limits = defaultdict(lambda: defaultdict(list))
        self.max_messages_per_topic_per_second = max_messages_per_topic_per_second
        self.equivocation_detection = {}
        self.eclipse_protection_enabled = eclipse_protection_enabled
        self.min_mesh_diversity_ips = min_mesh_diversity_ips

        # Extensions support (v1.3+)
        self.extension_handlers: dict[str, Callable[[bytes, ID], Awaitable[None]]] = {}

        # Rate limiting for v1.4 features
        self.iwant_request_limits: dict[ID, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.ihave_message_limits: dict[ID, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.graft_flood_tracking: dict[ID, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        # v1.4 rate limiting parameters
        self.max_iwant_requests_per_second: float = 10.0
        self.max_ihave_messages_per_second: float = 10.0
        self.graft_flood_threshold: float = 10.0  # seconds

        # v1.4 adaptive gossip parameters
        self.opportunistic_graft_threshold: float = 0.5

    def supports_scoring(self, peer_id: ID) -> bool:
        """
        Check if peer supports Gossipsub v1.1+ scoring features.

        :param peer_id: The peer to check
        :return: True if peer supports v1.1+ features, False otherwise
        """
        return self.peer_protocol.get(peer_id) in (
            PROTOCOL_ID_V11,
            PROTOCOL_ID_V12,
            PROTOCOL_ID_V13,
            PROTOCOL_ID_V14,
            PROTOCOL_ID_V20,
        )

    def supports_v20_features(self, peer_id: ID) -> bool:
        """
        Check if peer supports Gossipsub v2.0 features.

        :param peer_id: The peer to check
        :return: True if peer supports v2.0 features, False otherwise
        """
        return self.peer_protocol.get(peer_id) == PROTOCOL_ID_V20

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

    def supports_protocol_feature(self, peer_id: ID, feature: str) -> bool:
        """
        Check if a peer supports a specific protocol feature based on its
        supported protocol versions.

        :param peer_id: ID of the peer to check
        :param feature: Feature name to check support for
        :return: True if the peer supports the feature, False otherwise
        """
        if peer_id not in self.peer_protocol:
            return False

        protocol = self.peer_protocol[peer_id]

        # Define feature support by protocol version
        if feature == "px":  # Peer Exchange
            return protocol in (
                PROTOCOL_ID_V11,
                PROTOCOL_ID_V12,
                PROTOCOL_ID_V13,
                PROTOCOL_ID_V14,
            )
        elif feature == "idontwant":  # IDONTWANT message
            return protocol in (PROTOCOL_ID_V12, PROTOCOL_ID_V13, PROTOCOL_ID_V14)
        elif feature == "extensions":  # Extensions control message
            return protocol in (PROTOCOL_ID_V13, PROTOCOL_ID_V14)
        elif feature == "adaptive_gossip":  # Adaptive gossip parameters
            return protocol == PROTOCOL_ID_V14
        elif feature == "scoring":  # Peer scoring system
            return protocol in (
                PROTOCOL_ID_V11,
                PROTOCOL_ID_V12,
                PROTOCOL_ID_V13,
                PROTOCOL_ID_V14,
            )
        elif feature == "extended_scoring":  # Extended peer scoring (P5-P7)
            return protocol == PROTOCOL_ID_V14

        # Default to not supported for unknown features
        return False

    def register_extension_handler(
        self, extension_name: str, handler: Callable[[bytes, ID], Awaitable[None]]
    ) -> None:
        """
        Register a handler for a specific extension.

        :param extension_name: Name of the extension
        :param handler: Async callable that takes (data: bytes, sender_peer_id: ID)
        """
        self.extension_handlers[extension_name] = handler
        logger.debug("Registered handler for extension: %s", extension_name)

    def unregister_extension_handler(self, extension_name: str) -> None:
        """
        Unregister a handler for a specific extension.

        :param extension_name: Name of the extension
        """
        if extension_name in self.extension_handlers:
            del self.extension_handlers[extension_name]
            logger.debug("Unregistered handler for extension: %s", extension_name)

    async def emit_extension(
        self, extension_name: str, data: bytes, to_peer: ID
    ) -> None:
        """
        Emit an extension message to a peer.

        :param extension_name: Name of the extension
        :param data: Extension data
        :param to_peer: Target peer ID
        """
        if not self.supports_protocol_feature(to_peer, "extensions"):
            logger.warning(
                "Cannot send extension to peer %s: peer doesn't support extensions",
                to_peer,
            )
            return

        extension_msg = rpc_pb2.ControlExtension()
        extension_msg.name = extension_name
        extension_msg.data = data

        control_msg = rpc_pb2.ControlMessage()
        control_msg.extensions.extend([extension_msg])

        await self.emit_control_message(control_msg, to_peer)

    def _check_iwant_rate_limit(self, peer_id: ID) -> bool:
        """
        Check if peer has exceeded IWANT request rate limit.

        :param peer_id: The peer to check
        :return: True if within rate limit, False if exceeded
        """
        current_time = time.time()
        timestamps = self.iwant_request_limits[peer_id]["requests"]

        # Remove old timestamps (older than 1 second)
        cutoff_time = current_time - 1.0
        timestamps[:] = [t for t in timestamps if t > cutoff_time]

        # Check if rate limit exceeded
        if len(timestamps) >= self.max_iwant_requests_per_second:
            # Apply penalty for IWANT spam
            if hasattr(self, "scorer") and self.scorer is not None:
                self.scorer.penalize_iwant_spam(peer_id, 5.0)
            return False

        # Add current timestamp
        timestamps.append(current_time)
        return True

    def _check_ihave_rate_limit(self, peer_id: ID, topic: str) -> bool:
        """
        Check if peer has exceeded IHAVE message rate limit for a topic.

        :param peer_id: The peer to check
        :param topic: The topic to check
        :return: True if within rate limit, False if exceeded
        """
        current_time = time.time()
        timestamps = self.ihave_message_limits[peer_id][topic]

        # Remove old timestamps (older than 1 second)
        cutoff_time = current_time - 1.0
        timestamps[:] = [t for t in timestamps if t > cutoff_time]

        # Check if rate limit exceeded
        if len(timestamps) >= self.max_ihave_messages_per_second:
            # Apply penalty for IHAVE spam
            if hasattr(self, "scorer") and self.scorer is not None:
                self.scorer.penalize_ihave_spam(peer_id, 5.0)
            return False

        # Add current timestamp
        timestamps.append(current_time)
        return True

    def _check_graft_flood_protection(self, peer_id: ID, topic: str) -> bool:
        """
        Check for GRAFT flood protection (P7 behavioral penalty).

        :param peer_id: The peer to check
        :param topic: The topic to check
        :return: True if no flood detected, False if flood detected
        """
        current_time = time.time()
        last_prune_time = self.graft_flood_tracking[peer_id].get(topic, 0.0)

        # Use the smaller of graft_flood_threshold and prune_back_off so that
        # peers can re-graft after the configured backoff period.
        threshold = min(self.graft_flood_threshold, float(self.prune_back_off))

        # Check if GRAFT comes too soon after PRUNE (flood threshold)
        if current_time - last_prune_time < threshold:
            return False

        return True

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

        if protocol_id not in (
            PROTOCOL_ID,
            PROTOCOL_ID_V11,
            PROTOCOL_ID_V12,
            PROTOCOL_ID_V13,
            PROTOCOL_ID_V14,
            PROTOCOL_ID_V20,
            floodsub.PROTOCOL_ID,
        ):
            # We should never enter here. Becuase the `protocol_id` is registered by
            #   your pubsub instance in multistream-select, but it is not the protocol
            #   that gossipsub supports. In this case, probably we registered gossipsub
            #   to a wrong `protocol_id` in multistream-select, or wrong versions.
            raise ValueError(f"Protocol={protocol_id} is not supported.")
        self.peer_protocol[peer_id] = protocol_id

        # Initialize IDONTWANT tracking for this peer
        if peer_id not in self.dont_send_message_ids:
            self.dont_send_message_ids[peer_id] = set()

        # Track peer IP for colocation scoring if scorer is available
        if self.scorer is not None and self.pubsub is not None:
            self._track_peer_ip(peer_id)

        # Track connection for adaptive gossip metrics (only when enabled)
        if self.adaptive_gossip_enabled:
            self.recent_peer_connections.append(time.time())

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

        # Clean up IDONTWANT tracking for this peer
        self.dont_send_message_ids.pop(peer_id, None)

        # Clean up scoring data for this peer
        if self.scorer is not None:
            self.scorer.remove_peer(peer_id)

        # Clean up security state
        self._cleanup_security_state(peer_id)

        # Track disconnection for adaptive gossip metrics (only when enabled)
        if self.adaptive_gossip_enabled:
            self.recent_peer_disconnections.append(time.time())

    async def handle_rpc(self, rpc: rpc_pb2.RPC, sender_peer_id: ID) -> None:
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed

        :param rpc: RPC message
        :param sender_peer_id: id of the peer who sent the message
        """
        # Process the senderRecord if sent
        if isinstance(self.pubsub, Pubsub):
            if not maybe_consume_signed_record(rpc, self.pubsub.host, sender_peer_id):
                logger.error("Received an invalid-signed-record, ignoring the message")
                return

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
        if control_message.idontwant:
            for idontwant in control_message.idontwant:
                await self.handle_idontwant(idontwant, sender_peer_id)
        if control_message.extensions:
            for extension in control_message.extensions:
                await self.handle_extension(extension, sender_peer_id)

    async def publish(self, msg_forwarder: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """Invoked to forward a new message that has been validated."""
        # Security checks for Gossipsub 2.0
        if not self._check_spam_protection(msg_forwarder, pubsub_msg):
            logger.debug(
                "Message rejected due to spam protection from peer %s", msg_forwarder
            )
            return

        if not self._check_equivocation(pubsub_msg):
            logger.debug(
                "Message rejected due to equivocation from peer %s",
                ID(pubsub_msg.from_id),
            )
            return

        self.mcache.put(pubsub_msg)

        # Get message ID for IDONTWANT
        if self.pubsub is not None:
            msg_id = self.pubsub.get_message_id(pubsub_msg)
        else:
            # Fallback to default ID construction
            msg_id = pubsub_msg.seqno + pubsub_msg.from_id

        peers_gen = self._get_peers_to_send(
            pubsub_msg.topicIDs,
            msg_forwarder=msg_forwarder,
            origin=ID(pubsub_msg.from_id),
            msg_id=msg_id,
        )
        rpc_msg = rpc_pb2.RPC(publish=[pubsub_msg])

        # Add the senderRecord of the peer in the RPC msg
        if isinstance(self.pubsub, Pubsub):
            envelope_bytes, _ = env_to_send_in_RPC(self.pubsub.host)
            rpc_msg.senderRecord = envelope_bytes

        logger.debug("publishing message %s", pubsub_msg)

        # Send IDONTWANT to mesh peers about this message
        await self._emit_idontwant_for_message(msg_id, pubsub_msg.topicIDs)

        for peer_id in peers_gen:
            if self.pubsub is None:
                raise NoPubsubAttached
            if peer_id not in self.pubsub.peers:
                continue
            # Publish gate
            if self.scorer is not None and not self.scorer.allow_publish(
                peer_id, list(pubsub_msg.topicIDs)
            ):
                continue
            stream = self.pubsub.peers[peer_id]

            # TODO: Go use `sendRPC`, which possibly piggybacks gossip/control messages.
            await self.pubsub.write_msg(stream, rpc_msg)

        for topic in pubsub_msg.topicIDs:
            self.time_since_last_publish[topic] = int(time.time())
            # Track message delivery for adaptive metrics
            self.recent_message_deliveries[topic].append(time.time())

    def _get_peers_to_send(
        self,
        topic_ids: Iterable[str],
        msg_forwarder: ID,
        origin: ID,
        msg_id: bytes | None = None,
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
                if peer_id in self.peer_protocol
                and self.peer_protocol[peer_id] == floodsub.PROTOCOL_ID
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
            # Apply gossip score gate
            if self.scorer is not None and gossipsub_peers:
                allowed = {
                    p
                    for p in gossipsub_peers
                    if self.scorer.allow_gossip(p, [topic])
                    and not self.scorer.is_graylisted(p, [topic])
                }
                send_to.update(allowed)
            else:
                send_to.update(gossipsub_peers)
        # Excludes `msg_forwarder` and `origin`
        filtered_peers = send_to.difference([msg_forwarder, origin])

        # Filter out peers that have sent IDONTWANT for this message
        if msg_id is not None:
            filtered_peers = {
                peer_id
                for peer_id in filtered_peers
                if peer_id not in self.dont_send_message_ids
                or msg_id not in self.dont_send_message_ids[peer_id]
            }

        yield from filtered_peers

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
            # Add backoff BEFORE emitting PRUNE to avoid races where a GRAFT
            # could be processed before the backoff is recorded locally.
            self._add_back_off(peer, topic, True)
            await self.emit_prune(topic, peer, self.do_px, True)

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

            # Ensure mesh diversity for Eclipse attack protection
            # and collect additional peers to graft
            if self.eclipse_protection_enabled:
                for topic in self.mesh:
                    diversity_peers = self._ensure_mesh_diversity(topic)
                    # Add diversity peers to the graft list
                    for peer in diversity_peers:
                        if peer not in peers_to_graft:
                            peers_to_graft[peer] = []
                        if topic not in peers_to_graft[peer]:
                            peers_to_graft[peer].append(topic)

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

            # scorer decay step
            if self.scorer is not None:
                self.scorer.on_heartbeat()

            # Update network health and adapt parameters (v2.0 feature)
            if self.adaptive_gossip_enabled:
                self._update_network_health()
                self._adapt_gossip_parameters()

            # Security maintenance (v2.0 feature)
            self._periodic_security_cleanup()

            # Perform ongoing mesh quality maintenance (v2.0 feature)
            for topic in list(self.mesh):
                await self._maintain_mesh_quality(topic)

            # Prune old IDONTWANT entries to prevent memory leaks
            self._prune_idontwant_entries()

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

            # Use adaptive degree bounds
            effective_degree_low = (
                self.adaptive_degree_low
                if self.adaptive_gossip_enabled
                else self.degree_low
            )
            effective_degree_high = (
                self.adaptive_degree_high
                if self.adaptive_gossip_enabled
                else self.degree_high
            )

            if num_mesh_peers_in_topic < effective_degree_low:
                # Select D - |mesh[topic]| peers from peers.gossipsub[topic] - mesh[topic]  # noqa: E501
                selected_peers = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, self.degree - num_mesh_peers_in_topic, self.mesh[topic], True
                )

                for peer in selected_peers:
                    # Add peer to mesh[topic]
                    self.mesh[topic].add(peer)

                    # Emit GRAFT(topic) control message to peer
                    peers_to_graft[peer].append(topic)

            # Enhanced opportunistic grafting for Gossipsub 2.0
            if (
                self.scorer is not None
                and num_mesh_peers_in_topic >= effective_degree_low
            ):
                self._perform_opportunistic_grafting(topic, peers_to_graft)

            if num_mesh_peers_in_topic > effective_degree_high:
                # Enhanced mesh pruning with score-based selection
                peers_to_remove = self._select_peers_for_pruning(
                    topic, num_mesh_peers_in_topic - self.degree
                )
                for peer in peers_to_remove:
                    # Remove peer from mesh[topic]
                    self.mesh[topic].discard(peer)
                    if self.scorer is not None:
                        self.scorer.on_leave_mesh(peer, topic)

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
                # Select peers from peers.gossipsub[topic] excluding current peers
                # Use adaptive count based on network health
                total_gossip_peers = len(
                    self.pubsub.peer_topics.get(topic, set())
                ) - len(current_peers)
                gossip_count = self._get_adaptive_gossip_peers_count(
                    topic, total_gossip_peers
                )

                peers_to_emit_ihave_to = self._get_in_topic_gossipsub_peers_from_minus(
                    topic, gossip_count, current_peers, True
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
        if num_to_select <= 0:
            return []
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
            if self.peer_protocol.get(peer_id)
            in (
                PROTOCOL_ID,
                PROTOCOL_ID_V11,
                PROTOCOL_ID_V12,
                PROTOCOL_ID_V13,
                PROTOCOL_ID_V14,
                PROTOCOL_ID_V20,
            )
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

    def _prune_idontwant_entries(self) -> None:
        """
        Prune old IDONTWANT entries during heartbeat to prevent memory leaks.

        This method removes all IDONTWANT entries since they are only relevant
        for the current heartbeat period. The specific message IDs that peers
        don't want should be cleared regularly to prevent indefinite growth.
        """
        # Clear all IDONTWANT entries for all peers
        for peer_id in self.dont_send_message_ids:
            self.dont_send_message_ids[peer_id].clear()

    async def _do_px(self, px_peers: list[rpc_pb2.PeerInfo]) -> None:
        if len(px_peers) > self.px_peers_count:
            px_peers = px_peers[: self.px_peers_count]

        for peer in px_peers:
            peer_id: ID = ID(peer.peerID)

            if self.pubsub and peer_id in self.pubsub.peers:
                continue

            try:
                # Validate signed peer record if provided;
                # otherwise try to connect directly
                if peer.HasField("signedPeerRecord") and len(peer.signedPeerRecord) > 0:
                    # Validate envelope signature and freshness via peerstore consume
                    if self.pubsub is None:
                        raise NoPubsubAttached

                    envelope, record = consume_envelope(
                        peer.signedPeerRecord, "libp2p-peer-record"
                    )

                    # Ensure the record matches the advertised peer id
                    if record.peer_id != peer_id:
                        raise ValueError("peer id mismatch in PX signed record")

                    # Store into peerstore and update addrs
                    self.pubsub.host.get_peerstore().consume_peer_record(
                        envelope, ttl=7200
                    )

                    peer_info = PeerInfo(record.peer_id, record.addrs)
                    try:
                        await self.pubsub.host.connect(peer_info)
                    except Exception as e:
                        logger.warning(
                            "failed to connect to px peer %s: %s",
                            peer_id,
                            e,
                        )
                        continue
                else:
                    # No signed record available; try to use existing connection info
                    if self.pubsub is None:
                        raise NoPubsubAttached

                    try:
                        # Try to get existing peer info from peerstore
                        existing_peer_info = self.pubsub.host.get_peerstore().peer_info(
                            peer_id
                        )
                        await self.pubsub.host.connect(existing_peer_info)
                    except Exception as e:
                        logger.debug(
                            "peer %s not found in peerstore or connection failed: %s",
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
        """
        Checks the seen set and requests unknown messages with an IWANT message.

        Enhanced with rate limiting for GossipSub v1.4.
        """
        # Rate limiting check for IHAVE messages
        if not self._check_ihave_rate_limit(sender_peer_id, ihave_msg.topicID):
            logger.warning(
                "IHAVE rate limit exceeded for peer %s on topic %s, ignoring message",
                sender_peer_id,
                ihave_msg.topicID,
            )
            return
        if self.pubsub is None:
            raise NoPubsubAttached
        # Get list of all seen (seqnos, from) from the (seqno, from) tuples in
        # seen_messages cache
        seen_seqnos_and_peers = [
            str(seqno_and_from)
            for seqno_and_from in self.pubsub.seen_messages.cache.keys()
        ]

        # Add all unknown message ids (ids that appear in ihave_msg but not in
        # seen_seqnos) to list of messages we want to request
        msg_ids_wanted: list[MessageID] = [
            parse_message_id_safe(msg_id)
            for msg_id in ihave_msg.messageIDs
            if msg_id not in seen_seqnos_and_peers
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

        Enhanced with rate limiting for GossipSub v1.4.
        """
        # Rate limiting check for IWANT requests
        if not self._check_iwant_rate_limit(sender_peer_id):
            logger.warning(
                "IWANT rate limit exceeded for peer %s, ignoring request",
                sender_peer_id,
            )
            return
        msg_ids: list[tuple[bytes, bytes]] = [
            safe_parse_message_id(msg) for msg in iwant_msg.messageIDs
        ]
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

        # Here the an RPC message is being created and published in response
        # to the iwant control msg, so we will send a freshly created senderRecord
        # with the RPC msg
        if isinstance(self.pubsub, Pubsub):
            envelope_bytes, _ = env_to_send_in_RPC(self.pubsub.host)
            packet.senderRecord = envelope_bytes

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

        # GRAFT flood protection (v1.4 feature)
        if not self._check_graft_flood_protection(sender_peer_id, topic):
            logger.warning(
                "GRAFT flood detected from peer %s for topic %s, applying penalty",
                sender_peer_id,
                topic,
            )
            if self.scorer is not None:
                self.scorer.penalize_graft_flood(sender_peer_id, 10.0)
            await self.emit_prune(topic, sender_peer_id, False, False)
            return

        # Score gate for GRAFT acceptance
        if self.scorer is not None:
            if self.scorer.is_graylisted(sender_peer_id, [topic]):
                await self.emit_prune(topic, sender_peer_id, False, False)
                return

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
                if self.scorer is not None:
                    self.scorer.on_join_mesh(sender_peer_id, topic)
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
        # Always add backoff, even if topic is not currently in mesh
        if backoff_till > 0:
            self._add_back_off(sender_peer_id, topic, False, backoff_till)
        else:
            self._add_back_off(sender_peer_id, topic, False)

        # Remove sender from mesh if topic exists in mesh
        if topic in self.mesh:
            self.mesh[topic].discard(sender_peer_id)
            if self.scorer is not None:
                self.scorer.on_leave_mesh(sender_peer_id, topic)

        # Track PRUNE time for GRAFT flood protection
        self.graft_flood_tracking[sender_peer_id][topic] = time.time()

        if px_peers:
            # Score-gate PX acceptance
            allow_px = True
            if self.scorer is not None:
                allow_px = self.scorer.allow_px_from(sender_peer_id, [topic])
            if allow_px:
                await self._do_px(px_peers)

    # RPC emitters

    def pack_control_msgs(
        self,
        ihave_msgs: list[rpc_pb2.ControlIHave] | None,
        graft_msgs: list[rpc_pb2.ControlGraft] | None,
        prune_msgs: list[rpc_pb2.ControlPrune] | None,
        idontwant_msgs: list[rpc_pb2.ControlIDontWant] | None = None,
        extension_msgs: list[rpc_pb2.ControlExtension] | None = None,
    ) -> rpc_pb2.ControlMessage:
        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        if ihave_msgs:
            control_msg.ihave.extend(ihave_msgs)
        if graft_msgs:
            control_msg.graft.extend(graft_msgs)
        if prune_msgs:
            control_msg.prune.extend(prune_msgs)
        if idontwant_msgs:
            control_msg.idontwant.extend(idontwant_msgs)
        if extension_msgs:
            control_msg.extensions.extend(extension_msgs)
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

                # Try to get the signed peer record envelope from peerstore
                envelope = self.pubsub.host.get_peerstore().get_peer_record(peer)
                peer_info_msg: rpc_pb2.PeerInfo = rpc_pb2.PeerInfo()
                peer_info_msg.peerID = peer.to_bytes()

                if envelope is not None:
                    # Use the signed envelope
                    peer_info_msg.signedPeerRecord = envelope.marshal_envelope()
                # If no signed record available, include peer without signed record

                prune_msg.peers.append(peer_info_msg)

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.prune.extend([prune_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_idontwant(self, msg_ids: list[bytes], to_peer: ID) -> None:
        """Emit idontwant message, sent to to_peer, for msg_ids."""
        idontwant_msg: rpc_pb2.ControlIDontWant = rpc_pb2.ControlIDontWant()
        idontwant_msg.messageIDs.extend(msg_ids)

        control_msg: rpc_pb2.ControlMessage = rpc_pb2.ControlMessage()
        control_msg.idontwant.extend([idontwant_msg])

        await self.emit_control_message(control_msg, to_peer)

    async def emit_control_message(
        self, control_msg: rpc_pb2.ControlMessage, to_peer: ID
    ) -> None:
        if self.pubsub is None:
            raise NoPubsubAttached
        # Add control message to packet
        packet: rpc_pb2.RPC = rpc_pb2.RPC()

        # Add the sender's peer-record in the RPC msg
        if isinstance(self.pubsub, Pubsub):
            envelope_bytes, _ = env_to_send_in_RPC(self.pubsub.host)
            packet.senderRecord = envelope_bytes

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

    async def _emit_idontwant_for_message(
        self, msg_id: bytes, topic_ids: Iterable[str]
    ) -> None:
        """
        Emit IDONTWANT message to mesh peers about a received message.

        :param msg_id: The message ID to notify peers about
        :param topic_ids: The topics the message belongs to
        """
        if self.pubsub is None:
            return

        # Get all mesh peers for the topics in this message
        mesh_peers: set[ID] = set()
        for topic in topic_ids:
            if topic in self.mesh:
                mesh_peers.update(self.mesh[topic])

        # Only send to peers that support gossipsub 1.2+
        v12_plus_peers = {
            peer_id
            for peer_id in mesh_peers
            if self.peer_protocol.get(peer_id)
            in (PROTOCOL_ID_V12, PROTOCOL_ID_V13, PROTOCOL_ID_V14, PROTOCOL_ID_V20)
        }

        if not v12_plus_peers:
            return

        # Send IDONTWANT message to all v1.2+ mesh peers
        for peer_id in v12_plus_peers:
            await self.emit_idontwant([msg_id], peer_id)

    async def handle_idontwant(
        self, idontwant_msg: rpc_pb2.ControlIDontWant, sender_peer_id: ID
    ) -> None:
        """
        Handle incoming IDONTWANT control message by adding message IDs
        to the peer's dont_send_message_ids set.

        This method enforces max_idontwant_messages limit to prevent memory exhaustion
        from peers sending excessive IDONTWANT messages. When the limit is reached,
        older entries may be dropped to make room for new ones.

        :param idontwant_msg: The IDONTWANT control message
        :param sender_peer_id: ID of the peer who sent the message
        """
        # Initialize set if peer not tracked
        if sender_peer_id not in self.dont_send_message_ids:
            self.dont_send_message_ids[sender_peer_id] = set()

        # Check if we need to enforce the limit
        current_count = len(self.dont_send_message_ids[sender_peer_id])
        new_count = len(idontwant_msg.messageIDs)

        # If adding all new message IDs would exceed the limit, we need to enforce it
        if current_count + new_count > self.max_idontwant_messages:
            # If we're already at or over the limit, we need to drop some entries
            if current_count >= self.max_idontwant_messages:
                # Convert to list to allow removal of specific elements
                current_ids = list(self.dont_send_message_ids[sender_peer_id])
                # Calculate how many old entries to drop to make room for new ones
                # while staying under the limit
                to_drop = min(new_count, current_count)
                # Drop the oldest entries (assuming they're the first in the set)
                self.dont_send_message_ids[sender_peer_id] = set(current_ids[to_drop:])

                logger.debug(
                    "IDONTWANT limit reached for peer %s. Dropped %d oldest entries.",
                    sender_peer_id,
                    to_drop,
                )

            # Add new entries up to the limit
            remaining_capacity = self.max_idontwant_messages - len(
                self.dont_send_message_ids[sender_peer_id]
            )
            for msg_id in list(idontwant_msg.messageIDs)[:remaining_capacity]:
                self.dont_send_message_ids[sender_peer_id].add(msg_id)
        else:
            # We have room for all new entries
            for msg_id in idontwant_msg.messageIDs:
                self.dont_send_message_ids[sender_peer_id].add(msg_id)

        logger.debug(
            "Added message IDs to dont_send list for peer %s (current count: %d/%d)",
            sender_peer_id,
            len(self.dont_send_message_ids[sender_peer_id]),
            self.max_idontwant_messages,
        )

    async def handle_extension(
        self, extension_msg: rpc_pb2.ControlExtension, sender_peer_id: ID
    ) -> None:
        """
        Handle incoming Extension control message.

        Extensions allow for protocol extensibility in GossipSub v1.3+.
        This method dispatches to registered extension handlers.

        :param extension_msg: The Extension control message
        :param sender_peer_id: ID of the peer who sent the message
        """
        extension_name = extension_msg.name
        extension_data = extension_msg.data

        # Check if peer supports extensions
        if not self.supports_protocol_feature(sender_peer_id, "extensions"):
            logger.warning(
                "Received extension from peer %s that doesn't support extensions",
                sender_peer_id,
            )
            return

        # Dispatch to registered extension handler
        if (
            hasattr(self, "extension_handlers")
            and extension_name in self.extension_handlers
        ):
            try:
                await self.extension_handlers[extension_name](
                    extension_data, sender_peer_id
                )
                logger.debug(
                    "Processed extension '%s' from peer %s",
                    extension_name,
                    sender_peer_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to process extension '%s' from peer %s: %s",
                    extension_name,
                    sender_peer_id,
                    e,
                )
        else:
            logger.debug(
                "No handler registered for extension '%s' from peer %s",
                extension_name,
                sender_peer_id,
            )

    def _track_peer_ip(self, peer_id: ID) -> None:
        """
        Track the IP address of a peer for colocation scoring.

        :param peer_id: The peer ID to track
        """
        if self.pubsub is None or self.scorer is None:
            return

        try:
            # Try to get the peer's connection from the host
            if peer_id in self.pubsub.peers:
                stream = self.pubsub.peers[peer_id]
                # Get the remote address from the connection
                # Note: Accessing connection through muxed_conn may vary
                muxed_conn = stream.muxed_conn
                conn = getattr(muxed_conn, "conn", None)
                if conn is not None and hasattr(conn, "remote_addr"):
                    remote_addr = getattr(conn, "remote_addr", None)
                    if remote_addr:
                        # Extract IP from multiaddr
                        ip_str = self._extract_ip_from_multiaddr(str(remote_addr))
                        if ip_str:
                            self.scorer.add_peer_ip(peer_id, ip_str)
        except Exception as e:
            logger.debug("Failed to track IP for peer %s: %s", peer_id, e)

    def _extract_ip_from_multiaddr(self, multiaddr_str: str) -> str | None:
        """
        Extract IP address from a multiaddr string.

        :param multiaddr_str: The multiaddr string
        :return: The IP address or None if extraction fails
        """
        try:
            # Simple extraction for common cases like /ip4/127.0.0.1/tcp/4001
            # or /ip6/::1/tcp/4001
            parts = multiaddr_str.split("/")
            for i, part in enumerate(parts):
                if part in ("ip4", "ip6") and i + 1 < len(parts):
                    return parts[i + 1]
            return None
        except Exception:
            return None

    def _update_network_health(self) -> None:
        """
        Update network health score based on mesh connectivity and peer behavior.

        Network health is calculated based on:
        - Mesh connectivity ratio
        - Peer score distribution
        - Message delivery success rate
        """
        if not self.adaptive_gossip_enabled or self.scorer is None:
            return

        current_time = int(time.time())
        # Update health every 30 seconds
        if current_time - self.last_health_update < 30:
            return

        self.last_health_update = current_time

        try:
            total_topics = len(self.mesh)
            if total_topics == 0:
                self.network_health_score = 1.0
                return

            # Calculate mesh connectivity health (0.0 to 1.0)
            connectivity_health = 0.0
            for topic, peers in self.mesh.items():
                target_degree = self.degree
                actual_degree = len(peers)
                # Health is better when we're close to target degree
                if actual_degree == 0:
                    topic_health = 0.0
                else:
                    # Normalize based on how close we are to target
                    ratio = min(actual_degree / target_degree, 1.0)
                    topic_health = ratio
                connectivity_health += topic_health

            connectivity_health /= total_topics

            # Calculate additional health metrics
            score_health = self._calculate_peer_score_health()
            delivery_health = self._calculate_message_delivery_health()
            stability_health = self._calculate_mesh_stability_health()
            churn_health = self._calculate_connection_churn_health()

            # Combine metrics (weighted average with v1.4 enhancements)
            self.network_health_score = (
                0.3 * connectivity_health
                + 0.25 * score_health
                + 0.2 * delivery_health
                + 0.15 * stability_health
                + 0.1 * churn_health
            )
            self.network_health_score = max(0.0, min(1.0, self.network_health_score))

            logger.debug(
                "Network health updated: %.2f (connectivity: %.2f, scores: %.2f, ",
                "delivery: %.2f, stability: %.2f, churn: %.2f)",
                self.network_health_score,
                connectivity_health,
                score_health,
                delivery_health,
                stability_health,
                churn_health,
            )

        except Exception as e:
            logger.debug("Failed to update network health: %s", e)
            # Default to moderate health on error
            self.network_health_score = 0.5

    def _calculate_peer_score_health(self) -> float:
        """
        Calculate health based on peer score distribution.

        :return: Health score from 0.0 to 1.0
        """
        if self.scorer is None:
            return 1.0

        scorer = self.scorer  # Type narrowing
        try:
            # Get all peers in mesh
            all_mesh_peers: set[ID] = set()
            for peers in self.mesh.values():
                all_mesh_peers.update(peers)

            if not all_mesh_peers:
                return 0.0  # No peers means poor health

            # Calculate average score
            total_score = 0.0
            positive_scores = 0
            for peer in all_mesh_peers:
                # Use empty topic list for overall score
                score = scorer.score(peer, [])
                total_score += score
                if score > 0:
                    positive_scores += 1

            # Health is better when more peers have positive scores
            positive_ratio = positive_scores / len(all_mesh_peers)
            return positive_ratio

        except Exception:
            return 0.5

    def _calculate_message_delivery_health(self) -> float:
        """
        Calculate health based on message delivery success rate.

        :return: Health score from 0.0 to 1.0
        """
        try:
            current_time = time.time()
            cutoff_time = current_time - 60.0  # Look at last minute

            total_deliveries = 0
            successful_deliveries = 0

            for topic, delivery_times in self.recent_message_deliveries.items():
                # Clean old entries
                delivery_times[:] = [t for t in delivery_times if t > cutoff_time]

                # Count deliveries (simplified - in real implementation,
                # track success/failure separately)
                total_deliveries += len(delivery_times)
                successful_deliveries += len(
                    delivery_times
                )  # Assume all tracked are successful

            if total_deliveries == 0:
                # If we have no deliveries but have mesh peers, assume moderate health
                # If we have no mesh peers, return poor health
                total_mesh_peers = sum(len(peers) for peers in self.mesh.values())
                if total_mesh_peers == 0:
                    return 0.0  # No mesh peers means poor health
                return 0.5  # No delivery data but have peers, assume moderate

            self.message_delivery_success_rate = (
                successful_deliveries / total_deliveries
            )
            return self.message_delivery_success_rate

        except Exception:
            return 0.5

    def _calculate_mesh_stability_health(self) -> float:
        """
        Calculate health based on mesh stability (low churn is good).

        :return: Health score from 0.0 to 1.0
        """
        try:
            # Simple stability metric: ratio of stable connections
            total_mesh_peers = sum(len(peers) for peers in self.mesh.values())

            if total_mesh_peers == 0:
                return 0.0  # No mesh peers means poor stability

            # In a real implementation, track mesh changes over time
            # For now, use a simple heuristic based on mesh size vs target
            stability_ratio = 0.0
            topic_count = len(self.mesh)

            if topic_count > 0:
                for topic, peers in self.mesh.items():
                    target_size = self.degree
                    actual_size = len(peers)

                    if actual_size == 0:
                        topic_stability = 0.0
                    else:
                        # Stability is higher when actual size is close to target
                        size_ratio = min(
                            actual_size / target_size, target_size / actual_size
                        )
                        topic_stability = size_ratio

                    stability_ratio += topic_stability

                self.mesh_stability_score = stability_ratio / topic_count
            else:
                self.mesh_stability_score = 1.0

            return self.mesh_stability_score

        except Exception:
            return 0.5

    def _calculate_connection_churn_health(self) -> float:
        """
        Calculate health based on connection churn rate (low churn is good).

        :return: Health score from 0.0 to 1.0
        """
        try:
            current_time = time.time()
            window_size = 60.0  # 1 minute window
            cutoff_time = current_time - window_size

            # Clean old entries
            self.recent_peer_connections[:] = [
                t for t in self.recent_peer_connections if t > cutoff_time
            ]
            self.recent_peer_disconnections[:] = [
                t for t in self.recent_peer_disconnections if t > cutoff_time
            ]

            connections = len(self.recent_peer_connections)
            disconnections = len(self.recent_peer_disconnections)
            total_churn = connections + disconnections

            # Calculate churn rate (events per minute)
            churn_rate = total_churn / (window_size / 60.0)
            self.connection_churn_rate = churn_rate

            # Health decreases with higher churn rate
            # Assume 10 events/minute is high churn, 0 is perfect
            max_acceptable_churn = 10.0
            health = max(0.0, 1.0 - (churn_rate / max_acceptable_churn))

            return health

        except Exception:
            return 0.5

    def _adapt_gossip_parameters(self) -> None:
        """
        Adapt gossip parameters based on network health.

        Enhanced v1.4 version with more sophisticated parameter adjustment.

        When network health is poor:
        - Increase mesh degree bounds to improve connectivity
        - Increase gossip factor to spread messages more widely
        - Adjust heartbeat intervals for faster convergence

        When network health is good:
        - Use standard parameters for efficiency
        - Optimize for lower bandwidth usage
        """
        if not self.adaptive_gossip_enabled:
            return

        health = self.network_health_score

        # More granular health-based adjustments
        if health < 0.2:
            # Critical health: aggressive adaptation
            self.adaptive_degree_low = min(self.degree_low + 3, self.degree_high + 2)
            self.adaptive_degree_high = self.degree_high + 4
            self.gossip_factor = min(0.6, 0.25 * 2.0)
        elif health < 0.4:
            # Poor health: significant adaptation
            self.adaptive_degree_low = min(self.degree_low + 2, self.degree_high)
            self.adaptive_degree_high = self.degree_high + 3
            self.gossip_factor = min(0.5, 0.25 * 1.8)
        elif health < 0.6:
            # Moderate health: moderate adaptation
            self.adaptive_degree_low = min(self.degree_low + 1, self.degree_high)
            self.adaptive_degree_high = self.degree_high + 2
            self.gossip_factor = min(0.4, 0.25 * 1.4)
        elif health < 0.8:
            # Good health: slight optimization
            self.adaptive_degree_low = self.degree_low
            self.adaptive_degree_high = self.degree_high + 1
            self.gossip_factor = 0.25 * 1.1
        else:
            # Excellent health: use base parameters (no further reduction)
            self.adaptive_degree_low = self.degree_low
            self.adaptive_degree_high = self.degree_high
            self.gossip_factor = 0.25

        # Additional v1.4 adaptive features
        self._adapt_opportunistic_grafting_parameters(health)
        self._adapt_heartbeat_parameters(health)

    def _get_adaptive_gossip_peers_count(self, topic: str, total_peers: int) -> int:
        """
        Calculate adaptive number of peers to gossip to.

        :param topic: The topic
        :param total_peers: Total number of available peers
        :return: Number of peers to gossip to
        """
        if not self.adaptive_gossip_enabled:
            # Use default calculation
            return max(6, int(total_peers * 0.25))  # Default Dlazy=6, factor=0.25

        # Use adaptive gossip factor
        base_count = int(total_peers * self.gossip_factor)
        min_count = 6 if self.network_health_score > 0.5 else 8

        return max(min_count, base_count)

    def _adapt_opportunistic_grafting_parameters(self, health: float) -> None:
        """
        Adapt opportunistic grafting behavior based on network health.

        :param health: Current network health score (0.0 to 1.0)
        """
        # In poor health, be more aggressive about opportunistic grafting
        if hasattr(self, "opportunistic_graft_threshold"):
            if health < 0.4:
                # Lower threshold = more aggressive grafting
                self.opportunistic_graft_threshold = 0.3
            elif health < 0.7:
                self.opportunistic_graft_threshold = 0.5
            else:
                # Higher threshold = more selective grafting
                self.opportunistic_graft_threshold = 0.7

    def _adapt_heartbeat_parameters(self, health: float) -> None:
        """
        Adapt heartbeat-related parameters based on network health.

        Poor health: more frequent heartbeats for faster convergence.
        Good health: standard interval to save bandwidth.

        :param health: Current network health score (0.0 to 1.0)
        """
        base = getattr(self, "heartbeat_interval_base", self.heartbeat_interval)
        if health < 0.4:
            # Critical: heartbeat every 30-60s for faster recovery
            self.heartbeat_interval = max(30, min(60, base // 2))
        elif health < 0.7:
            # Moderate: slightly more frequent than baseline
            self.heartbeat_interval = max(60, int(base * 0.75))
        else:
            # Good health: use baseline interval
            self.heartbeat_interval = base

    def _check_spam_protection(self, peer_id: ID, msg: rpc_pb2.Message) -> bool:
        """
        Check if message should be rejected due to spam protection.

        :param peer_id: The peer sending the message
        :param msg: The message to check
        :return: True if message should be accepted, False if rejected for spam
        """
        if not self.spam_protection_enabled:
            return True

        current_time = time.time()

        for topic in msg.topicIDs:
            # Get timestamps for this peer/topic combination
            timestamps = self.message_rate_limits[peer_id][topic]

            # Remove old timestamps (older than 1 second)
            cutoff_time = current_time - 1.0
            timestamps[:] = [t for t in timestamps if t > cutoff_time]

            # Check if rate limit exceeded
            if len(timestamps) >= self.max_messages_per_topic_per_second:
                logger.warning(
                    "Rate limit exceeded for peer %s on topic %s", peer_id, topic
                )
                # Penalize peer for spam
                if self.scorer is not None:
                    self.scorer.penalize_behavior(peer_id, 5.0)
                return False

            # Add current timestamp
            timestamps.append(current_time)

        return True

    def _check_equivocation(self, msg: rpc_pb2.Message) -> bool:
        """
        Check for message equivocation (same seqno/from with different content).

        :param msg: The message to check
        :return: True if message is valid, False if equivocation detected
        """
        msg_key = (msg.seqno, msg.from_id)

        if msg_key in self.equivocation_detection:
            existing_msg = self.equivocation_detection[msg_key]
            # Check if content differs (equivocation)
            if existing_msg.data != msg.data or existing_msg.topicIDs != msg.topicIDs:
                logger.warning("Equivocation detected from peer %s", ID(msg.from_id))
                # Severely penalize equivocating peer
                if self.scorer is not None:
                    self.scorer.penalize_equivocation(ID(msg.from_id), 100.0)
                return False
        else:
            # Store first occurrence
            self.equivocation_detection[msg_key] = msg

        return True

    def _ensure_mesh_diversity(self, topic: str) -> list[ID]:
        """
        Ensure mesh has sufficient IP diversity to prevent Eclipse attacks.

        :param topic: The topic to check
        :return: List of peers that should be grafted for IP diversity
        """
        if not self.eclipse_protection_enabled or topic not in self.mesh:
            return []

        if self.scorer is None:
            return []

        mesh_peers = self.mesh[topic]
        if len(mesh_peers) < self.min_mesh_diversity_ips:
            return []

        # Count unique IPs in mesh
        unique_ips = set()
        scorer = self.scorer
        if scorer is not None:
            for peer in mesh_peers:
                if peer in scorer.ip_by_peer:
                    unique_ips.add(scorer.ip_by_peer[peer])

        # If diversity is too low, try to improve it
        if len(unique_ips) < self.min_mesh_diversity_ips:
            logger.debug(
                "Low IP diversity in mesh for topic %s: %d unique IPs",
                topic,
                len(unique_ips),
            )
            return self._improve_mesh_diversity(topic, unique_ips)

        return []

    def _improve_mesh_diversity(self, topic: str, current_ips: set[str]) -> list[ID]:
        """
        Attempt to improve mesh diversity by grafting peers from different IPs.

        :param topic: The topic to improve
        :param current_ips: Set of IPs currently in mesh
        :return: List of peers that should be grafted for IP diversity
        """
        if self.pubsub is None or self.scorer is None:
            return []

        if topic not in self.pubsub.peer_topics:
            return []

        # Find candidates from different IPs
        candidates = []
        if self.scorer is None:
            return []

        scorer = self.scorer  # Type narrowing
        for peer in self.pubsub.peer_topics[topic]:
            if peer in self.mesh[topic]:
                continue  # Already in mesh

            if peer not in scorer.ip_by_peer:
                continue  # No IP info

            peer_ip = scorer.ip_by_peer[peer]
            if peer_ip not in current_ips:
                # This peer would add IP diversity
                candidates.append(peer)

        if not candidates:
            return []

        # Select best candidates based on score
        candidates_with_scores = [
            (peer, scorer.score(peer, [topic])) for peer in candidates
        ]
        candidates_with_scores.sort(key=lambda x: x[1], reverse=True)

        # Select up to 2 diverse peers to graft
        peers_to_graft = []
        grafted = 0
        for peer, score in candidates_with_scores:
            if grafted >= 2:
                break

            if score > scorer.params.graylist_threshold:
                self.mesh[topic].add(peer)
                peers_to_graft.append(peer)
                # Notify scorer about the new mesh peer
                if self.scorer is not None:
                    self.scorer.on_join_mesh(peer, topic)
                logger.debug(
                    "Grafted peer %s for IP diversity in topic %s", peer, topic
                )
                grafted += 1

        return peers_to_graft

    def _cleanup_security_state(self, peer_id: ID) -> None:
        """
        Clean up security-related state when a peer disconnects.

        :param peer_id: The peer that disconnected
        """
        # Clean up rate limiting data
        if peer_id in self.message_rate_limits:
            del self.message_rate_limits[peer_id]

        # Clean up v1.4 rate limiting data
        if peer_id in self.iwant_request_limits:
            del self.iwant_request_limits[peer_id]
        if peer_id in self.ihave_message_limits:
            del self.ihave_message_limits[peer_id]
        if peer_id in self.graft_flood_tracking:
            del self.graft_flood_tracking[peer_id]

    def _perform_opportunistic_grafting(
        self, topic: str, peers_to_graft: DefaultDict[ID, list[str]]
    ) -> int:
        """
        Perform enhanced opportunistic grafting with sophisticated peer selection.

        :param topic: The topic to perform grafting for
        :param peers_to_graft: Dictionary to add graft candidates to
        :return: Number of peers grafted
        """
        if self.scorer is None or self.pubsub is None:
            return 0

        try:
            current_mesh_peers = self.mesh[topic]

            # Only consider peers that support scoring for opportunistic grafting
            scoring_mesh_peers = [
                p for p in current_mesh_peers if self.supports_scoring(p)
            ]

            if not scoring_mesh_peers:
                return 0

            # Calculate mesh quality metrics
            mesh_scores = [self.scorer.score(p, [topic]) for p in scoring_mesh_peers]
            if not mesh_scores:
                return 0

            median_score = statistics.median(mesh_scores)
            avg_score = sum(mesh_scores) / len(mesh_scores)
            min_score = min(mesh_scores)

            # Determine grafting strategy based on mesh quality
            grafting_threshold = self._calculate_grafting_threshold(
                median_score, avg_score, min_score, topic
            )

            # Find potential candidates
            candidates = self._get_grafting_candidates(
                topic, current_mesh_peers, grafting_threshold
            )

            if not candidates:
                return 0

            # Select best candidates using multiple criteria
            selected_candidates = self._select_grafting_candidates(
                candidates, topic, len(current_mesh_peers)
            )

            # Perform grafting
            grafted_count = 0
            for candidate in selected_candidates:
                self.mesh[topic].add(candidate)
                peers_to_graft[candidate].append(topic)
                if self.scorer is not None:
                    self.scorer.on_join_mesh(candidate, topic)
                grafted_count += 1

                if self.scorer is not None:
                    logger.debug(
                        "Opportunistically grafted peer %s to topic %s (score: %.2f)",
                        candidate,
                        topic,
                        self.scorer.score(candidate, [topic]),
                    )

            return grafted_count

        except Exception as e:
            logger.warning(
                "Enhanced opportunistic grafting failed for topic %s: %s", topic, e
            )
            return 0

    def _calculate_grafting_threshold(
        self, median_score: float, avg_score: float, min_score: float, topic: str
    ) -> float:
        """
        Calculate the score threshold for opportunistic grafting candidates.

        Uses opportunistic_graft_threshold (adapted by
        _adapt_opportunistic_grafting_parameters based on network health) to control
        aggressiveness: lower = more aggressive, higher = more selective.

        :param median_score: Median score of current mesh peers
        :param avg_score: Average score of current mesh peers
        :param min_score: Minimum score of current mesh peers
        :param topic: The topic being considered
        :return: Score threshold for candidates
        """
        # Base threshold from median, scaled by opportunistic_graft_threshold
        # Lower threshold (aggressive) = more peers qualify; higher (selective) = fewer
        graft_threshold = getattr(self, "opportunistic_graft_threshold", 0.5)
        threshold = median_score * graft_threshold

        # Ensure threshold is reasonable
        threshold = max(
            threshold, min_score * 1.1
        )  # At least slightly better than worst peer
        if self.scorer is not None:
            threshold = max(
                threshold, self.scorer.params.gossip_threshold
            )  # At least gossip threshold

        return threshold

    def _get_grafting_candidates(
        self, topic: str, current_mesh: set[ID], threshold: float
    ) -> list[tuple[ID, float]]:
        """
        Get potential candidates for opportunistic grafting.

        :param topic: The topic
        :param current_mesh: Current mesh peers
        :param threshold: Score threshold for candidates
        :return: List of (peer_id, score) tuples for candidates
        """
        if self.pubsub is None or self.scorer is None:
            return []

        scorer = self.scorer  # Type narrowing
        if topic not in self.pubsub.peer_topics:
            return []

        candidates: list[tuple[ID, float]] = []

        for peer in self.pubsub.peer_topics[topic]:
            if peer in current_mesh:
                continue  # Already in mesh

            if not self.supports_scoring(peer):
                continue  # Only consider scoring-capable peers

            if self._check_back_off(peer, topic):
                continue  # Peer is in backoff

            # Check if peer meets score threshold
            peer_score = scorer.score(peer, [topic])
            if peer_score >= threshold:
                candidates.append((peer, peer_score))

        return candidates

    def _select_grafting_candidates(
        self, candidates: list[tuple[ID, float]], topic: str, current_mesh_size: int
    ) -> list[ID]:
        """
        Select the best candidates for grafting using multiple criteria.

        :param candidates: List of (peer_id, score) tuples
        :param topic: The topic
        :param current_mesh_size: Current size of mesh
        :return: List of selected peer IDs
        """
        if not candidates:
            return []

        # Sort candidates by score (descending)
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Apply additional selection criteria
        selected = []
        max_grafts = min(2, len(candidates))  # Limit grafts per heartbeat

        # Prefer peers that improve IP diversity if Eclipse protection is enabled
        if self.eclipse_protection_enabled and self.scorer is not None:
            selected = self._select_for_ip_diversity(candidates, topic, max_grafts)

        # If we still need more peers or diversity selection didn't work,
        # select highest scoring peers
        if len(selected) < max_grafts:
            remaining_needed = max_grafts - len(selected)
            for peer_id, score in candidates[: remaining_needed + len(selected)]:
                if peer_id not in selected:
                    selected.append(peer_id)
                    if len(selected) >= max_grafts:
                        break

        return selected

    def _select_for_ip_diversity(
        self, candidates: list[tuple[ID, float]], topic: str, max_grafts: int
    ) -> list[ID]:
        """
        Select candidates that improve IP diversity in the mesh.

        :param candidates: List of (peer_id, score) tuples
        :param topic: The topic
        :param max_grafts: Maximum number of peers to select
        :return: List of selected peer IDs
        """
        if self.scorer is None or topic not in self.mesh:
            return []

        # Get current IPs in mesh
        current_ips: set[str] = set()
        scorer = self.scorer
        if scorer is not None:
            for peer in self.mesh[topic]:
                if peer in scorer.ip_by_peer:
                    current_ips.add(scorer.ip_by_peer[peer])

        selected: list[ID] = []

        # Prioritize candidates from new IPs
        if scorer is not None:
            for peer_id, score in candidates:
                if len(selected) >= max_grafts:
                    break

                if peer_id in scorer.ip_by_peer:
                    peer_ip = scorer.ip_by_peer[peer_id]
                    if peer_ip not in current_ips:
                        # This peer would add IP diversity
                        selected.append(peer_id)
                        current_ips.add(peer_ip)

        return selected

    def _select_peers_for_pruning(self, topic: str, num_to_prune: int) -> list[ID]:
        """
        Select peers to prune from mesh using sophisticated scoring and
        diversity criteria.

        :param topic: The topic to prune peers from
        :param num_to_prune: Number of peers to prune
        :return: List of peer IDs to prune
        """
        if topic not in self.mesh or num_to_prune <= 0:
            return []

        mesh_peers = list(self.mesh[topic])
        if len(mesh_peers) <= num_to_prune:
            return mesh_peers

        if self.scorer is None:
            # Fallback to random selection if no scorer
            return self.select_from_minus(num_to_prune, mesh_peers, set())

        # Enhanced pruning strategy
        return self._score_based_pruning_selection(topic, mesh_peers, num_to_prune)

    def _score_based_pruning_selection(
        self, topic: str, mesh_peers: list[ID], num_to_prune: int
    ) -> list[ID]:
        """
        Select peers for pruning based on scores and diversity considerations.

        :param topic: The topic
        :param mesh_peers: List of current mesh peers
        :param num_to_prune: Number of peers to prune
        :return: List of peer IDs to prune
        """
        if self.scorer is None:
            return []

        # Calculate scores for all mesh peers
        peer_scores = []
        for peer in mesh_peers:
            score = self.scorer.score(peer, [topic])
            peer_scores.append((peer, score))

        # Sort by score (ascending - worst peers first)
        peer_scores.sort(key=lambda x: x[1])

        # Apply pruning strategy based on Gossipsub 2.0 principles
        selected_for_pruning: list[ID] = []

        # Strategy 1: Always prune peers below graylist threshold
        graylist_threshold = self.scorer.params.graylist_threshold
        for peer, score in peer_scores:
            if score < graylist_threshold and len(selected_for_pruning) < num_to_prune:
                selected_for_pruning.append(peer)

        # Strategy 2: If we still need to prune more, consider IP diversity
        if len(selected_for_pruning) < num_to_prune and self.eclipse_protection_enabled:
            remaining_to_prune = num_to_prune - len(selected_for_pruning)
            diversity_pruned = self._prune_for_ip_diversity(
                topic, peer_scores, selected_for_pruning, remaining_to_prune
            )
            selected_for_pruning.extend(diversity_pruned)

        # Strategy 3: If we still need more, prune lowest scoring peers
        if len(selected_for_pruning) < num_to_prune:
            remaining_to_prune = num_to_prune - len(selected_for_pruning)
            for peer, score in peer_scores:
                if (
                    peer not in selected_for_pruning
                    and len(selected_for_pruning) < num_to_prune
                ):
                    selected_for_pruning.append(peer)

        return selected_for_pruning[:num_to_prune]

    def _prune_for_ip_diversity(
        self,
        topic: str,
        peer_scores: list[tuple[ID, float]],
        already_selected: list[ID],
        num_needed: int,
    ) -> list[ID]:
        """
        Select additional peers for pruning to maintain IP diversity.

        :param topic: The topic
        :param peer_scores: List of (peer_id, score) tuples sorted by score
        :param already_selected: Peers already selected for pruning
        :param num_needed: Number of additional peers needed
        :return: List of additional peer IDs to prune
        """
        if self.scorer is None or num_needed <= 0:
            return []

        scorer = self.scorer  # Type narrowing
        # Count IPs after removing already selected peers
        ip_counts: defaultdict[str, int] = defaultdict(int)
        remaining_peers: list[tuple[ID, float]] = []

        for peer, score in peer_scores:
            if peer not in already_selected:
                remaining_peers.append((peer, score))
                if peer in scorer.ip_by_peer:
                    ip = scorer.ip_by_peer[peer]
                    ip_counts[ip] += 1

        # Find IPs with excessive peers (more than 2 peers per IP)
        excessive_ips = {ip: count for ip, count in ip_counts.items() if count > 2}

        selected: list[ID] = []

        # Prune from excessive IPs, preferring lower-scoring peers
        for peer, score in remaining_peers:
            if len(selected) >= num_needed:
                break

            if peer in scorer.ip_by_peer:
                peer_ip = scorer.ip_by_peer[peer]
                if peer_ip in excessive_ips and excessive_ips[peer_ip] > 2:
                    selected.append(peer)
                    excessive_ips[peer_ip] -= 1

        return selected

    async def _maintain_mesh_quality(self, topic: str) -> None:
        """
        Perform ongoing mesh quality maintenance beyond basic degree bounds.

        :param topic: The topic to maintain
        """
        if topic not in self.mesh or self.scorer is None:
            return

        mesh_peers = self.mesh[topic]
        if len(mesh_peers) < 3:  # Too small to optimize
            return

        # Check if we should replace low-scoring peers with better alternatives
        await self._consider_peer_replacement(topic)

        # Ensure we maintain good connectivity patterns
        self._optimize_mesh_connectivity(topic)

    async def _consider_peer_replacement(self, topic: str) -> None:
        """
        Replace the worst mesh peer with a better alternative when beneficial.

        Performs mesh mutation, sends PRUNE to the removed peer and GRAFT to the
        new peer.

        :param topic: The topic to consider
        """
        if self.scorer is None or self.pubsub is None:
            return

        if topic not in self.mesh or topic not in self.pubsub.peer_topics:
            return

        mesh_peers = list(self.mesh[topic])
        if len(mesh_peers) < self.degree:
            return  # Don't replace if we're below target

        # Find the worst mesh peer
        scorer = self.scorer  # Type narrowing
        peer_scores = [(p, scorer.score(p, [topic])) for p in mesh_peers]
        peer_scores.sort(key=lambda x: x[1])  # Sort by score ascending
        worst_peer, worst_score = peer_scores[0]

        # Find potential replacements
        available_peers = set(self.pubsub.peer_topics[topic]) - set(mesh_peers)
        if not available_peers:
            return

        # Find best available peer
        best_replacement = None
        best_score = worst_score

        for peer in available_peers:
            if self._check_back_off(peer, topic):
                continue

            if not self.supports_scoring(peer):
                continue

            peer_score = scorer.score(peer, [topic])
            if peer_score > best_score + 0.1:  # Require meaningful improvement
                best_replacement = peer
                best_score = peer_score

        if best_replacement is None:
            return

        # Perform replacement: mutate mesh and emit PRUNE/GRAFT
        self.mesh[topic].discard(worst_peer)
        self.mesh[topic].add(best_replacement)

        if self.scorer is not None:
            self.scorer.on_leave_mesh(worst_peer, topic)
            self.scorer.on_join_mesh(best_replacement, topic)

        # Add back_off so we don't immediately re-graft the pruned peer
        self._add_back_off(worst_peer, topic, False)

        # Track PRUNE time for GRAFT flood protection
        self.graft_flood_tracking[worst_peer][topic] = time.time()

        logger.debug(
            "Replacing mesh peer %s (score: %.2f) with %s (score: %.2f) in topic %s",
            worst_peer,
            worst_score,
            best_replacement,
            best_score,
            topic,
        )

        try:
            await self.emit_prune(topic, worst_peer, self.do_px, False)
            await self.emit_graft(topic, best_replacement)
        except Exception as e:
            logger.warning("Failed to emit PRUNE/GRAFT during peer replacement: %s", e)
            # Revert mesh and scorer on failure
            self.mesh[topic].add(worst_peer)
            self.mesh[topic].discard(best_replacement)
            if self.scorer is not None:
                self.scorer.on_join_mesh(worst_peer, topic)
                self.scorer.on_leave_mesh(best_replacement, topic)
            # Clear back_off we added (peer stays in back_off until expiry)
            if topic in self.back_off and worst_peer in self.back_off[topic]:
                del self.back_off[topic][worst_peer]

    def _optimize_mesh_connectivity(self, topic: str) -> None:
        """
        Optimize mesh connectivity patterns for better resilience.

        Validates mesh invariants and applies lightweight optimizations.
        IP diversity is handled by _ensure_mesh_diversity and _prune_for_ip_diversity.
        Geographic/latency optimization would require additional metrics.

        :param topic: The topic to optimize
        """
        if topic not in self.mesh or self.pubsub is None:
            return

        mesh_peers = self.mesh[topic]
        effective_high = (
            self.adaptive_degree_high
            if self.adaptive_gossip_enabled
            else self.degree_high
        )

        # Sanity check: mesh should not exceed degree_high (handled in mesh_heartbeat,
        # but we verify here as a safeguard). No action needed if within bounds.
        if len(mesh_peers) > effective_high + 2:
            logger.debug(
                "Mesh for topic %s exceeds expected bounds (%d > %d)",
                topic,
                len(mesh_peers),
                effective_high,
            )

    def _periodic_security_cleanup(self) -> None:
        """
        Periodic cleanup of security-related data structures.
        """
        current_time = time.time()

        # Clean up old equivocation detection entries
        # Note: Message objects don't have _timestamp, so we'll just clear old entries
        # based on a simple size limit instead
        if len(self.equivocation_detection) > 1000:
            # Keep only the most recent 500 entries
            keys_to_remove = list(self.equivocation_detection.keys())[:-500]
            for key in keys_to_remove:
                del self.equivocation_detection[key]

        # Clean up old rate limiting data
        for peer_id in list(self.message_rate_limits.keys()):
            for topic in list(self.message_rate_limits[peer_id].keys()):
                timestamps = self.message_rate_limits[peer_id][topic]
                # Remove timestamps older than 2 seconds
                cutoff = current_time - 2.0
                timestamps[:] = [t for t in timestamps if t > cutoff]

                # Remove empty topic entries
                if not timestamps:
                    del self.message_rate_limits[peer_id][topic]

            # Remove empty peer entries
            if not self.message_rate_limits[peer_id]:
                del self.message_rate_limits[peer_id]

        # Clean up v1.4 rate limiting data
        for peer_id in list(self.iwant_request_limits.keys()):
            for request_type in list(self.iwant_request_limits[peer_id].keys()):
                timestamps = self.iwant_request_limits[peer_id][request_type]
                cutoff = current_time - 2.0
                timestamps[:] = [t for t in timestamps if t > cutoff]

                if not timestamps:
                    del self.iwant_request_limits[peer_id][request_type]

            if not self.iwant_request_limits[peer_id]:
                del self.iwant_request_limits[peer_id]

        for peer_id in list(self.ihave_message_limits.keys()):
            for topic in list(self.ihave_message_limits[peer_id].keys()):
                timestamps = self.ihave_message_limits[peer_id][topic]
                cutoff = current_time - 2.0
                timestamps[:] = [t for t in timestamps if t > cutoff]

                if not timestamps:
                    del self.ihave_message_limits[peer_id][topic]

            if not self.ihave_message_limits[peer_id]:
                del self.ihave_message_limits[peer_id]

        # Clean up old GRAFT flood tracking (keep for 30 seconds)
        graft_cutoff = current_time - 30.0
        for peer_id in list(self.graft_flood_tracking.keys()):
            for topic in list(self.graft_flood_tracking[peer_id].keys()):
                if self.graft_flood_tracking[peer_id][topic] <= graft_cutoff:
                    del self.graft_flood_tracking[peer_id][topic]

            if not self.graft_flood_tracking[peer_id]:
                del self.graft_flood_tracking[peer_id]
