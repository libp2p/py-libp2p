from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    AsyncIterable,
    Iterable,
    KeysView,
    Sequence,
)
from contextlib import AbstractAsyncContextManager
from types import (
    TracebackType,
)
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
)

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
    THandler,
    TProtocol,
    ValidatorFn,
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

if TYPE_CHECKING:
    from libp2p.pubsub.pubsub import (
        Pubsub,
    )

from libp2p.pubsub.pb import (
    rpc_pb2,
)
from libp2p.tools.async_service import (
    ServiceAPI,
)

# -------------------------- raw_connection interface.py --------------------------


class IRawConnection(ReadWriteCloser):
    """
    Interface for a raw connection.

    This interface provides a basic reader/writer connection abstraction.

    Attributes
    ----------
    is_initiator (bool):
        True if the local endpoint initiated
        the connection.

    """

    is_initiator: bool


# -------------------------- secure_conn interface.py --------------------------


"""
Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class AbstractSecureConn(ABC):
    """
    Abstract interface for secure connections.

    Represents a secured connection object, including details about the
    security involved in the connection.

    """

    @abstractmethod
    def get_local_peer(self) -> ID:
        """
        Retrieve the local peer's identifier.

        :return: The local peer ID.
        """

    @abstractmethod
    def get_local_private_key(self) -> PrivateKey:
        """
        Retrieve the local peer's private key.

        :return: The private key of the local peer.
        """

    @abstractmethod
    def get_remote_peer(self) -> ID:
        """
        Retrieve the remote peer's identifier.

        :return: The remote peer ID.
        """

    @abstractmethod
    def get_remote_public_key(self) -> PublicKey:
        """
        Retrieve the remote peer's public key.

        :return: The public key of the remote peer.
        """


class ISecureConn(AbstractSecureConn, IRawConnection):
    """
    Interface for a secure connection.

    Combines secure connection functionalities with raw I/O operations.

    """


# -------------------------- stream_muxer abc.py --------------------------


class IMuxedConn(ABC):
    """
    Interface for a multiplexed connection.

    References
    ----------
    https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go

    Attributes
    ----------
    peer_id (ID):
        The identifier of the connected peer.
    event_started (trio.Event):
        An event that signals when the multiplexer has started.

    """

    peer_id: ID
    event_started: trio.Event

    @abstractmethod
    def __init__(
        self,
        conn: ISecureConn,
        peer_id: ID,
    ) -> None:
        """
        Initialize a new multiplexed connection.

        :param conn: An instance of a secure connection used for new
            multiplexed streams.
        :param peer_id: The peer ID associated with the connection.
        """

    @property
    @abstractmethod
    def is_initiator(self) -> bool:
        """
        Determine if this connection is the initiator.

        :return: True if this connection initiated the connection,
            otherwise False.
        """

    @abstractmethod
    async def start(self) -> None:
        """
        Start the multiplexer.

        """

    @abstractmethod
    async def close(self) -> None:
        """
        Close the multiplexed connection.

        """

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """
        Check if the connection is fully closed.

        :return: True if the connection is closed, otherwise False.
        """

    @abstractmethod
    async def open_stream(self) -> "IMuxedStream":
        """
        Create and open a new multiplexed stream.

        :return: A new instance of IMuxedStream.
        """

    @abstractmethod
    async def accept_stream(self) -> "IMuxedStream":
        """
        Accept a new multiplexed stream initiated by the remote peer.

        :return: A new instance of IMuxedStream.
        """


class IMuxedStream(ReadWriteCloser, AsyncContextManager["IMuxedStream"]):
    """
    Interface for a multiplexed stream.

    Represents a stream multiplexed over a single connection.

    Attributes
    ----------
    muxed_conn (IMuxedConn):
        The underlying multiplexed connection.

    """

    muxed_conn: IMuxedConn

    @abstractmethod
    async def reset(self) -> None:
        """
        Reset the stream.

        This method closes both ends of the stream, instructing the remote
        side to hang up.
        """

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        Set a deadline for the stream.

        :param ttl: Time-to-live for the stream in seconds.
        :return: True if the deadline was set successfully,
            otherwise False.
        """

    @abstractmethod
    async def __aenter__(self) -> "IMuxedStream":
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager and close the stream."""
        await self.close()


# -------------------------- net_stream interface.py --------------------------


class INetStream(ReadWriteCloser):
    """
    Interface for a network stream.

    Represents a network stream operating over a multiplexed connection.

    Attributes
    ----------
    muxed_conn (IMuxedConn):
        The multiplexed connection that this stream belongs to.

    """

    muxed_conn: IMuxedConn

    @abstractmethod
    def get_protocol(self) -> TProtocol | None:
        """
        Retrieve the protocol identifier for the stream.

        :return: The protocol ID associated with the stream.
        """

    @abstractmethod
    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        Set the protocol identifier for the stream.

        :param protocol_id: The protocol ID to assign to the stream.
        """

    @abstractmethod
    async def reset(self) -> None:
        """
        Reset the network stream.

        This method closes both ends of the stream.
        """


# -------------------------- net_connection interface.py --------------------------


class INetConn(Closer):
    """
    Interface for a network connection.

    Defines a network connection capable of creating and managing streams.

    Attributes
    ----------
    muxed_conn (IMuxedConn):
        The underlying multiplexed connection.
    event_started (trio.Event):
        Event signaling when the connection has started.

    """

    muxed_conn: IMuxedConn
    event_started: trio.Event

    @abstractmethod
    async def new_stream(self) -> INetStream:
        """
        Create a new network stream over the connection.

        :return: A new instance of INetStream.
        """

    @abstractmethod
    def get_streams(self) -> tuple[INetStream, ...]:
        """
        Retrieve all active streams associated with this connection.

        :return: A tuple containing instances of INetStream.
        """


