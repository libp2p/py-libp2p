"""
GossipSub v1.3 Extensions Control Message support.

Spec: https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.3.md
extensions.proto: https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/extensions/extensions.proto

Design mirrors the go-libp2p reference implementation (pubsub/extensions.go in
libp2p/go-libp2p-pubsub).

Key spec rules implemented here:
  1. Extensions control message MUST be in the FIRST message on the stream.
  2. Extensions control message MUST NOT be sent more than once per peer.
  3. A second Extensions control message from the same peer is misbehaviour.
  4. Peers MUST ignore unknown extensions (forward-compatible).
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
import logging

from libp2p.peer.id import (
    ID,
)

from .pb import (
    rpc_pb2,
)

logger = logging.getLogger("libp2p.pubsub.extensions")


@dataclass
class PeerExtensions:
    """
    Describes the set of GossipSub v1.3 extensions that a peer supports.

    Each field corresponds to one optional extension.  When we receive a peer's
    ``ControlExtensions`` protobuf we decode it into a ``PeerExtensions``
    instance.  When we build our own hello packet we encode our
    ``PeerExtensions`` into the outgoing ``ControlExtensions`` protobuf.

    Adding a new extension:
      1. Add a ``bool`` field here (default ``False``).
      2. Set the field in :meth:`from_control_extensions`.
      3. Populate the field in :meth:`to_control_extensions`.
      4. Add any per-peer activation logic in :class:`ExtensionsState`.
    """

    # Topic Observation extension (GossipSub v1.3 Topic Observation proposal).
    # https://ethresear.ch/t/gossipsub-topic-observation-proposed-gossipsub-1-3/20907
    topic_observation: bool = False

    # testExtension – field 6492434 – used exclusively for cross-implementation
    # interoperability testing (go-libp2p / rust-libp2p / py-libp2p).
    test_extension: bool = False

    @classmethod
    def from_control_extensions(cls, ext: rpc_pb2.ControlExtensions) -> PeerExtensions:
        """
        Decode a wire ``ControlExtensions`` protobuf into a ``PeerExtensions``.

        Unknown fields in ``ext`` are silently ignored per spec rule 3
        ("Peers MUST ignore unknown extensions").
        """
        return cls(
            topic_observation=ext.topicObservation,
            test_extension=ext.testExtension,
        )

    def to_control_extensions(self) -> rpc_pb2.ControlExtensions:
        """
        Encode this ``PeerExtensions`` into a wire ``ControlExtensions`` protobuf.

        Only fields that are ``True`` are set; unset optional proto fields are
        omitted from the serialised bytes (proto2 semantics).
        """
        kwargs: dict[str, bool] = {}
        if self.topic_observation:
            kwargs["topicObservation"] = True
        if self.test_extension:
            kwargs["testExtension"] = True
        return rpc_pb2.ControlExtensions(**kwargs)

    def has_any(self) -> bool:
        """Return True if the local peer supports at least one extension."""
        return self.topic_observation or self.test_extension

    def supports_topic_observation(self) -> bool:
        return self.topic_observation

    def supports_test_extension(self) -> bool:
        return self.test_extension


@dataclass
class ExtensionsState:
    """
    Per-router state for the GossipSub v1.3 extension exchange protocol.

    Mirrors ``extensionsState`` in go-libp2p's ``extensions.go``.

    Lifecycle (per peer):
      1. ``build_hello_extensions(peer_id)`` is called when we open a stream
         and are about to send the first message.  It mutates the hello RPC
         in-place, adding ``control.extensions`` when appropriate, and records
         that we have sent extensions to this peer.
      2. ``handle_rpc(rpc, peer_id)`` is called on every incoming RPC.
         - For the *first* RPC from a peer it records their extensions.
         - For subsequent RPCs it checks for a duplicate extensions field and
           calls ``report_misbehaviour`` if one is found.

    The ``report_misbehaviour`` callback is expected to apply a peer-score
    penalty (analogous to go-libp2p's ``reportMisbehavior``).
    """

    # Extensions we advertise to other peers.
    my_extensions: PeerExtensions = field(default_factory=PeerExtensions)

    # Extensions we have received from each peer (populated on first RPC).
    _peer_extensions: dict[ID, PeerExtensions] = field(
        default_factory=dict, init=False, repr=False
    )

    # Set of peer IDs to whom we have already sent the extensions control message.
    # Used to enforce the "at most once" rule on the sending side.
    _sent_extensions: set[ID] = field(default_factory=set, init=False, repr=False)

    # Optional callback invoked when a peer sends a duplicate extensions message.
    # Signature: report_misbehaviour(peer_id: ID) -> None
    _report_misbehaviour: object = field(default=None, init=False, repr=False)

    def set_report_misbehaviour(self, callback: object) -> None:
        """
        Register the callback that penalises misbehaving peers.

        :param callback: callable(peer_id: ID) -> None
        """
        self._report_misbehaviour = callback

    # ------------------------------------------------------------------
    # Sending side
    # ------------------------------------------------------------------

    def build_hello_extensions(self, peer_id: ID, hello: rpc_pb2.RPC) -> rpc_pb2.RPC:
        """
        Attach our ``ControlExtensions`` to *hello* if this is a v1.3 peer and
        we support at least one extension.

        Per spec rule 1: "If a peer supports any extension, the Extensions
        control message MUST be included in the first message on the stream."

        Per spec rule 2: "It MUST NOT be sent more than once."

        This method MUST be called exactly once per peer, before the hello
        packet is written to the stream.

        :param peer_id: the remote peer we are greeting.
        :param hello:   the RPC packet being constructed (mutated in-place).
        :return:        the (possibly mutated) RPC packet.
        """
        if not self.my_extensions.has_any():
            # Nothing to advertise – still record that we did our part so that
            # the "sent" tracking is consistent.
            self._sent_extensions.add(peer_id)
            return hello

        # Ensure control sub-message exists.
        if not hello.HasField("control"):
            hello.control.CopyFrom(rpc_pb2.ControlMessage())

        hello.control.extensions.CopyFrom(self.my_extensions.to_control_extensions())

        self._sent_extensions.add(peer_id)
        logger.debug(
            "Sent extensions to peer %s: topic_observation=%s test_extension=%s",
            peer_id,
            self.my_extensions.topic_observation,
            self.my_extensions.test_extension,
        )

        # If we already received their extensions (unlikely race on the first
        # message, but handled for correctness), activate the shared features.
        if peer_id in self._peer_extensions:
            self._activate_peer(peer_id)

        return hello

    # ------------------------------------------------------------------
    # Receiving side
    # ------------------------------------------------------------------

    def handle_rpc(self, rpc: rpc_pb2.RPC, peer_id: ID) -> None:
        """
        Process the extensions portion of an incoming RPC.

        Called for every incoming RPC.  On the very first call for a given
        peer this records the peer's extensions; on subsequent calls it checks
        for a duplicate ``control.extensions`` field.

        :param rpc:     the full incoming RPC message.
        :param peer_id: the peer who sent the RPC.
        """
        if peer_id not in self._peer_extensions:
            # This is the first RPC from this peer.
            peer_ext = self._extract_peer_extensions(rpc)
            self._peer_extensions[peer_id] = peer_ext

            logger.debug(
                "Received extensions from peer %s: topic_observation=%s "
                "test_extension=%s",
                peer_id,
                peer_ext.topic_observation,
                peer_ext.test_extension,
            )

            # If we have already sent our extensions, the exchange is complete.
            if peer_id in self._sent_extensions:
                self._activate_peer(peer_id)
        else:
            # We already have this peer's extensions.  A second
            # ``control.extensions`` field is a protocol violation.
            if self._rpc_has_extensions(rpc):
                logger.warning(
                    "Peer %s sent a duplicate Extensions control message – "
                    "this is a protocol violation (GossipSub v1.3 spec rule 2).",
                    peer_id,
                )
                if callable(self._report_misbehaviour):
                    self._report_misbehaviour(peer_id)  # type: ignore[operator]

    # ------------------------------------------------------------------
    # Peer lifecycle
    # ------------------------------------------------------------------

    def remove_peer(self, peer_id: ID) -> None:
        """
        Clean up all extension state for a disconnected peer.

        :param peer_id: the peer that disconnected.
        """
        self._peer_extensions.pop(peer_id, None)
        self._sent_extensions.discard(peer_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def peer_supports_topic_observation(self, peer_id: ID) -> bool:
        """
        Return True if *peer_id* has advertised the Topic Observation extension.

        :param peer_id: the remote peer to query.
        """
        ext = self._peer_extensions.get(peer_id)
        return ext is not None and ext.topic_observation

    def peer_supports_test_extension(self, peer_id: ID) -> bool:
        """
        Return True if *peer_id* has advertised the test extension.

        :param peer_id: the remote peer to query.
        """
        ext = self._peer_extensions.get(peer_id)
        return ext is not None and ext.test_extension

    def both_support_topic_observation(self, peer_id: ID) -> bool:
        """
        Return True if both this node and *peer_id* support Topic Observation.

        Feature activation is only valid when both sides have advertised
        support (per GossipSub v1.3 spec section on extension behaviour).

        :param peer_id: the remote peer to query.
        """
        return (
            self.my_extensions.topic_observation
            and self.peer_supports_topic_observation(peer_id)
        )

    def both_support_test_extension(self, peer_id: ID) -> bool:
        """
        Return True if both this node and *peer_id* support the test extension.

        :param peer_id: the remote peer to query.
        """
        return self.my_extensions.test_extension and self.peer_supports_test_extension(
            peer_id
        )

    def get_peer_extensions(self, peer_id: ID) -> PeerExtensions | None:
        """
        Return the extensions advertised by *peer_id*, or ``None`` if we have
        not yet received the peer's first message.

        :param peer_id: the remote peer to query.
        """
        return self._peer_extensions.get(peer_id)

    def sent_extensions_to(self, peer_id: ID) -> bool:
        """
        Return True if we have already sent extensions to *peer_id*.

        :param peer_id: the remote peer to query.
        """
        return peer_id in self._sent_extensions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rpc_has_extensions(rpc: rpc_pb2.RPC) -> bool:
        """Return True if *rpc* carries a ``control.extensions`` field."""
        return rpc.HasField("control") and rpc.control.HasField("extensions")

    @staticmethod
    def _extract_peer_extensions(rpc: rpc_pb2.RPC) -> PeerExtensions:
        """
        Decode the peer's extensions from an RPC, returning an empty
        ``PeerExtensions`` if none are present.
        """
        if ExtensionsState._rpc_has_extensions(rpc):
            return PeerExtensions.from_control_extensions(rpc.control.extensions)
        return PeerExtensions()

    def _activate_peer(self, peer_id: ID) -> None:
        """
        Called once both sides have exchanged extensions.  Logs the active
        feature set; subclasses / callers can extend this for bookkeeping.

        :param peer_id: the peer whose extension handshake just completed.
        """
        peer_ext = self._peer_extensions[peer_id]
        if self.my_extensions.topic_observation and peer_ext.topic_observation:
            logger.debug("Topic Observation extension active with peer %s.", peer_id)
        if self.my_extensions.test_extension and peer_ext.test_extension:
            logger.debug("Test extension active with peer %s.", peer_id)


# ---------------------------------------------------------------------------
# Topic Observation state (per router)
# ---------------------------------------------------------------------------


class TopicObservationState:
    """
    Manages the Topic Observation extension state for a single GossipSub router.

    Spec: https://ethresear.ch/t/gossipsub-topic-observation-proposed-gossipsub-1-3/20907

    Two directions:

    * **Outbound (we are the observer):** We send ``OBSERVE`` to subscribing
      peers and receive ``IHAVE`` notifications.  We do NOT receive full
      message payloads unless we explicitly request them.

    * **Inbound (we are the subscriber):** We receive ``OBSERVE`` / ``UNOBSERVE``
      from observing peers and send ``IHAVE`` to them when new messages arrive.

    The actual IHAVE emission is handled in ``GossipSub.publish()`` so that
    notification is immediate (not deferred to the heartbeat) per the spec.
    """

    def __init__(self) -> None:
        # Topics we are currently observing (outbound).
        # topic -> set of subscriber peer IDs we sent OBSERVE to.
        self._observing: dict[str, set[ID]] = {}

        # Peers that are observing us (inbound).
        # topic -> set of observer peer IDs.
        self._observers: dict[str, set[ID]] = {}

    # ------------------------------------------------------------------
    # Outbound: this node is an observer
    # ------------------------------------------------------------------

    def add_observing(self, topic: str, subscriber_peer: ID) -> None:
        """
        Record that we are observing *topic* via *subscriber_peer*.

        Called after we emit an OBSERVE control message.

        :param topic:           the topic we sent OBSERVE for.
        :param subscriber_peer: the subscribing peer we sent OBSERVE to.
        """
        self._observing.setdefault(topic, set()).add(subscriber_peer)

    def remove_observing(self, topic: str, subscriber_peer: ID) -> None:
        """
        Record that we stopped observing *topic* via *subscriber_peer*.

        Called after we emit an UNOBSERVE control message.

        :param topic:           the topic we sent UNOBSERVE for.
        :param subscriber_peer: the peer we sent UNOBSERVE to.
        """
        peers = self._observing.get(topic)
        if peers is not None:
            peers.discard(subscriber_peer)
            if not peers:
                del self._observing[topic]

    def is_observing(self, topic: str) -> bool:
        """
        Return True if we are currently observing *topic*.

        :param topic: the topic to query.
        """
        return bool(self._observing.get(topic))

    # ------------------------------------------------------------------
    # Inbound: remote peers are observing us
    # ------------------------------------------------------------------

    def add_observer(self, topic: str, observer_peer: ID) -> None:
        """
        Record that *observer_peer* wants to observe *topic* from us.

        Called when we handle an incoming OBSERVE control message.

        :param topic:         the topic the peer wants to observe.
        :param observer_peer: the peer that sent us the OBSERVE.
        """
        self._observers.setdefault(topic, set()).add(observer_peer)
        logger.debug(
            "Peer %s is now observing topic '%s' via us.", observer_peer, topic
        )

    def remove_observer(self, topic: str, observer_peer: ID) -> None:
        """
        Remove *observer_peer* from the observer list for *topic*.

        Called when we handle an incoming UNOBSERVE control message.

        :param topic:         the topic the peer wants to stop observing.
        :param observer_peer: the peer that sent us the UNOBSERVE.
        """
        peers = self._observers.get(topic)
        if peers is not None:
            peers.discard(observer_peer)
            if not peers:
                del self._observers[topic]
            logger.debug(
                "Peer %s stopped observing topic '%s' via us.",
                observer_peer,
                topic,
            )

    def get_observers(self, topic: str) -> set[ID]:
        """
        Return the set of peers that are currently observing *topic* from us.

        :param topic: the topic to query.
        :return:      a copy of the observer set (empty set if none).
        """
        return set(self._observers.get(topic, set()))

    def remove_peer(self, peer_id: ID) -> None:
        """
        Clean up all Topic Observation state for a disconnected peer.

        :param peer_id: the peer that disconnected.
        """
        for topic in list(self._observers):
            self._observers[topic].discard(peer_id)
            if not self._observers[topic]:
                del self._observers[topic]

        for topic in list(self._observing):
            self._observing[topic].discard(peer_id)
            if not self._observing[topic]:
                del self._observing[topic]

    # ------------------------------------------------------------------
    # TODO for contributor:
    # Implement the following methods to complete the outbound observer path.
    # ------------------------------------------------------------------

    def get_observing_topics(self) -> set[str]:
        """
        Return the set of topics this node is currently observing (outbound).

        Implementation hint:
          Return ``set(self._observing.keys())``.

        :return: set of topic strings we sent OBSERVE for.
        """
        # TODO: Return the set of topics from self._observing.
        raise NotImplementedError(
            "get_observing_topics() is left as an easy task for contributors. "
            "Hint: return set(self._observing.keys())"
        )

    def get_subscriber_peers_for_topic(self, topic: str) -> set[ID]:
        """
        Return the set of subscriber peers we sent OBSERVE to for *topic*.

        Implementation hint:
          Return a copy of ``self._observing.get(topic, set())``.

        :param topic: the topic to query.
        :return: set of subscriber peer IDs we are observing through.
        """
        # TODO: Return a copy of self._observing.get(topic, set()).
        raise NotImplementedError(
            "get_subscriber_peers_for_topic() is left as an easy task for "
            "contributors. Hint: return set(self._observing.get(topic, set()))"
        )
