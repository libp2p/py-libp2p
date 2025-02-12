from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Sequence,
)
from typing import (
    Any,
    AsyncContextManager,
)

import multiaddr
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
    PublicKey,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.io.abc import (
    Closer,
    ReadWriteCloser,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.tools.async_service import (
    ServiceAPI,
)
from libp2p.transport.listener_interface import (
    IListener,
)

# raw_connection_interface


class IRawConnection(ReadWriteCloser):
    """A Raw Connection provides a Reader and a Writer."""

    is_initiator: bool


# secure_conn_interface
"""
Represents a secured connection object, which includes a connection and details about
the security involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class AbstractSecureConn(ABC):
    @abstractmethod
    def get_local_peer(self) -> ID:
        pass

    @abstractmethod
    def get_local_private_key(self) -> PrivateKey:
        pass

    @abstractmethod
    def get_remote_peer(self) -> ID:
        pass

    @abstractmethod
    def get_remote_public_key(self) -> PublicKey:
        pass


class ISecureConn(AbstractSecureConn, IRawConnection):
    pass


# stream_muxer abc.py


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    peer_id: ID
    event_started: trio.Event

    @abstractmethod
    def __init__(self, conn: ISecureConn, peer_id: ID) -> None:
        """
        Create a new muxed connection.

        :param conn: an instance of secured connection
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @property
    @abstractmethod
    def is_initiator(self) -> bool:
        """If this connection is the initiator."""

    @abstractmethod
    async def start(self) -> None:
        """Start the multiplexer."""

    @abstractmethod
    async def close(self) -> None:
        """Close connection."""

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """
        Check connection is fully closed.

        :return: true if successful
        """

    @abstractmethod
    async def open_stream(self) -> "IMuxedStream":
        """
        Create a new muxed_stream.

        :return: a new ``IMuxedStream`` stream
        """

    @abstractmethod
    async def accept_stream(self) -> "IMuxedStream":
        """Accept a muxed stream opened by the other end."""


class IMuxedStream(ReadWriteCloser):
    muxed_conn: IMuxedConn

    @abstractmethod
    async def reset(self) -> None:
        """Close both ends of the stream tells this remote side to hang up."""

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        Set deadline for muxed stream.

        :return: a new stream
        """


# net_stream_interface


class INetStream(ReadWriteCloser):
    muxed_conn: IMuxedConn

    @abstractmethod
    def get_protocol(self) -> TProtocol:
        """
        :return: protocol id that stream runs on
        """

    @abstractmethod
    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        """

    @abstractmethod
    async def reset(self) -> None:
        """Close both ends of the stream."""


# net_connection_interface
class INetConn(Closer):
    muxed_conn: IMuxedConn
    event_started: trio.Event

    @abstractmethod
    async def new_stream(self) -> INetStream:
        ...

    @abstractmethod
    def get_streams(self) -> tuple[INetStream, ...]:
        ...


# peermetadata_interface
class IPeerMetadata(ABC):
    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to look up
        :return: value at key for given peer
        :raise Exception: peer ID not found
        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to associate with peer
        :param val: value to associated with key
        :raise Exception: unsuccessful put
        """


# addrbook_interface


class IAddrBook(ABC):
    @abstractmethod
    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        Calls add_addrs(peer_id, [addr], ttl)

        :param peer_id: the peer to add address for
        :param addr: multiaddress of the peer
        :param ttl: time-to-live for the address (after this time, address is no longer valid)
        """  # noqa: E501

    @abstractmethod
    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        Adds addresses for a given peer all with the same time-to-live. If one
        of the addresses already exists for the peer and has a longer TTL, no
        operation should take place. If one of the addresses exists with a
        shorter TTL, extend the TTL to equal param ttl.

        :param peer_id: the peer to add address for
        :param addr: multiaddresses of the peer
        :param ttl: time-to-live for the address (after this time, address is no longer valid
        """  # noqa: E501

    @abstractmethod
    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer to get addresses of
        :return: all known (and valid) addresses for the given peer
        """

    @abstractmethod
    def clear_addrs(self, peer_id: ID) -> None:
        """
        Removes all previously stored addresses.

        :param peer_id: peer to remove addresses of
        """

    @abstractmethod
    def peers_with_addrs(self) -> list[ID]:
        """
        :return: all of the peer IDs stored with addresses
        """


# peerstore_interface


class IPeerStore(IAddrBook, IPeerMetadata):
    @abstractmethod
    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """

    @abstractmethod
    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """

    @abstractmethod
    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """

    @abstractmethod
    def peer_ids(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """

    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """

    @abstractmethod
    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """

    @abstractmethod
    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """

    @abstractmethod
    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs
        """

    @abstractmethod
    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """

    @abstractmethod
    def peers_with_addrs(self) -> list[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """

    @abstractmethod
    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID already has pubkey set
        """

    @abstractmethod
    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID already has privkey set
        """

    @abstractmethod
    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        :raise PeerStoreError: if peer ID already has pubkey or privkey set
        """


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


# notifee_interface


class INotifee(ABC):
    @abstractmethod
    async def opened_stream(self, network: "INetwork", stream: INetStream) -> None:
        """
        :param network: network the stream was opened on
        :param stream: stream that was opened
        """

    @abstractmethod
    async def closed_stream(self, network: "INetwork", stream: INetStream) -> None:
        """
        :param network: network the stream was closed on
        :param stream: stream that was closed
        """

    @abstractmethod
    async def connected(self, network: "INetwork", conn: INetConn) -> None:
        """
        :param network: network the connection was opened on
        :param conn: connection that was opened
        """

    @abstractmethod
    async def disconnected(self, network: "INetwork", conn: INetConn) -> None:
        """
        :param network: network the connection was closed on
        :param conn: connection that was closed
        """

    @abstractmethod
    async def listen(self, network: "INetwork", multiaddr: Multiaddr) -> None:
        """
        :param network: network the listener is listening on
        :param multiaddr: multiaddress listener is listening on
        """

    @abstractmethod
    async def listen_close(self, network: "INetwork", multiaddr: Multiaddr) -> None:
        """
        :param network: network the connection was opened on
        :param multiaddr: multiaddress listener is no longer listening on
        """


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


# peerdata_interface
class IPeerData(ABC):
    @abstractmethod
    def get_protocols(self) -> list[str]:
        """
        :return: all protocols associated with given peer
        """

    @abstractmethod
    def add_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to add
        """

    @abstractmethod
    def set_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to set
        """

    @abstractmethod
    def add_addrs(self, addrs: Sequence[Multiaddr]) -> None:
        """
        :param addrs: multiaddresses to add
        """

    @abstractmethod
    def get_addrs(self) -> list[Multiaddr]:
        """
        :return: all multiaddresses
        """

    @abstractmethod
    def clear_addrs(self) -> None:
        """Clear all addresses."""

    @abstractmethod
    def put_metadata(self, key: str, val: Any) -> None:
        """
        :param key: key in KV pair
        :param val: val to associate with key
        """

    @abstractmethod
    def get_metadata(self, key: str) -> IPeerMetadata:
        """
        :param key: key in KV pair
        :return: val for key
        :raise PeerDataError: key not found
        """

    @abstractmethod
    def add_pubkey(self, pubkey: PublicKey) -> None:
        """
        :param pubkey:
        """

    @abstractmethod
    def get_pubkey(self) -> PublicKey:
        """
        :return: public key of the peer
        :raise PeerDataError: if public key not found
        """

    @abstractmethod
    def add_privkey(self, privkey: PrivateKey) -> None:
        """
        :param privkey:
        """

    @abstractmethod
    def get_privkey(self) -> PrivateKey:
        """
        :return: private key of the peer
        :raise PeerDataError: if private key not found
        """