# -------------------------- peermetadata interface.py --------------------------


class IPeerMetadata(ABC):
    """
    Interface for managing peer metadata.

    Provides methods for storing and retrieving metadata associated with peers.
    """

    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        Retrieve metadata for a specified peer.

        :param peer_id: The ID of the peer.
        :param key: The key for the metadata to retrieve.
        :return: The metadata value associated with the key.
        :raises Exception: If the peer ID is not found.
        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        Store metadata for a specified peer.

        :param peer_id: The ID of the peer.
        :param key: The key for the metadata.
        :param val: The value to store.
        :raises Exception: If the operation is unsuccessful.
        """

    @abstractmethod
    def clear_metadata(self, peer_id: ID) -> None:
        """
        Remove all stored metadata for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose metadata are to be removed.

        """


# -------------------------- addrbook interface.py --------------------------


class IAddrBook(ABC):
    """
    Interface for an address book.

    Provides methods for managing peer addresses.
    """

    @abstractmethod
    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        Add a single address for a given peer.

        This method calls ``add_addrs(peer_id, [addr], ttl)``.

        Parameters
        ----------
        peer_id : ID
            The peer identifier for which to add the address.
        addr : Multiaddr
            The multiaddress of the peer.
        ttl : int
            The time-to-live for the address, after which it is no longer valid.

        """

    @abstractmethod
    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        Add multiple addresses for a given peer, all with the same TTL.

        If an address already exists with a longer TTL, no action should be taken.
        If an address exists with a shorter TTL, its TTL should be extended to match
        the provided TTL.

        Parameters
        ----------
        peer_id : ID
            The peer identifier for which to add addresses.
        addrs : Sequence[Multiaddr]
            A sequence of multiaddresses to add.
        ttl : int
            The time-to-live for the addresses, after which they become invalid.

        """

    @abstractmethod
    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        Retrieve all known and valid addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose addresses are requested.

        Returns
        -------
        list[Multiaddr]
            A list of valid multiaddresses for the given peer.

        """

    @abstractmethod
    def clear_addrs(self, peer_id: ID) -> None:
        """
        Remove all stored addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose addresses are to be removed.

        """

    @abstractmethod
    def peers_with_addrs(self) -> list[ID]:
        """
        Retrieve all peer identifiers that have stored addresses.

        Returns
        -------
        list[ID]
            A list of peer IDs with stored addresses.

        """


# -------------------------- keybook interface.py --------------------------


class IKeyBook(ABC):
    """
    Interface for an key book.

    Provides methods for managing cryptographic keys.
    """

    @abstractmethod
    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        Returns the public key of the specified peer

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose public key is to be returned.

        """

    @abstractmethod
    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        Returns the private key of the specified peer

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose private key is to be returned.

        """

    @abstractmethod
    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        Adds the public key for a specified peer

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose public key is to be added
        pubkey: PublicKey
            The public key of the peer

        """

    @abstractmethod
    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        Adds the private key for a specified peer

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose private key is to be added
        privkey: PrivateKey
            The private key of the peer

        """

    @abstractmethod
    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        Adds the key pair for a specified peer

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose key pair is to be added
        key_pair: KeyPair
            The key pair of the peer

        """

    @abstractmethod
    def peer_with_keys(self) -> list[ID]:
        """Returns all the peer IDs stored in the AddrBook"""

    @abstractmethod
    def clear_keydata(self, peer_id: ID) -> None:
        """
        Remove all stored keydata for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose keys are to be removed.

        """


# -------------------------- metrics interface.py --------------------------


class IMetrics(ABC):
    """
    Interface for metrics of peer interaction.

    Provides methods for managing the metrics.
    """

    @abstractmethod
    def record_latency(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new round-trip time (RTT) latency value for the specified peer
        using Exponentially Weighted Moving Average (EWMA).

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer for which latency is being recorded.

        RTT : float
            The round-trip time latency value to record.

        """

    @abstractmethod
    def latency_EWMA(self, peer_id: ID) -> float:
        """
        Returns the current latency value for the specified peer using
        Exponentially Weighted Moving Average (EWMA).

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose latency EWMA is to be returned.

        """

    @abstractmethod
    def clear_metrics(self, peer_id: ID) -> None:
        """
        Clears the stored latency metrics for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose latency metrics are to be cleared.

        """


# -------------------------- protobook interface.py --------------------------


class IProtoBook(ABC):
    """
    Interface for a protocol book.

    Provides methods for managing the list of supported protocols.
    """

    @abstractmethod
    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        Returns the list of protocols associated with the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose supported protocols are to be returned.

        """

    @abstractmethod
    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Adds the given protocols to the specified peer's protocol list.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to which protocols will be added.

        protocols : Sequence[str]
            A sequence of protocol strings to add.

        """

    @abstractmethod
    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Replaces the existing protocols of the specified peer with the given list.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose protocols are to be set.

        protocols : Sequence[str]
            A sequence of protocol strings to assign.

        """

    @abstractmethod
    def remove_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Removes the specified protocols from the peer's protocol list.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer from which protocols will be removed.

        protocols : Sequence[str]
            A sequence of protocol strings to remove.

        """

    @abstractmethod
    def supports_protocols(self, peer_id: ID, protocols: Sequence[str]) -> list[str]:
        """
        Returns the list of protocols from the input sequence that the peer supports.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to check for protocol support.

        protocols : Sequence[str]
            A sequence of protocol strings to check against the peer's
            supported protocols.

        """

    @abstractmethod
    def first_supported_protocol(self, peer_id: ID, protocols: Sequence[str]) -> str:
        """
        Returns the first protocol from the input list that the peer supports.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to check for supported protocols.

        protocols : Sequence[str]
            A sequence of protocol strings to check.

        Returns
        -------
        str
            The first matching protocol string, or an empty string
            if none are supported.

        """

    @abstractmethod
    def clear_protocol_data(self, peer_id: ID) -> None:
        """
        Clears all protocol data associated with the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose protocol data will be cleared.

        """


