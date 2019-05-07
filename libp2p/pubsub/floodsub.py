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

    async def publish(self, sender_peer_id, rpc_message):
        """
        Invoked to forward a new message that has been validated.
        This is where the "flooding" part of floodsub happens

        With flooding, routing is almost trivial: for each incoming message,
        forward to all known peers in the topic. There is a bit of logic,
        as the router maintains a timed cache of previous messages,
        so that seen messages are not further forwarded.
        It also never forwards a message back to the source
        or the peer that forwarded the message.
        :param sender_peer_id: peer_id of message sender
        :param rpc_message: pubsub message in RPC string format
        """
        packet = rpc_pb2.RPC()
        packet.ParseFromString(rpc_message)
        msg_sender = str(sender_peer_id)
        # Deliver to self if self was origin
        # Note: handle_talk checks if self is subscribed to topics in message
        for message in packet.publish:
            decoded_from_id = message.from_id.decode('utf-8')
            if msg_sender == decoded_from_id and msg_sender == str(self.pubsub.host.get_id()):
                id_in_seen_msgs = (message.seqno, message.from_id)

                if id_in_seen_msgs not in self.pubsub.seen_messages:
                    self.pubsub.seen_messages[id_in_seen_msgs] = 1

                await self.pubsub.handle_talk(message)

            # Deliver to self and peers
            for topic in message.topicIDs:
                if topic in self.pubsub.peer_topics:
                    for peer_id_in_topic in self.pubsub.peer_topics[topic]:
                        # Forward to all known peers in the topic that are not the
                        # message sender and are not the message origin
                        if peer_id_in_topic not in (msg_sender, decoded_from_id):
                            stream = self.pubsub.peers[peer_id_in_topic]
                            # Create new packet with just publish message
                            new_packet = rpc_pb2.RPC()
                            new_packet.publish.extend([message])

                            # Publish the packet
                            await stream.write(new_packet.SerializeToString())

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
