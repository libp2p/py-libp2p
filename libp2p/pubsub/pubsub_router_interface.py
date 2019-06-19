from abc import ABC, abstractmethod


class IPubsubRouter(ABC):
    @abstractmethod
    def get_protocols(self):
        """
        :return: the list of protocols supported by the router
        """

    @abstractmethod
    def attach(self, pubsub):
        """
        Attach is invoked by the PubSub constructor to attach the router to a
        freshly initialized PubSub instance.
        :param pubsub: pubsub instance to attach to
        """

    @abstractmethod
    def add_peer(self, peer_id, protocol_id):
        """
        Notifies the router that a new peer has been connected
        :param peer_id: id of peer to add
        """

    @abstractmethod
    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """

    @abstractmethod
    def handle_rpc(self, rpc, sender_peer_id):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        TODO: Check if this interface is ok. It's not the exact same as the go code, but the go
        code is really confusing with the msg origin, they specify `rpc.from` even when the rpc
        shouldn't have a from
        :param rpc: rpc message
        """

    @abstractmethod
    def publish(self, sender_peer_id, rpc_message):
        """
        Invoked to forward a new message that has been validated
        :param sender_peer_id: peer_id of message sender
        :param rpc_message: message to forward
        """

    @abstractmethod
    def join(self, topic):
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """

    @abstractmethod
    def leave(self, topic):
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """
