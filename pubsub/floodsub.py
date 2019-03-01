from .pubsub_router_interface import IPubsubRouter

class FloodSub(IPubsubRouter):

    def __init__(self, protocols):
        self.protocols = protocols

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
        """
        pass

    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        """
        pass

    def handle_rpc(self, rpc):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        """
        pass

    async def publish(self, peer_id, message):
        """
        Invoked to forward a new message that has been validated.
        This is where the "flooding" part of floodsub happens

        With flooding, routing is almost trivial: for each incoming message, 
        forward to all known peers in the topic. There is a bit of logic, 
        as the router maintains a timed cache of previous messages, 
        so that seen messages are not further forwarded. 
        It also never forwards a message back to the source 
        or the peer that forwarded the message.
        """

        print("publish started")

        # Encode message
        encoded_msg = message.encode()
        
        # Get message sender, origin, and topics
        msg_sender = str(peer_id)
        msg_origin = message.split("\n")[1]
        topics = self.pubsub.get_topics_in_talk_msg(message)
        print("publish topics are " + str(topics))
        print("publish peer topics are " + str(self.pubsub.peer_topics))

        for topic in topics:
            if topic in self.pubsub.peer_topics:
                for peer_id_in_topic in self.pubsub.peer_topics[topic]:
                    # Forward to all known peers in the topic that are not the
                    # message sender and are not the message origin
                    if peer_id_in_topic != msg_sender and peer_id_in_topic != msg_origin:
                        stream = self.pubsub.peers[peer_id_in_topic]
                        print("publish should write")
                        await stream.write(encoded_msg)
                        print("publish wrote")
                    else:
                        # Implies publish did not write
                        print("REACHED2")


    def join(self, topic):
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        """
        pass

    def leave(self, topic):
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        """
        pass

