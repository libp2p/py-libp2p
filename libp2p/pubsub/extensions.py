"""
GossipSub v1.3 Extensions Control Message support.

Spec: https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.3.md
extensions.proto: https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/extensions/extensions.proto
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging

from libp2p.peer.id import ID

from .pb import rpc_pb2

logger = logging.getLogger("libp2p.pubsub.extensions")

ReportMisbehaviour = Callable[[ID], None]


@dataclass
class PeerExtensions:
    """
    Describes the set of GossipSub v1.3 extensions that a peer supports.
    """

    # --- Canonical extensions (field numbers < 0x200000) ---
    topic_observation: bool = False

    # --- Experimental extensions (field numbers > 0x200000) ---
    test_extension: bool = False

    # Large Message Segmentation.
    # Spec: extensions/experimental/large-message-segmentation.md
    large_message_segmentation: bool = False

    # ------------------------------------------------------------------

    @classmethod
    def from_control_extensions(cls, ext: rpc_pb2.ControlExtensions) -> PeerExtensions:
        return cls(
            topic_observation=ext.topicObservation,
            test_extension=ext.testExtension,
            large_message_segmentation=ext.largeMessageSegmentation,
        )

    def to_control_extensions(self) -> rpc_pb2.ControlExtensions:
        kwargs: dict[str, bool] = {}
        if self.topic_observation:
            kwargs["topicObservation"] = True
        if self.test_extension:
            kwargs["testExtension"] = True
        if self.large_message_segmentation:
            kwargs["largeMessageSegmentation"] = True
        return rpc_pb2.ControlExtensions(**kwargs)

    def has_any(self) -> bool:
        return (
            self.topic_observation
            or self.test_extension
            or self.large_message_segmentation
        )

    def supports_topic_observation(self) -> bool:
        return self.topic_observation

    def supports_test_extension(self) -> bool:
        return self.test_extension

    def supports_large_message_segmentation(self) -> bool:
        return self.large_message_segmentation


@dataclass
class ExtensionsState:
    """
    Per-router state for the GossipSub v1.3 extension exchange protocol.
    """

    my_extensions: PeerExtensions = field(default_factory=PeerExtensions)

    _peer_extensions: dict[ID, PeerExtensions] = field(
        default_factory=dict, init=False, repr=False
    )
    _sent_extensions: set[ID] = field(
        default_factory=set, init=False, repr=False
    )
    _report_misbehaviour: ReportMisbehaviour | None = field(
        default=None, init=False, repr=False
    )

    def set_report_misbehaviour(self, callback: ReportMisbehaviour | None) -> None:
        self._report_misbehaviour = callback

    # ------------------------------------------------------------------
    # Sending side
    # ------------------------------------------------------------------

    def build_hello_extensions(self, peer_id: ID, hello: rpc_pb2.RPC) -> rpc_pb2.RPC:
        if not self.my_extensions.has_any():
            self._sent_extensions.add(peer_id)
            return hello

        if not hello.HasField("control"):
            hello.control.CopyFrom(rpc_pb2.ControlMessage())
        hello.control.extensions.CopyFrom(self.my_extensions.to_control_extensions())
        self._sent_extensions.add(peer_id)

        logger.debug(
            "Sent extensions to peer %s: topic_observation=%s test_extension=%s "
            "large_message_segmentation=%s",
            peer_id,
            self.my_extensions.topic_observation,
            self.my_extensions.test_extension,
            self.my_extensions.large_message_segmentation,
        )

        if peer_id in self._peer_extensions:
            self._activate_peer(peer_id)
        return hello

    # ------------------------------------------------------------------
    # Receiving side
    # ------------------------------------------------------------------

    def handle_rpc(self, rpc: rpc_pb2.RPC, peer_id: ID) -> None:
        if peer_id not in self._peer_extensions:
            peer_ext = self._extract_peer_extensions(rpc)
            self._peer_extensions[peer_id] = peer_ext
            logger.debug(
                "Received extensions from peer %s: topic_observation=%s "
                "test_extension=%s large_message_segmentation=%s",
                peer_id,
                peer_ext.topic_observation,
                peer_ext.test_extension,
                peer_ext.large_message_segmentation,
            )
            if peer_id in self._sent_extensions:
                self._activate_peer(peer_id)
        else:
            if self._rpc_has_extensions(rpc):
                logger.warning(
                    "Peer %s sent a duplicate Extensions control message – "
                    "this is a protocol violation (GossipSub v1.3 spec rule 2).",
                    peer_id,
                )
                if self._report_misbehaviour is not None:
                    self._report_misbehaviour(peer_id)

    def remove_peer(self, peer_id: ID) -> None:
        self._peer_extensions.pop(peer_id, None)
        self._sent_extensions.discard(peer_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def peer_supports_topic_observation(self, peer_id: ID) -> bool:
        ext = self._peer_extensions.get(peer_id)
        return ext is not None and ext.topic_observation

    def peer_supports_test_extension(self, peer_id: ID) -> bool:
        ext = self._peer_extensions.get(peer_id)
        return ext is not None and ext.test_extension

    def peer_supports_large_message_segmentation(self, peer_id: ID) -> bool:
        ext = self._peer_extensions.get(peer_id)
        return ext is not None and ext.large_message_segmentation

    def both_support_topic_observation(self, peer_id: ID) -> bool:
        return (
            self.my_extensions.topic_observation
            and self.peer_supports_topic_observation(peer_id)
        )

    def both_support_test_extension(self, peer_id: ID) -> bool:
        return (
            self.my_extensions.test_extension
            and self.peer_supports_test_extension(peer_id)
        )

    def both_support_large_message_segmentation(self, peer_id: ID) -> bool:
        return (
            self.my_extensions.large_message_segmentation
            and self.peer_supports_large_message_segmentation(peer_id)
        )

    def get_peer_extensions(self, peer_id: ID) -> PeerExtensions | None:
        return self._peer_extensions.get(peer_id)

    def sent_extensions_to(self, peer_id: ID) -> bool:
        return peer_id in self._sent_extensions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rpc_has_extensions(rpc: rpc_pb2.RPC) -> bool:
        return rpc.HasField("control") and rpc.control.HasField("extensions")

    @staticmethod
    def _extract_peer_extensions(rpc: rpc_pb2.RPC) -> PeerExtensions:
        if ExtensionsState._rpc_has_extensions(rpc):
            return PeerExtensions.from_control_extensions(rpc.control.extensions)
        return PeerExtensions()

    def _activate_peer(self, peer_id: ID) -> None:
        peer_ext = self._peer_extensions[peer_id]
        if self.my_extensions.topic_observation and peer_ext.topic_observation:
            logger.debug("Topic Observation extension active with peer %s.", peer_id)
        if self.my_extensions.test_extension and peer_ext.test_extension:
            logger.debug("Test extension active with peer %s.", peer_id)
        if (
            self.my_extensions.large_message_segmentation
            and peer_ext.large_message_segmentation
        ):
            logger.debug(
                "Large Message Segmentation extension active with peer %s.",
                peer_id,
            )


class TopicObservationState:
    """
    Manages the Topic Observation extension state for a single GossipSub router.
    """

    def __init__(self) -> None:
        self._observing: dict[str, set[ID]] = {}
        self._observers: dict[str, set[ID]] = {}

    def add_observing(self, topic: str, subscriber_peer: ID) -> None:
        self._observing.setdefault(topic, set()).add(subscriber_peer)

    def remove_observing(self, topic: str, subscriber_peer: ID) -> None:
        peers = self._observing.get(topic)
        if peers is not None:
            peers.discard(subscriber_peer)
            if not peers:
                del self._observing[topic]

    def is_observing(self, topic: str) -> bool:
        return bool(self._observing.get(topic))

    def add_observer(self, topic: str, observer_peer: ID) -> None:
        self._observers.setdefault(topic, set()).add(observer_peer)

    def remove_observer(self, topic: str, observer_peer: ID) -> None:
        peers = self._observers.get(topic)
        if peers is not None:
            peers.discard(observer_peer)
            if not peers:
                del self._observers[topic]

    def get_observers(self, topic: str) -> set[ID]:
        return self._observers.get(topic, set())

    def clear_peer(self, peer_id: ID) -> None:
        for topic in list(self._observing.keys()):
            self._observing[topic].discard(peer_id)
            if not self._observing[topic]:
                del self._observing[topic]
        for topic in list(self._observers.keys()):
            self._observers[topic].discard(peer_id)
            if not self._observers[topic]:
                del self._observers[topic]
