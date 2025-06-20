from collections.abc import (
    Iterable,
    Sequence,
)
import logging

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

from .exceptions import (
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
    protocols: list[TProtocol]

    pubsub: Pubsub | None

    def __init__(self, protocols: Sequence[TProtocol]) -> None:
        self.protocols = list(protocols)
        self.pubsub = None

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

    def add_peer(self, peer_id: ID, protocol_id: TProtocol | None) -> None:
        """
        Notifies the router that a new peer has been connected.

        :param peer_id: id of peer to add
        """

    def remove_peer(self, peer_id: ID) -> None:
        """
        Notifies the router that a peer has been disconnected.

        :param peer_id: id of peer to remove
        """

    async def handle_rpc(self, rpc: rpc_pb2.RPC, sender_peer_id: ID) -> None:
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed

        :param rpc: RPC message
        :param sender_peer_id: id of the peer who sent the message
        """
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

    async def join(self, topic: str) -> None:
        """
        Join notifies the router that we want to receive and forward messages
        in a topic. It is invoked after the subscription announcement.

        :param topic: topic to join
        """
        # Checkpoint
        await trio.lowlevel.checkpoint()

    async def leave(self, topic: str) -> None:
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.

        :param topic: topic to leave
        """
        # Checkpoint
        await trio.lowlevel.checkpoint()

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
                yield peer_id
