from collections import (
    defaultdict,
)
from collections.abc import (
    AsyncIterable,
    Sequence,
)
from typing import (
    Any,
)

from multiaddr import (
    Multiaddr,
)
import trio
from trio import MemoryReceiveChannel, MemorySendChannel

from libp2p.abc import (
    IPeerStore,
)
from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
    PublicKey,
)

from .id import (
    ID,
)
from .peerdata import (
    PeerData,
    PeerDataError,
)
from .peerinfo import (
    PeerInfo,
)

PERMANENT_ADDR_TTL = 0


class PeerStore(IPeerStore):
    peer_data_map: dict[ID, PeerData]

    def __init__(self) -> None:
        self.peer_data_map = defaultdict(PeerData)
        self.addr_update_channels: dict[ID, MemorySendChannel[Multiaddr]] = {}

    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """
        if peer_id in self.peer_data_map:
            peer_data = self.peer_data_map[peer_id]
            if peer_data.is_expired():
                peer_data.clear_addrs()
            return PeerInfo(peer_id, peer_data.get_addrs())
        raise PeerStoreError("peer ID not found")

    def peer_ids(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        return list(self.peer_data_map.keys())

    def clear_peerdata(self, peer_id: ID) -> None:
        """Clears the peer data of the peer"""

    def valid_peer_ids(self) -> list[ID]:
        """
        :return: all of the valid peer IDs stored in peer store
        """
        valid_peer_ids: list[ID] = []
        for peer_id, peer_data in self.peer_data_map.items():
            if not peer_data.is_expired():
                valid_peer_ids.append(peer_id)
            else:
                peer_data.clear_addrs()
        return valid_peer_ids

    # --------PROTO-BOOK--------

    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_data_map:
            return self.peer_data_map[peer_id].get_protocols()
        raise PeerStoreError("peer ID not found")

    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.add_protocols(list(protocols))

    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.set_protocols(list(protocols))

    def remove_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to get info for
        :param protocols: unsupported protocols to remove
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.remove_protocols(protocols)

    def supports_protocols(self, peer_id: ID, protocols: Sequence[str]) -> list[str]:
        """
        :return: all of the peer IDs stored in peer store
        """
        peer_data = self.peer_data_map[peer_id]
        return peer_data.supports_protocols(protocols)

    def first_supported_protocol(self, peer_id: ID, protocols: Sequence[str]) -> str:
        peer_data = self.peer_data_map[peer_id]
        return peer_data.first_supported_protocol(protocols)

    def clear_protocol_data(self, peer_id: ID) -> None:
        """Clears prtocoldata"""
        peer_data = self.peer_data_map[peer_id]
        peer_data.clear_protocol_data()

    # ------METADATA---------

    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """
        if peer_id in self.peer_data_map:
            try:
                val = self.peer_data_map[peer_id].get_metadata(key)
            except PeerDataError as error:
                raise PeerStoreError() from error
            return val
        raise PeerStoreError("peer ID not found")

    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.put_metadata(key, val)

    def clear_metadata(self, peer_id: ID) -> None:
        """Clears metadata"""
        peer_data = self.peer_data_map[peer_id]
        peer_data.clear_metadata()

    # -------ADDR-BOOK--------

    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int = 0) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """
        self.add_addrs(peer_id, [addr], ttl)

    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int = 0) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.add_addrs(list(addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()

        if peer_id in self.addr_update_channels:
            for addr in addrs:
                try:
                    self.addr_update_channels[peer_id].send_nowait(addr)
                except trio.WouldBlock:
                    pass  # Or consider logging / dropping / replacing stream

    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs of a valid peer.
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_data_map:
            peer_data = self.peer_data_map[peer_id]
            if not peer_data.is_expired():
                return peer_data.get_addrs()
            else:
                peer_data.clear_addrs()
                raise PeerStoreError("peer ID is expired")
        raise PeerStoreError("peer ID not found")

    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """
        # Only clear addresses if the peer is in peer map
        if peer_id in self.peer_data_map:
            self.peer_data_map[peer_id].clear_addrs()

    def peers_with_addrs(self) -> list[ID]:
        """
        :return: all of the peer IDs which has addrsfloat stored in peer store
        """
        # Add all peers with addrs at least 1 to output
        output: list[ID] = []

        for peer_id in self.peer_data_map:
            if len(self.peer_data_map[peer_id].get_addrs()) >= 1:
                peer_data = self.peer_data_map[peer_id]
                if not peer_data.is_expired():
                    output.append(peer_id)
                else:
                    peer_data.clear_addrs()
        return output

    async def addr_stream(self, peer_id: ID) -> AsyncIterable[Multiaddr]:
        """
        Returns an async stream of newly added addresses for the given peer.

        This function allows consumers to subscribe to address updates for a peer
        and receive each new address as it is added via `add_addr` or `add_addrs`.

        :param peer_id: The ID of the peer to monitor address updates for.
        :return: An async iterator yielding Multiaddr instances as they are added.
        """
        send: MemorySendChannel[Multiaddr]
        receive: MemoryReceiveChannel[Multiaddr]

        send, receive = trio.open_memory_channel(0)
        self.addr_update_channels[peer_id] = send

        async for addr in receive:
            yield addr

    # -------KEY-BOOK---------

    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID and pubkey does not match
        """
        peer_data = self.peer_data_map[peer_id]
        if ID.from_pubkey(pubkey) != peer_id:
            raise PeerStoreError("peer ID and pubkey does not match")
        peer_data.add_pubkey(pubkey)

    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID or peer pubkey not found
        """
        if peer_id in self.peer_data_map:
            peer_data = self.peer_data_map[peer_id]
            try:
                pubkey = peer_data.get_pubkey()
            except PeerDataError as e:
                raise PeerStoreError("peer pubkey not found") from e
            return pubkey
        raise PeerStoreError("peer ID not found")

    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        peer_data = self.peer_data_map[peer_id]
        if ID.from_pubkey(privkey.get_public_key()) != peer_id:
            raise PeerStoreError("peer ID and privkey does not match")
        peer_data.add_privkey(privkey)

    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        if peer_id in self.peer_data_map:
            peer_data = self.peer_data_map[peer_id]
            try:
                privkey = peer_data.get_privkey()
            except PeerDataError as e:
                raise PeerStoreError("peer privkey not found") from e
            return privkey
        raise PeerStoreError("peer ID not found")

    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        """
        self.add_pubkey(peer_id, key_pair.public_key)
        self.add_privkey(peer_id, key_pair.private_key)

    def peer_with_keys(self) -> list[ID]:
        """Returns the peer_ids for which keys are stored"""
        return [
            peer_id
            for peer_id, pdata in self.peer_data_map.items()
            if pdata.pubkey is not None
        ]

    def clear_keydata(self, peer_id: ID) -> None:
        """Clears the keys of the peer"""
        peer_data = self.peer_data_map[peer_id]
        peer_data.clear_keydata()

    # --------METRICS--------

    def record_latency(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new latency measurement for the given peer
        using Exponentially Weighted Moving Average (EWMA)

        :param peer_id: peer ID to get private key for
        :param RTT: the new latency value (round trip time)
        """
        peer_data = self.peer_data_map[peer_id]
        peer_data.record_latency(RTT)

    def latency_EWMA(self, peer_id: ID) -> float:
        """
        :param peer_id: peer ID to get private key for
        :return: The latency EWMA value for that peer
        """
        peer_data = self.peer_data_map[peer_id]
        return peer_data.latency_EWMA()

    def clear_metrics(self, peer_id: ID) -> None:
        """Clear the latency metrics"""
        peer_data = self.peer_data_map[peer_id]
        peer_data.clear_metrics()


class PeerStoreError(KeyError):
    """Raised when peer ID is not found in peer store."""
