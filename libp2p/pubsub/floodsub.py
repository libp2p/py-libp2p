from collections.abc import (
    Iterable,
    Sequence,
)
import logging
import time

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
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.pubsub.utils import maybe_consume_signed_record

from .exceptions import (
    NoPubsubAttached,
    PubsubRouterError,
)
from .pb import (
    rpc_pb2,
)
from .pubsub import (
    Pubsub,
)

PROTOCOL_ID = TProtocol("/floodsub/1.0.0")

logger = logging.getLogger("libp2p.pubsub.floodsub")


class FloodSub(IPubsubRouter):
    mesh: dict[str, set[ID]]
    peer_protocol: dict[ID, TProtocol]
    protocols: list[TProtocol]
    pubsub: Pubsub | None
    time_since_last_publish: dict[str, int]

    def __init__(self, protocols: Sequence[TProtocol]) -> None:
        self.protocols = list(protocols)
        self.pubsub = None
        self.mesh = {}
        self.peer_protocol = {}
        self.time_since_last_publish = {}

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
        logger.debug("attached to pubsub")

    def add_peer(self, peer_id: ID, protocol_id: TProtocol | None) -> None:
        """
        Notifies the router that a new peer has been connected.

        :param peer_id: id of peer to add
        """
        logger.debug("adding peer %s with protocol %s", peer_id, protocol_id)

        if protocol_id is None:
            raise ValueError("Protocol cannot be None")

        if protocol_id not in (PROTOCOL_ID):
            raise ValueError(f"Protocol={protocol_id} is not supported")
        self.peer_protocol[peer_id] = protocol_id

    def remove_peer(self, peer_id: ID) -> None:
        """
        Notifies the router that a peer has been disconnected.

        :param peer_id: id of peer to remove
        """
        logger.debug("removing peer %s", peer_id)

        for topic in self.mesh:
            self.mesh[topic].discard(peer_id)

        self.peer_protocol.pop(peer_id, None)

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

        # Checkpoint
        await trio.lowlevel.checkpoint()

    async def publish(self, msg_forwarder: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """
        Invoked to forward a new message that has been validated. This is where
        the "flooding" part of floodsub happens.

        With flooding, routing is almost trivial: for each incoming message,
        forward to all known peers in the topic. There is a bit of logic,
        as the router maintains a timed cache of previous messages,
        so that seen messages are not further forwarded.
        It also never forwards a message back to the source
        or the peer that forwarded the message.
        :param msg_forwarder: peer ID of the peer who forwards the message to us
        :param pubsub_msg: pubsub message in protobuf.
        """
        peers_gen = set(
            self._get_peers_to_send(
                pubsub_msg.topicIDs,
                msg_forwarder=msg_forwarder,
                origin=ID(pubsub_msg.from_id),
            )
        )
        rpc_msg = rpc_pb2.RPC(publish=[pubsub_msg])

        # Add the senderRecord of the peer in the RPC msg
        if isinstance(self.pubsub, Pubsub):
            envelope_bytes, _ = env_to_send_in_RPC(self.pubsub.host)
            rpc_msg.senderRecord = envelope_bytes

        logger.debug("publishing message %s", pubsub_msg)

        if self.pubsub is None:
            raise PubsubRouterError("pubsub not attached to this instance")
        else:
            pubsub = self.pubsub

        for peer_id in peers_gen:
            if peer_id not in pubsub.peers:
                continue
            stream = pubsub.peers[peer_id]
            await pubsub.write_msg(stream, rpc_msg)

        for topic in pubsub_msg.topicIDs:
            self.time_since_last_publish[topic] = int(time.time())

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
        self.time_since_last_publish.pop(topic, None)

    async def leave(self, topic: str) -> None:
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.

        :param topic: topic to leave
        """
        logger.debug("leaving topic %s", topic)

        if topic not in self.mesh:
            return

        self.mesh.pop(topic, None)

    def _get_peers_to_send(
        self, topic_ids: Iterable[str], msg_forwarder: ID, origin: ID
    ) -> Iterable[ID]:
        """
        Get the eligible peers to send the data to.

        :param msg_forwarder: peer ID of the peer who forwards the message to us.
        :param origin: peer id of the peer the message originate from.
        :return: a generator of the peer ids who we send data to.
        """
        if self.pubsub is None:
            raise PubsubRouterError("pubsub not attached to this instance")
        else:
            pubsub = self.pubsub
        for topic in topic_ids:
            if topic not in pubsub.peer_topics:
                continue
            for peer_id in pubsub.peer_topics[topic]:
                if peer_id in (msg_forwarder, origin):
                    continue
                if peer_id not in pubsub.peers:
                    continue
                if peer_id not in self.peer_protocol:
                    continue

                if self.peer_protocol[peer_id] != PROTOCOL_ID:
                    continue
                yield peer_id
