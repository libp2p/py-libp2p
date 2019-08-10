from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

from libp2p.peer.id import ID
from libp2p.typing import TProtocol

from .pb import rpc_pb2

if TYPE_CHECKING:
    from .pubsub import Pubsub  # noqa: F401


class IPubsubRouter(ABC):
    @abstractmethod
    def get_protocols(self) -> List[TProtocol]:
        """
        :return: the list of protocols supported by the router
        """

    @abstractmethod
    def attach(self, pubsub: "Pubsub") -> None:
        """
        Attach is invoked by the PubSub constructor to attach the router to a
        freshly initialized PubSub instance.
        :param pubsub: pubsub instance to attach to
        """

    @abstractmethod
    def add_peer(self, peer_id: ID, protocol_id: TProtocol) -> None:
        """
        Notifies the router that a new peer has been connected
        :param peer_id: id of peer to add
        """

    @abstractmethod
    def remove_peer(self, peer_id: ID) -> None:
        """
        Notifies the router that a peer has been disconnected
        :param peer_id: id of peer to remove
        """

    @abstractmethod
    async def handle_rpc(self, rpc: rpc_pb2.RPC, sender_peer_id: ID) -> None:
        """
        Invoked to process control messages in the RPC envelope.
        It is invoked after subscriptions and payload messages have been processed
        TODO: Check if this interface is ok. It's not the exact same as the go code, but the go
        code is really confusing with the msg origin, they specify `rpc.from` even when the rpc
        shouldn't have a from
        :param rpc: rpc message
        """

    # FIXME: Should be changed to type 'peer.ID'
    @abstractmethod
    async def publish(self, msg_forwarder: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """
        Invoked to forward a new message that has been validated
        :param msg_forwarder: peer_id of message sender
        :param pubsub_msg: pubsub message to forward
        """

    @abstractmethod
    async def join(self, topic: str) -> None:
        """
        Join notifies the router that we want to receive and
        forward messages in a topic. It is invoked after the
        subscription announcement
        :param topic: topic to join
        """

    @abstractmethod
    async def leave(self, topic: str) -> None:
        """
        Leave notifies the router that we are no longer interested in a topic.
        It is invoked after the unsubscription announcement.
        :param topic: topic to leave
        """
