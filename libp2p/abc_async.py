"""
Asynchronous interfaces for py-libp2p components.

This module defines async variants of the core libp2p interfaces,
allowing for fully asynchronous implementations alongside the
synchronous ones.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Sequence

from multiaddr import Multiaddr

from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey
from libp2p.custom_types import MetadataValue
from libp2p.peer.envelope import Envelope
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


class IAsyncPeerMetadata(ABC):
    """Async interface for peer metadata operations."""

    @abstractmethod
    async def get_async(self, peer_id: ID, key: str) -> MetadataValue:
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
        MetadataValue
            The value corresponding to the specified key.

        Raises
        ------
        PeerStoreError
            If the peer ID or value is not found.

        """

    @abstractmethod
    async def put_async(self, peer_id: ID, key: str, val: MetadataValue) -> None:
        """
        Store a key-value pair for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        key : str
            The key for the data.
        val : MetadataValue
            The value to store.

        """

    @abstractmethod
    async def clear_metadata_async(self, peer_id: ID) -> None:
        """
        Clear metadata for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer whose metadata is to be cleared.

        """


class IAsyncAddrBook(ABC):
    """Async interface for address book operations."""

    @abstractmethod
    async def add_addr_async(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
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
    async def add_addrs_async(
        self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int
    ) -> None:
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
    async def addrs_async(self, peer_id: ID) -> list[Multiaddr]:
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
    async def clear_addrs_async(self, peer_id: ID) -> None:
        """
        Clear all addresses for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        """

    @abstractmethod
    async def peers_with_addrs_async(self) -> list[ID]:
        """
        Retrieve all peer IDs that have addresses stored.

        Returns
        -------
        list[ID]
            A list of peer IDs with stored addresses.

        """

    @abstractmethod
    async def addr_stream_async(self, peer_id: ID) -> AsyncIterable[Multiaddr]:
        """
        Returns an async stream of newly added addresses for the given peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID to monitor for address updates.

        Returns
        -------
        AsyncIterable[Multiaddr]
            An async iterator yielding new addresses as they are added.

        """


class IAsyncCertifiedAddrBook(ABC):
    """Async interface for certified address book operations."""

    @abstractmethod
    async def get_local_record_async(self) -> Envelope | None:
        """Get the local-signed-record wrapped in Envelope"""

    @abstractmethod
    async def set_local_record_async(self, envelope: Envelope) -> None:
        """Set the local-signed-record wrapped in Envelope"""

    @abstractmethod
    async def consume_peer_record_async(self, envelope: Envelope, ttl: int) -> bool:
        """
        Accept and store a signed PeerRecord, unless it's older
        than the one already stored.

        Parameters
        ----------
        envelope:
            Signed envelope containing a PeerRecord.
        ttl:
            Time-to-live for the included multiaddrs (in seconds).

        """

    @abstractmethod
    async def get_peer_record_async(self, peer_id: ID) -> Envelope | None:
        """
        Retrieve the most recent signed PeerRecord `Envelope` for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to look up.

        """

    @abstractmethod
    async def maybe_delete_peer_record_async(self, peer_id: ID) -> None:
        """
        Delete the signed peer record for a peer if it has no
        known (non-expired) addresses.

        Parameters
        ----------
        peer_id : ID
            The peer whose record we may delete.

        """


class IAsyncKeyBook(ABC):
    """Async interface for key book operations."""

    @abstractmethod
    async def pubkey_async(self, peer_id: ID) -> PublicKey:
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

        """

    @abstractmethod
    async def add_pubkey_async(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        Add a public key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        pubkey : PublicKey
            The public key to add.

        """

    @abstractmethod
    async def privkey_async(self, peer_id: ID) -> PrivateKey:
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

        """

    @abstractmethod
    async def add_privkey_async(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        Add a private key for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        privkey : PrivateKey
            The private key to add.

        """

    @abstractmethod
    async def add_key_pair_async(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        Add a key pair for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        key_pair : KeyPair
            The key pair to add.

        """

    @abstractmethod
    async def peer_with_keys_async(self) -> list[ID]:
        """
        Retrieve all peer IDs that have keys stored.

        Returns
        -------
        list[ID]
            A list of peer IDs with stored keys.

        """

    @abstractmethod
    async def clear_keydata_async(self, peer_id: ID) -> None:
        """
        Clear key data for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        """


class IAsyncMetrics(ABC):
    """Async interface for metrics operations."""

    @abstractmethod
    async def record_latency_async(self, peer_id: ID, RTT: float) -> None:
        """
        Record a new latency measurement for the given peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        RTT : float
            The round-trip time measurement.

        """

    @abstractmethod
    async def latency_EWMA_async(self, peer_id: ID) -> float:
        """
        Retrieve the latency EWMA for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        float
            The latency EWMA value.

        """

    @abstractmethod
    async def clear_metrics_async(self, peer_id: ID) -> None:
        """
        Clear metrics for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        """


class IAsyncProtoBook(ABC):
    """Async interface for protocol book operations."""

    @abstractmethod
    async def get_protocols_async(self, peer_id: ID) -> list[str]:
        """
        Retrieve the protocols supported by the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        Returns
        -------
        list[str]
            A list of protocol strings.

        """

    @abstractmethod
    async def add_protocols_async(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Add protocols for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to add.

        """

    @abstractmethod
    async def set_protocols_async(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        Set protocols for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to set.

        """

    @abstractmethod
    async def remove_protocols_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> None:
        """
        Remove protocols for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to remove.

        """

    @abstractmethod
    async def supports_protocols_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> list[str]:
        """
        Check which protocols are supported by the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to check.

        Returns
        -------
        list[str]
            A list of supported protocols.

        """

    @abstractmethod
    async def first_supported_protocol_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> str:
        """
        Get the first supported protocol from the given list.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.
        protocols : Sequence[str]
            The protocols to check.

        Returns
        -------
        str
            The first supported protocol.

        """

    @abstractmethod
    async def clear_protocol_data_async(self, peer_id: ID) -> None:
        """
        Clear protocol data for the specified peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer.

        """


class IAsyncPeerStore(
    IAsyncPeerMetadata,
    IAsyncAddrBook,
    IAsyncCertifiedAddrBook,
    IAsyncKeyBook,
    IAsyncMetrics,
    IAsyncProtoBook,
):
    """
    Async interface for a peer store.

    Provides async methods for managing peer information including address
    management, protocol handling, and key storage.
    """

    @abstractmethod
    async def peer_info_async(self, peer_id: ID) -> PeerInfo:
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
    async def peer_ids_async(self) -> list[ID]:
        """
        Retrieve all peer identifiers stored in the peer store.

        Returns
        -------
        list[ID]
            A list of all peer IDs in the store.

        """

    @abstractmethod
    async def clear_peerdata_async(self, peer_id: ID) -> None:
        """Clear all data for the specified peer."""

    @abstractmethod
    async def valid_peer_ids_async(self) -> list[ID]:
        """
        Retrieve all valid (non-expired) peer identifiers.

        Returns
        -------
        list[ID]
            A list of valid peer IDs in the store.

        """

    @abstractmethod
    async def start_cleanup_task(self, cleanup_interval: int = 3600) -> None:
        """Start periodic cleanup of expired peer records and addresses."""

    @abstractmethod
    async def close_async(self) -> None:
        """Close the peerstore and clean up resources."""
