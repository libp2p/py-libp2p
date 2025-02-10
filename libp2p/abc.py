# host_interface

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Sequence,
)
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
)

import multiaddr
from multiaddr import (
    Multiaddr,
)

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.network.connection.net_connection_interface import (
    INetConn,
)
from libp2p.network.stream.net_stream_interface import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore_interface import (
    IPeerStore,
)
from libp2p.tools.async_service import (
    ServiceAPI,
)
from libp2p.transport.listener_interface import (
    IListener,
)

if TYPE_CHECKING:
    from libp2p.network.notifee_interface import INotifee  # noqa: F401

# network_interface


class INetwork(ABC):
    peerstore: IPeerStore
    connections: dict[ID, INetConn]
    listeners: dict[str, IListener]

    @abstractmethod
    def get_peer_id(self) -> ID:
        """
        :return: the peer id
        """

    @abstractmethod
    async def dial_peer(self, peer_id: ID) -> INetConn:
        """
        dial_peer try to create a connection to peer_id.

        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when an error occurs
        :return: muxed connection
        """

    @abstractmethod
    async def new_stream(self, peer_id: ID) -> INetStream:
        """
        :param peer_id: peer_id of destination
        :param protocol_ids: available protocol ids to use for stream
        :return: net stream instance
        """

    @abstractmethod
    def set_stream_handler(self, stream_handler: StreamHandlerFn) -> None:
        """Set the stream handler for all incoming streams."""

    @abstractmethod
    async def listen(self, *multiaddrs: Sequence[Multiaddr]) -> bool:
        """
        :param multiaddrs: one or many multiaddrs to start listening on
        :return: True if at least one success
        """

    @abstractmethod
    def register_notifee(self, notifee: "INotifee") -> None:
        """
        :param notifee: object implementing Notifee interface
        :return: true if notifee registered successfully, false otherwise
        """

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def close_peer(self, peer_id: ID) -> None:
        pass


class INetworkService(INetwork, ServiceAPI):
    pass


# host_interface
class IHost(ABC):
    @abstractmethod
    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """

    @abstractmethod
    def get_public_key(self) -> PublicKey:
        """
        :return: the public key belonging to the peer
        """

    @abstractmethod
    def get_private_key(self) -> PrivateKey:
        """
        :return: the private key belonging to the peer
        """

    @abstractmethod
    def get_network(self) -> INetworkService:
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
    def get_addrs(self) -> list[multiaddr.Multiaddr]:
        """
        :return: all the multiaddr addresses this host is listening to
        """

    @abstractmethod
    def get_connected_peers(self) -> list[ID]:
        """
        :return: all the ids of peers this host is currently connected to
        """

    @abstractmethod
    def run(
        self, listen_addrs: Sequence[multiaddr.Multiaddr]
    ) -> AsyncContextManager[None]:
        """
        Run the host instance and listen to ``listen_addrs``.

        :param listen_addrs: a sequence of multiaddrs that we want to listen to
        """

    @abstractmethod
    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> None:
        """
        Set stream handler for host.

        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        """

    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    @abstractmethod
    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_ids: available protocol ids to use for stream
        :return: stream: new stream created
        """

    @abstractmethod
    async def connect(self, peer_info: PeerInfo) -> None:
        """
        Ensure there is a connection between this host and the peer
        with given peer_info.peer_id. connect will absorb the addresses in
        peer_info into its internal peerstore. If there is not an active
        connection, connect will issue a dial, and block until a connection is
        opened, or an error is returned.

        :param peer_info: peer_info of the peer we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """

    @abstractmethod
    async def disconnect(self, peer_id: ID) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
