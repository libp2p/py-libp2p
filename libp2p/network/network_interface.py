from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Any,
    Callable,
    Coroutine,
    Sequence,
    TYPE_CHECKING,
)

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.stream_muxer.muxed_connection_interface import IMuxedConn

from .stream.net_stream import NetStream

if TYPE_CHECKING:
    from .notifee_interface import INotifee


StreamHandlerFn = Callable[[NetStream], Coroutine[Any, Any, None]]


class INetwork(ABC):

    @abstractmethod
    def get_peer_id(self) -> ID:
        """
        :return: the peer id
        """

    @abstractmethod
    def dial_peer(self, peer_id: ID) -> Coroutine[Any, Any, IMuxedConn]:
        """
        dial_peer try to create a connection to peer_id

        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when no address if found for peer_id
        :return: muxed connection
        """

    @abstractmethod
    def set_stream_handler(self, protocol_id: str, stream_handler: StreamHandlerFn) -> bool:
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """

    @abstractmethod
    def new_stream(self,
                   peer_id: ID,
                   protocol_ids: Sequence[str]) -> Coroutine[Any, Any, NetStream]:
        """
        :param peer_id: peer_id of destination
        :param protocol_ids: available protocol ids to use for stream
        :return: net stream instance
        """

    @abstractmethod
    def listen(self, *args: Multiaddr) -> Coroutine[Any, Any, bool]:
        """
        :param *args: one or many multiaddrs to start listening on
        :return: True if at least one success
        """

    @abstractmethod
    def notify(self, notifee: 'INotifee') -> bool:
        """
        :param notifee: object implementing Notifee interface
        :return: true if notifee registered successfully, false otherwise
        """
