from abc import ABC, abstractmethod
from typing import Any, List, Sequence

import multiaddr

from libp2p.network.network_interface import INetwork
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.typing import StreamHandlerFn, TProtocol


class IHost(ABC):
    @abstractmethod
    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """

    @abstractmethod
    def get_network(self) -> INetwork:
        """
        :return: network instance of host
        """

    # FIXME: Replace with correct return type
    @abstractmethod
    def get_mux(self) -> Any:
        """
        :return: mux instance of host
        """

    @abstractmethod
    def get_addrs(self) -> List[multiaddr.Multiaddr]:
        """
        :return: all the multiaddr addresses this host is listening too
        """

    @abstractmethod
    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> bool:
        """
        set stream handler for host
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        :return: true if successful
        """

    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    @abstractmethod
    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_ids: protocol ids that stream can run on
        :return: stream: new stream created
        """

    @abstractmethod
    async def connect(self, peer_info: PeerInfo) -> None:
        """
        connect ensures there is a connection between this host and the peer with
        given peer_info.peer_id. connect will absorb the addresses in peer_info into its internal
        peerstore. If there is not an active connection, connect will issue a
        dial, and block until a connection is open, or an error is
        returned.

        :param peer_info: peer_info of the host we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