# -------------------------- peerstore interface.py --------------------------


class IPeerStore(IPeerMetadata, IAddrBook, IKeyBook, IMetrics, IProtoBook):
    """
    Interface for a peer store.

    Provides methods for managing peer information including address
    management, protocol handling, and key storage.
    """

    # -------METADATA---------
    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        Retrieve the value associated with a key for a specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        key : str
            The key to look up.

        Returns
        -------
        Any
            The value corresponding to the specified key.

        Raises
        ------
        PeerStoreError
            If the peer ID or value is not found.

        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        Store a key-value pair for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        key : str
            The key for the data.
        val : Any
            The value to store.

        """

    @abstractmethod
    def clear_metadata(self, peer_id: ID) -> None:
        """
        Clears the stored latency metrics for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose latency metrics are to be cleared.

        """

    # --------ADDR-BOOK---------
    @abstractmethod
    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        Add an address for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        addr : Multiaddr
            The multiaddress to add.
        ttl : int
            The time-to-live for the record.

        """

    @abstractmethod
    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        Add multiple addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        addrs : Sequence[Multiaddr]
            A sequence of multiaddresses to add.
        ttl : int
            The time-to-live for the record.

        """

    @abstractmethod
    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        Retrieve the addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        list[Multiaddr]
            A list of multiaddresses.

        """

    @abstractmethod
    def clear_addrs(self, peer_id: ID) -> None:
        """
        Clear all addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        """

    @abstractmethod
    def peers_with_addrs(self) -> list[ID]:
        """
        Retrieve all peer identifiers with stored addresses.

        Returns
        -------
        list[ID]
            A list of peer IDs.

        """

    # --------KEY-BOOK----------
    @abstractmethod
    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        Retrieve the public key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        PublicKey
            The public key of the peer.

        Raises
        ------
        PeerStoreError
            If the peer ID is not found.

        """

    @abstractmethod
    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        Retrieve the private key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        PrivateKey
            The private key of the peer.

        Raises
        ------
        PeerStoreError
            If the peer ID is not found.

        """

    @abstractmethod
    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        Add a public key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        pubkey : PublicKey
            The public key to add.

        Raises
        ------
        PeerStoreError
            If the peer already has a public key set.

        """

    @abstractmethod
    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        Add a private key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        privkey : PrivateKey
            The private key to add.

        Raises
        ------
        PeerStoreError
            If the peer already has a private key set.

        """

    @abstractmethod
    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        Add a key pair for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        key_pair : KeyPair
            The key pair to add.

        Raises
        ------
        PeerStoreError
            If the peer already has a public or private key set.

        """

    @abstractmethod
    def peer_with_keys(self) -> list[ID]:
        """Returns all the peer IDs stored in the AddrBook"""

    @abstractmethod
    def clear_keydata(self, peer_id: ID) -> None:
        """
        Remove all stored keydata for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer identifier whose keys are to be removed.

        """

    # -------METRICS---------
    @abstractmethod
    def record_latency(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new round-trip time (RTT) latency value for the specified peer
        using Exponentially Weighted Moving Average (EWMA).

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer for which latency is being recorded.

        RTT : float
            The round-trip time latency value to record.

        """

    @abstractmethod
    def latency_EWMA(self, peer_id: ID) -> float:
        """
        Returns the current latency value for the specified peer using
        Exponentially Weighted Moving Average (EWMA).

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose latency EWMA is to be returned.

        """

    @abstractmethod
    def clear_metrics(self, peer_id: ID) -> None:
        """
        Clears the stored latency metrics for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose latency metrics are to be cleared.

        """

    # --------PROTO-BOOK----------
    @abstractmethod
    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        Retrieve the protocols associated with the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        list[str]
            A list of protocol identifiers.

        Raises
        ------
        PeerStoreError
            If the peer ID is not found.

        """

    @abstractmethod
    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Add additional protocols for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to add.

        """

    @abstractmethod
    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Set the protocols for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to set.

        """

    @abstractmethod
    def remove_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Removes the specified protocols from the peer's protocol list.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer from which protocols will be removed.

        protocols : Sequence[str]
            A sequence of protocol strings to remove.

        """

    @abstractmethod
    def supports_protocols(self, peer_id: ID, protocols: Sequence[str]) -> list[str]:
        """
        Returns the list of protocols from the input sequence that the peer supports.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to check for protocol support.

        protocols : Sequence[str]
            A sequence of protocol strings to check against the peer's
            supported protocols.

        """

    @abstractmethod
    def first_supported_protocol(self, peer_id: ID, protocols: Sequence[str]) -> str:
        """
        Returns the first protocol from the input list that the peer supports.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to check for supported protocols.

        protocols : Sequence[str]
            A sequence of protocol strings to check.

        Returns
        -------
        str
            The first matching protocol string, or an empty string
            if none are supported.

        """

    @abstractmethod
    def clear_protocol_data(self, peer_id: ID) -> None:
        """
        Clears all protocol data associated with the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose protocol data will be cleared.

        """

    # --------PEER-STORE--------
    @abstractmethod
    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        Retrieve the peer information for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        PeerInfo
            The peer information object for the given peer.

        """

    @abstractmethod
    def peer_ids(self) -> list[ID]:
        """
        Retrieve all peer identifiers stored in the peer store.

        Returns
        -------
        list[ID]
            A list of all peer IDs in the store.

        """

    @abstractmethod
    def clear_peerdata(self, peer_id: ID) -> None:
        """clear_peerdata"""


# -------------------------- listener interface.py --------------------------


class IListener(ABC):
    """
    Interface for a network listener.

    Provides methods for starting a listener, retrieving its addresses,
    and closing it.
    """

    @abstractmethod
    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening on the specified multiaddress.

        Parameters
        ----------
        maddr : Multiaddr
            The multiaddress on which to listen.
        nursery : trio.Nursery
            The nursery for spawning listening tasks.

        Returns
        -------
        bool
            True if the listener started successfully, otherwise False.

        """

    @abstractmethod
    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Retrieve the list of addresses on which the listener is active.

        Returns
        -------
        tuple[Multiaddr, ...]
            A tuple of multiaddresses.

        """

    @abstractmethod
    async def close(self) -> None:
        """
        Close the listener.

        """
        ...


# -------------------------- network interface.py --------------------------


class INetwork(ABC):
    """
    Interface for the network.

    Provides methods for managing connections, streams, and listeners.

    Attributes
    ----------
    peerstore : IPeerStore
        The peer store for managing peer information.
    connections : dict[ID, INetConn]
        A mapping of peer IDs to network connections.
    listeners : dict[str, IListener]
        A mapping of listener identifiers to listener instances.

    """

    peerstore: IPeerStore
    connections: dict[ID, INetConn]
    listeners: dict[str, IListener]

    @abstractmethod
    def get_peer_id(self) -> ID:
        """
        Retrieve the peer identifier for this network.

        Returns
        -------
        ID
            The identifier of this peer.

        """

    @abstractmethod
    async def dial_peer(self, peer_id: ID) -> INetConn:
        """
        Create a connection to the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to dial.

        Returns
        -------
        INetConn
            The network connection instance to the specified peer.

        Raises
        ------
        SwarmException
            If an error occurs during dialing.

        """

    @abstractmethod
    async def new_stream(self, peer_id: ID) -> INetStream:
        """
        Create a new network stream to the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the destination peer.

        Returns
        -------
        INetStream
            The newly created network stream.

        """

    @abstractmethod
    def set_stream_handler(self, stream_handler: StreamHandlerFn) -> None:
        """
        Set the stream handler for incoming streams.

        Parameters
        ----------
        stream_handler : StreamHandlerFn
            The handler function to process incoming streams.

        """

    @abstractmethod
    async def listen(self, *multiaddrs: Multiaddr) -> bool:
        """
        Start listening on one or more multiaddresses.

        Parameters
        ----------
        multiaddrs : Sequence[Multiaddr]
            One or more multiaddresses on which to start listening.

        Returns
        -------
        bool
            True if at least one listener started successfully, otherwise False.

        """

    @abstractmethod
    def register_notifee(self, notifee: "INotifee") -> None:
        """
        Register a notifee instance to receive network events.

        Parameters
        ----------
        notifee : INotifee
            An object implementing the INotifee interface.

        """

    @abstractmethod
    async def close(self) -> None:
        """
        Close the network and all associated connections and listeners.
        """

    @abstractmethod
    async def close_peer(self, peer_id: ID) -> None:
        """
        Close the connection to the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose connection should be closed.

        """


class INetworkService(INetwork, ServiceAPI):
    pass


# -------------------------- notifee interface.py --------------------------


class INotifee(ABC):
    """
    Interface for a network service.

    Extends the INetwork interface with additional service management
    capabilities.

    """

    @abstractmethod
    async def opened_stream(self, network: "INetwork", stream: INetStream) -> None:
        """
        Called when a new stream is opened.

        Parameters
        ----------
        network : INetwork
            The network instance on which the stream was opened.
        stream : INetStream
            The stream that was opened.

        """

    @abstractmethod
    async def closed_stream(self, network: "INetwork", stream: INetStream) -> None:
        """
        Called when a stream is closed.

        Parameters
        ----------
        network : INetwork
            The network instance on which the stream was closed.
        stream : INetStream
            The stream that was closed.

        """

    @abstractmethod
    async def connected(self, network: "INetwork", conn: INetConn) -> None:
        """
        Called when a new connection is established.

        Parameters
        ----------
        network : INetwork
            The network instance where the connection was established.
        conn : INetConn
            The connection that was opened.

        """

    @abstractmethod
    async def disconnected(self, network: "INetwork", conn: INetConn) -> None:
        """
        Called when a connection is closed.

        Parameters
        ----------
        network : INetwork
            The network instance where the connection was closed.
        conn : INetConn
            The connection that was closed.

        """

    @abstractmethod
    async def listen(self, network: "INetwork", multiaddr: Multiaddr) -> None:
        """
        Called when a listener starts on a multiaddress.

        Parameters
        ----------
        network : INetwork
            The network instance where the listener is active.
        multiaddr : Multiaddr
            The multiaddress on which the listener is listening.

        """

    @abstractmethod
    async def listen_close(self, network: "INetwork", multiaddr: Multiaddr) -> None:
        """
        Called when a listener stops listening on a multiaddress.

        Parameters
        ----------
        network : INetwork
            The network instance where the listener was active.
        multiaddr : Multiaddr
            The multiaddress that is no longer being listened on.

        """


# -------------------------- host interface.py --------------------------


class IHost(ABC):
    """
    Interface for the host.

    Provides methods for retrieving host information, managing
    connections and streams, and running the host.

    """

    @abstractmethod
    def get_id(self) -> ID:
        """
        Retrieve the host's peer identifier.

        Returns
        -------
        ID
            The host's peer identifier.

        """

    @abstractmethod
    def get_public_key(self) -> PublicKey:
        """
        Retrieve the public key of the host.

        Returns
        -------
        PublicKey
            The public key belonging to the host.

        """

    @abstractmethod
    def get_private_key(self) -> PrivateKey:
        """
        Retrieve the private key of the host.

        Returns
        -------
        PrivateKey
            The private key belonging to the host.

        """

    @abstractmethod
    def get_network(self) -> INetworkService:
        """
        Retrieve the network service instance associated with the host.

        Returns
        -------
        INetworkService
            The network instance of the host.

        """

    # FIXME: Replace with correct return type
    @abstractmethod
    def get_mux(self) -> Any:
        """
        Retrieve the muxer instance for the host.

        Returns
        -------
        Any
            The muxer instance of the host.

        """

    @abstractmethod
    def get_addrs(self) -> list[Multiaddr]:
        """
        Retrieve all multiaddresses on which the host is listening.

        Returns
        -------
        list[Multiaddr]
            A list of multiaddresses.

        """

    @abstractmethod
    def get_peerstore(self) -> IPeerStore:
        """
        :return: the peerstore of the host
        """

    @abstractmethod
    def get_connected_peers(self) -> list[ID]:
        """
        Retrieve the identifiers of peers currently connected to the host.

        Returns
        -------
        list[ID]
            A list of peer identifiers.

        """

    @abstractmethod
    def get_live_peers(self) -> list[ID]:
        """
        :return: List of peer IDs that have active connections
        """

    @abstractmethod
    def run(
        self, listen_addrs: Sequence[Multiaddr]
    ) -> AbstractAsyncContextManager[None]:
        """
        Run the host and start listening on the specified multiaddresses.

        Parameters
        ----------
        listen_addrs : Sequence[Multiaddr]
            A sequence of multiaddresses on which the host should listen.

        """

    @abstractmethod
    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> None:
        """
        Set the stream handler for the specified protocol.

        Parameters
        ----------
        protocol_id : TProtocol
            The protocol identifier used on the stream.
        stream_handler : StreamHandlerFn
            The stream handler function to be set.

        """

    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    @abstractmethod
    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        Create a new stream to the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to connect.
        protocol_ids : Sequence[TProtocol]
            A sequence of available protocol identifiers to use for the stream.

        Returns
        -------
        INetStream
            The newly created network stream.

        """

    @abstractmethod
    async def connect(self, peer_info: PeerInfo) -> None:
        """
        Establish a connection to the specified peer.

        This method ensures there is a connection between the host and the peer
        represented by the provided peer information. It also absorbs the addresses
        from ``peer_info`` into the host's internal peerstore. If no active connection
        exists, the host will dial the peer and block until a connection is established
        or an error occurs.

        Parameters
        ----------
        peer_info : PeerInfo
            The peer information of the peer to connect to.

        """

    @abstractmethod
    async def disconnect(self, peer_id: ID) -> None:
        """
        Disconnect from the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to disconnect from.

        """

    @abstractmethod
    async def close(self) -> None:
        """
        Close the host and all underlying connections and services.

        """


