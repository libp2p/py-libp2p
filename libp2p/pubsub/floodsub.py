from typing import (
    Iterable,
)

from libp2p.peer.id import (
    ID,
    id_b58_decode,
)

from .pb import rpc_pb2
from .pubsub_router_interface import IPubsubRouter


class FloodSub(IPubsubRouter):
    # pylint: disable=no-member

    def __init__(self, protocols):
        self.protocols = protocols
        self.pubsub = None

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

    async def handle_rpc(self, rpc, sender_peer_id):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        :param rpc: rpc message
        """

    async def publish(self, src: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """
        Invoked to forward a new message that has been validated.
        This is where the "flooding" part of floodsub happens

        With flooding, routing is almost trivial: for each incoming message,
        forward to all known peers in the topic. There is a bit of logic,
        as the router maintains a timed cache of previous messages,
        so that seen messages are not further forwarded.
        It also never forwards a message back to the source
        or the peer that forwarded the message.
        :param src: the peer id of the peer who forwards the message to me.
        :param pubsub_msg: pubsub message in protobuf.
        """

        peers_gen = self._get_peers_to_send(
            pubsub_msg.topicIDs,
            src=src,
            origin=ID(pubsub_msg.from_id),
        )
        rpc_msg = rpc_pb2.RPC(
            publish=[pubsub_msg],
        )
        for peer_id in peers_gen:
            stream = self.pubsub.peers[str(peer_id)]
            await stream.write(rpc_msg.SerializeToString())

    def _get_peers_to_send(
            self,
            topic_ids: Iterable[str],
            src: ID,
            origin: ID) -> Iterable[ID]:
        """
        :return: the list of protocols supported by the router
        """
        for topic in topic_ids:
            if topic not in self.pubsub.peer_topics:
                continue
            for peer_id_str in self.pubsub.peer_topics[topic]:
                peer_id = id_b58_decode(peer_id_str)
                if peer_id in (src, origin):
                    continue
                # FIXME: Should change `self.pubsub.peers` to Dict[PeerID, ...]
                if str(peer_id) not in self.pubsub.peers:
                    continue
                yield peer_id

    async def join(self, topic):
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """

    async def leave(self, topic):
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """
