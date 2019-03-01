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
        """

    @abstractmethod
    def remove_peer(self, peer_id):
        """
        Notifies the router that a peer has been disconnected
        """

    @abstractmethod
    def handle_rpc(self, rpc):
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        """

    @abstractmethod
    def publish(self, peer_id, message):
        """
        Invoked to forward a new message that has been validated
        """

    @abstractmethod
    def join(self, topic):
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        """

    @abstractmethod
    def leave(self, topic):
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        """
        