# -------------------------- peerdata interface.py --------------------------


class IPeerData(ABC):
    """
    Interface for managing peer data.

    Provides methods for handling protocols, addresses, metadata, and keys
    associated with a peer.
    """

    @abstractmethod
    def get_protocols(self) -> list[str]:
        """
        Retrieve all protocols associated with the peer.

        Returns
        -------
        list[str]
            A list of protocols associated with the peer.

        """

    @abstractmethod
    def add_protocols(self, protocols: Sequence[str]) -> None:
        """
        Add one or more protocols to the peer's data.

        Parameters
        ----------
        protocols : Sequence[str]
            A sequence of protocols to add.

        """

    @abstractmethod
    def set_protocols(self, protocols: Sequence[str]) -> None:
        """
        Set the protocols for the peer.

        Parameters
        ----------
        protocols : Sequence[str]
            A sequence of protocols to set.

        """

    @abstractmethod
    def remove_protocols(self, protocols: Sequence[str]) -> None:
        """
        Removes the specified protocols from this peer's list of supported protocols.

        Parameters
        ----------
        protocols : Sequence[str]
            A sequence of protocol strings to be removed.

        """

    @abstractmethod
    def supports_protocols(self, protocols: Sequence[str]) -> list[str]:
        """
        Returns the list of protocols from the input sequence that are supported
        by this peer.

        Parameters
        ----------
        protocols : Sequence[str]
            A sequence of protocol strings to check against this peer's supported
            protocols.

        Returns
        -------
        list[str]
            A list of protocol strings that are supported.

        """

    @abstractmethod
    def first_supported_protocol(self, protocols: Sequence[str]) -> str:
        """
        Returns the first protocol from the input list that this peer supports.

        Parameters
        ----------
        protocols : Sequence[str]
            A sequence of protocol strings to check for support.

        Returns
        -------
        str
            The first matching protocol, or an empty string if none are supported.

        """

    @abstractmethod
    def clear_protocol_data(self) -> None:
        """
        Clears all protocol data associated with this peer.
        """

    @abstractmethod
    def add_addrs(self, addrs: Sequence[Multiaddr]) -> None:
        """
        Add multiple multiaddresses to the peer's data.

        Parameters
        ----------
        addrs : Sequence[Multiaddr]
            A sequence of multiaddresses to add.
        ttl: inr
            Time to live for the peer record

        """

    @abstractmethod
    def get_addrs(self) -> list[Multiaddr]:
        """
        Retrieve all multiaddresses associated with the peer.

        Returns
        -------
        list[Multiaddr]
            A list of multiaddresses.

        """

    @abstractmethod
    def clear_addrs(self) -> None:
        """
        Clear all addresses associated with the peer.

        """

    @abstractmethod
    def put_metadata(self, key: str, val: Any) -> None:
        """
        Store a metadata key-value pair for the peer.

        Parameters
        ----------
        key : str
            The metadata key.
        val : Any
            The value to associate with the key.

        """

    @abstractmethod
    def get_metadata(self, key: str) -> IPeerMetadata:
        """
        Retrieve metadata for a given key.

        Parameters
        ----------
        key : str
            The metadata key.

        Returns
        -------
        IPeerMetadata
            The metadata value for the given key.

        Raises
        ------
        PeerDataError
            If the key is not found.

        """

    @abstractmethod
    def clear_metadata(self) -> None:
        """
        Clears all metadata entries associated with this peer.
        """

    @abstractmethod
    def add_pubkey(self, pubkey: PublicKey) -> None:
        """
        Add a public key to the peer's data.

        Parameters
        ----------
        pubkey : PublicKey
            The public key to add.

        """

    @abstractmethod
    def get_pubkey(self) -> PublicKey:
        """
        Retrieve the public key for the peer.

        Returns
        -------
        PublicKey
            The public key of the peer.

        Raises
        ------
        PeerDataError
            If the public key is not found.

        """

    @abstractmethod
    def add_privkey(self, privkey: PrivateKey) -> None:
        """
        Add a private key to the peer's data.

        Parameters
        ----------
        privkey : PrivateKey
            The private key to add.

        """

    @abstractmethod
    def get_privkey(self) -> PrivateKey:
        """
        Retrieve the private key for the peer.

        Returns
        -------
        PrivateKey
            The private key of the peer.

        Raises
        ------
        PeerDataError
            If the private key is not found.

        """

    @abstractmethod
    def clear_keydata(self) -> None:
        """
        Clears all cryptographic key data associated with this peer,
        including both public and private keys.
        """

    @abstractmethod
    def record_latency(self, new_latency: float) -> None:
        """
        Records a new latency measurement using
        Exponentially Weighted Moving Average (EWMA).

        Parameters
        ----------
        new_latency : float
            The new round-trip time (RTT) latency value to incorporate
            into the EWMA calculation.

        """

    @abstractmethod
    def latency_EWMA(self) -> float:
        """
        Returns the current EWMA value of the recorded latency.

        Returns
        -------
        float
            The current latency estimate based on EWMA.

        """

    @abstractmethod
    def clear_metrics(self) -> None:
        """
        Clears all latency-related metrics and resets the internal state.
        """

    @abstractmethod
    def update_last_identified(self) -> None:
        """
        Updates timestamp to current time.
        """

    @abstractmethod
    def get_last_identified(self) -> int:
        """
        Fetch the last identified timestamp

        Returns
        -------
        last_identified_timestamp
            The lastIdentified time of peer.

        """

    @abstractmethod
    def get_ttl(self) -> int:
        """
        Get ttl value for the peer for validity check

        Returns
        -------
        int
            The ttl of the peer.

        """

    @abstractmethod
    def set_ttl(self, ttl: int) -> None:
        """
        Set ttl value for the peer for validity check

        Parameters
        ----------
        ttl : int
            The ttl for the peer.

        """

    @abstractmethod
    def is_expired(self) -> bool:
        """
        Check if the peer is expired based on last_identified and ttl

        Returns
        -------
        bool
            True, if last_identified + ttl > current_time

        """


