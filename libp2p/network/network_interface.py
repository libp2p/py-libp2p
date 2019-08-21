from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Sequence

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.transport.listener_interface import IListener
from libp2p.typing import StreamHandlerFn, TProtocol

from .stream.net_stream_interface import INetStream

if TYPE_CHECKING:
    from .notifee_interface import INotifee  # noqa: F401


class INetwork(ABC):

    peerstore: IPeerStore
    connections: Dict[ID, IMuxedConn]
    listeners: Dict[str, IListener]

    @abstractmethod
    def get_peer_id(self) -> ID:
        """
        :return: the peer id
        """

    @abstractmethod
    async def dial_peer(self, peer_id: ID) -> IMuxedConn:
        """
        dial_peer try to create a connection to peer_id

        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when an error occurs
        :return: muxed connection
        """

    @abstractmethod
    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> bool:
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """

    @abstractmethod
    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id of destination
        :param protocol_ids: available protocol ids to use for stream
        :return: net stream instance
        """

    @abstractmethod
    async def listen(self, *multiaddrs: Sequence[Multiaddr]) -> bool:
        """
        :param multiaddrs: one or many multiaddrs to start listening on
        :return: True if at least one success
        """

    @abstractmethod
    def notify(self, notifee: "INotifee") -> bool:
        """
        :param notifee: object implementing Notifee interface
        :return: true if notifee registered successfully, false otherwise
        """