# ------------------ multiselect_communicator interface.py ------------------


class IMultiselectCommunicator(ABC):
    """
    Communicator helper for multiselect.

    Ensures that both the client and multistream module follow the same
    multistream protocol.
    """

    @abstractmethod
    async def write(self, msg_str: str) -> None:
        """
        Write a message to the stream.

        Parameters
        ----------
        msg_str : str
            The message string to write.

        """

    @abstractmethod
    async def read(self) -> str:
        """
        Read a message from the stream until EOF.

        Returns
        -------
        str
            The message read from the stream.

        """


# -------------------------- multiselect_client interface.py --------------------------


class IMultiselectClient(ABC):
    """
    Client for multiselect negotiation.

    Communicates with the receiver's multiselect module to select a protocol
    for communication.
    """

    @abstractmethod
    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Ensure that the client and multiselect module are using the same
        multiselect protocol.

        Parameters
        ----------
        communicator : IMultiselectCommunicator
            The communicator used for negotiating the multiselect protocol.

        Raises
        ------
        Exception
            If there is a multiselect protocol ID mismatch.

        """

    @abstractmethod
    async def select_one_of(
        self, protocols: Sequence[TProtocol], communicator: IMultiselectCommunicator
    ) -> TProtocol:
        """
        Select one protocol from a sequence by communicating with the multiselect
        module.

        For each protocol in the provided sequence, the client sends a selection
        message and expects the multiselect module to confirm the protocol. The
        first confirmed protocol is returned.

        Parameters
        ----------
        protocols : Sequence[TProtocol]
            The protocols to attempt selection.
        communicator : IMultiselectCommunicator
            The communicator used for negotiating the protocol.

        Returns
        -------
        TProtocol
            The protocol selected by the multiselect module.

        """

    @abstractmethod
    async def try_select(
        self, communicator: IMultiselectCommunicator, protocol: TProtocol
    ) -> TProtocol:
        """
        Attempt to select the given protocol.

        Parameters
        ----------
        communicator : IMultiselectCommunicator
            The communicator used to interact with the counterparty.
        protocol : TProtocol
            The protocol to select.

        Returns
        -------
        TProtocol
            The protocol if successfully selected.

        Raises
        ------
        Exception
            If protocol selection fails.

        """


# -------------------------- multiselect_muxer interface.py --------------------------


class IMultiselectMuxer(ABC):
    """
    Multiselect module for protocol negotiation.

    Responsible for responding to a multiselect client by selecting a protocol
    and its corresponding handler for communication.
    """

    handlers: dict[TProtocol | None, StreamHandlerFn | None]

    @abstractmethod
    def add_handler(self, protocol: TProtocol, handler: StreamHandlerFn) -> None:
        """
        Store a handler for the specified protocol.

        Parameters
        ----------
        protocol : TProtocol
            The protocol name.
        handler : StreamHandlerFn
            The handler function associated with the protocol.

        """

    def get_protocols(self) -> tuple[TProtocol | None, ...]:
        """
        Retrieve the protocols for which handlers have been registered.

        Returns
        -------
        tuple[TProtocol, ...]
            A tuple of registered protocol names.

        """
        return tuple(self.handlers.keys())

    @abstractmethod
    async def negotiate(
        self, communicator: IMultiselectCommunicator
    ) -> tuple[TProtocol | None, StreamHandlerFn | None]:
        """
        Negotiate a protocol selection with a multiselect client.

        Parameters
        ----------
        communicator : IMultiselectCommunicator
            The communicator used to negotiate the protocol.

        Returns
        -------
        tuple[TProtocol, StreamHandlerFn]
            A tuple containing the selected protocol and its handler.

        Raises
        ------
        Exception
            If negotiation fails.

        """


# -------------------------- routing interface.py --------------------------


class IContentRouting(ABC):
    """
    Interface for content routing.

    Provides methods to advertise and search for content providers.
    """

    @abstractmethod
    def provide(self, cid: bytes, announce: bool = True) -> None:
        """
        Advertise that the host can provide content identified by the given CID.

        If ``announce`` is True, the content is announced; otherwise, it is only
        recorded locally.

        Parameters
        ----------
        cid : bytes
            The content identifier.
        announce : bool, optional
            Whether to announce the provided content (default is True).

        """

    @abstractmethod
    def find_provider_iter(self, cid: bytes, count: int) -> Iterable[PeerInfo]:
        """
        Search for peers that can provide the content identified by the given CID.

        Parameters
        ----------
        cid : bytes
            The content identifier.
        count : int
            The maximum number of providers to return.

        Returns
        -------
        Iterable[PeerInfo]
            An iterator of PeerInfo objects for peers that provide the content.

        """


class IPeerRouting(ABC):
    """
    Interface for peer routing.

    Provides methods to search for a specific peer.
    """

    @abstractmethod
    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        """
        Search for a peer with the specified peer ID.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to search for.

        Returns
        -------
        PeerInfo
            The peer information containing relevant addresses.

        """


# -------------------------- security_transport interface.py --------------------------


class ISecureTransport(ABC):
    """
    Interface for a security transport.

    Used to secure connections by performing handshakes and negotiating secure
    channels between peers.

    References
    ----------
    https://github.com/libp2p/go-conn-security/blob/master/interface.go

    """

    @abstractmethod
    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure an inbound connection (when we are not the initiator).

        This method secures the connection by either performing local operations
        or communicating with the opposing node.

        Parameters
        ----------
        conn : IRawConnection
            The raw connection to secure.

        Returns
        -------
        ISecureConn
            The secured connection instance.

        """

    @abstractmethod
    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure an outbound connection (when we are the initiator).

        This method secures the connection by either performing local operations
        or communicating with the opposing node.

        Parameters
        ----------
        conn : IRawConnection
            The raw connection to secure.
        peer_id : ID
            The identifier of the remote peer.

        Returns
        -------
        ISecureConn
            The secured connection instance.

        """


# -------------------------- transport interface.py --------------------------


class ITransport(ABC):
    """
    Interface for a transport.

    Provides methods for dialing peers and creating listeners on a transport.

    """

    @abstractmethod
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        Dial a peer on the specified multiaddress.

        Parameters
        ----------
        maddr : Multiaddr
            The multiaddress of the peer to dial.

        Returns
        -------
        IRawConnection
            The raw connection established to the peer.

        """

    @abstractmethod
    def create_listener(self, handler_function: THandler) -> IListener:
        """
        Create a listener on the transport.

        Parameters
        ----------
        handler_function : THandler
            A function that is called when a new connection is received.
            The function should accept a connection (that implements the
            connection interface) as its argument.

        Returns
        -------
        IListener
            A listener instance.

        """


# -------------------------- pubsub abc.py --------------------------


class ISubscriptionAPI(
    AsyncContextManager["ISubscriptionAPI"], AsyncIterable[rpc_pb2.Message]
):
    """
    Interface for a subscription in pubsub.

    Combines asynchronous context management and iteration over messages.

    """

    @abstractmethod
    async def unsubscribe(self) -> None:
        """
        Unsubscribe from the current topic.

        """
        ...

    @abstractmethod
    async def get(self) -> rpc_pb2.Message:
        """
        Retrieve the next message from the subscription.

        Returns
        -------
        rpc_pb2.Message
            The next pubsub message.

        """
        ...


class IPubsubRouter(ABC):
    """
    Interface for a pubsub router.

    Provides methods to manage protocol support, peer attachments,
    and message handling for pubsub.

    """

    mesh: dict[str, set[ID]]
    fanout: dict[str, set[ID]]
    peer_protocol: dict[ID, TProtocol]
    degree: int

    @abstractmethod
    def get_protocols(self) -> list[TProtocol]:
        """
        Retrieve the list of protocols supported by the router.

        Returns
        -------
        list[TProtocol]
            A list of supported protocol identifiers.

        """

    @abstractmethod
    def attach(self, pubsub: "Pubsub") -> None:
        """
        Attach the router to a newly initialized PubSub instance.

        Parameters
        ----------
        pubsub : Pubsub
            The PubSub instance to attach to.

        """

    @abstractmethod
    def add_peer(self, peer_id: ID, protocol_id: TProtocol | None) -> None:
        """
        Notify the router that a new peer has connected.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocol_id : TProtocol
            The protocol the peer supports (e.g., floodsub, gossipsub).

        """

    @abstractmethod
    def remove_peer(self, peer_id: ID) -> None:
        """
        Notify the router that a peer has disconnected.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to remove.

        """

    @abstractmethod
    async def handle_rpc(self, rpc: rpc_pb2.RPC, sender_peer_id: ID) -> None:
        """
        Process an RPC message received from a peer.

        Parameters
        ----------
        rpc : rpc_pb2.RPC
            The RPC message to process.
        sender_peer_id : ID
            The identifier of the peer that sent the message.

        """

    @abstractmethod
    async def publish(self, msg_forwarder: ID, pubsub_msg: rpc_pb2.Message) -> None:
        """
        Forward a validated pubsub message.

        Parameters
        ----------
        msg_forwarder : ID
            The identifier of the message sender.
        pubsub_msg : rpc_pb2.Message
            The pubsub message to forward.

        """

    @abstractmethod
    async def join(self, topic: str) -> None:
        """
        Join a topic to receive and forward messages.

        Parameters
        ----------
        topic : str
            The topic to join.

        """

    @abstractmethod
    async def leave(self, topic: str) -> None:
        """
        Leave a topic, stopping message forwarding for that topic.

        Parameters
        ----------
        topic : str
            The topic to leave.

        """


class IPubsub(ServiceAPI):
    """
    Interface for the pubsub system.

    Provides properties and methods to manage topics, subscriptions, and
    message publishing.
    """

    @property
    @abstractmethod
    def my_id(self) -> ID:
        """
        Retrieve the identifier for this pubsub instance.

        Returns
        -------
        ID
            The pubsub identifier.

        """
        ...

    @property
    @abstractmethod
    def protocols(self) -> tuple[TProtocol, ...]:
        """
        Retrieve the protocols used by the pubsub system.

        Returns
        -------
        tuple[TProtocol, ...]
            A tuple of protocol identifiers.

        """
        ...

    @property
    @abstractmethod
    def topic_ids(self) -> KeysView[str]:
        """
        Retrieve the set of topic identifiers.

        Returns
        -------
        KeysView[str]
            A view of the topic identifiers.

        """
        ...

    @abstractmethod
    def set_topic_validator(
        self, topic: str, validator: ValidatorFn, is_async_validator: bool
    ) -> None:
        """
        Set a validator for a specific topic.

        Parameters
        ----------
        topic : str
            The topic for which to set the validator.
        validator : ValidatorFn
            The validator function.
        is_async_validator : bool
            Whether the validator is asynchronous.

        """
        ...

    @abstractmethod
    def remove_topic_validator(self, topic: str) -> None:
        """
        Remove the validator for a specific topic.

        Parameters
        ----------
        topic : str
            The topic whose validator should be removed.

        """
        ...

    @abstractmethod
    async def wait_until_ready(self) -> None:
        """
        Wait until the pubsub system is fully initialized and ready.

        """
        ...

    @abstractmethod
    async def subscribe(self, topic_id: str) -> ISubscriptionAPI:
        """
        Subscribe to a topic.

        Parameters
        ----------
        topic_id : str
            The identifier of the topic to subscribe to.

        Returns
        -------
        ISubscriptionAPI
            An object representing the subscription.

        """
        ...

    @abstractmethod
    async def unsubscribe(self, topic_id: str) -> None:
        """
        Unsubscribe from a topic.

        Parameters
        ----------
        topic_id : str
            The identifier of the topic to unsubscribe from.

        """
        ...

    @abstractmethod
    async def publish(self, topic_id: str | list[str], data: bytes) -> None:
        """
        Publish a message to a topic or multiple topics.

        Parameters
        ----------
        topic_id : str | list[str]
            The identifier of the topic (str) or topics (list[str]).
        data : bytes
            The data to publish.

        """
        ...
