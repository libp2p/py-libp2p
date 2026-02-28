from collections import (
    defaultdict,
)
from collections.abc import (
    AsyncIterable,
    Sequence,
)

from multiaddr import (
    Multiaddr,
)
import trio
from trio import MemoryReceiveChannel, MemorySendChannel

from libp2p.abc import (
    IHost,
    IPeerStore,
)
from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
    PublicKey,
)
from libp2p.custom_types import (
    MetadataValue,
)
from libp2p.peer.envelope import Envelope, seal_record
from libp2p.peer.peer_record import PeerRecord

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


def create_signed_peer_record(
    peer_id: ID, addrs: list[Multiaddr], pvt_key: PrivateKey
) -> Envelope:
    """Creates a signed_peer_record wrapped in an Envelope"""
    record = PeerRecord(peer_id, addrs)
    envelope = seal_record(record, pvt_key)
    return envelope


def env_to_send_in_RPC(host: IHost) -> tuple[bytes, bool]:
    """
    Return the signed peer record (Envelope) to be sent in an RPC.

    This function checks whether the host already has a cached signed peer record
    (SPR). If one exists and its addresses match the host's current listen
    addresses, the cached envelope is reused. Otherwise, a new signed peer record
    is created, cached, and returned.

    Parameters
    ----------
    host : IHost
        The local host instance, providing access to peer ID, listen addresses,
        private key, and the peerstore.

    Returns
    -------
    tuple[bytes, bool]
        A 2-tuple where the first element is the serialized envelope (bytes)
        for the signed peer record, and the second element is a boolean flag
        indicating whether a new record was created (True) or an existing cached
        one was reused (False).

    """
    listen_addrs_set = {addr for addr in host.get_addrs()}
    local_env = host.get_peerstore().get_local_record()

    if local_env is None:
        # No cached SPR yet -> create one
        return issue_and_cache_local_record(host), True
    else:
        record_addrs_set = local_env._env_addrs_set()
        if record_addrs_set == listen_addrs_set:
            # Perfect match -> reuse cached envelope
            return local_env.marshal_envelope(), False
        else:
            # Addresses changed -> issue a new SPR and cache it
            return issue_and_cache_local_record(host), True


def issue_and_cache_local_record(host: IHost) -> bytes:
    """
    Create and cache a new signed peer record (Envelope) for the host.

    This function generates a new signed peer record from the host’s peer ID,
    listen addresses, and private key. The resulting envelope is stored in
    the peerstore as the local record for future reuse.

    Parameters
    ----------
    host : IHost
        The local host instance, providing access to peer ID, listen addresses,
        private key, and the peerstore.

    Returns
    -------
    bytes
        The serialized envelope (bytes) representing the newly created signed
        peer record.

    """
    env = create_signed_peer_record(
        host.get_id(),
        host.get_addrs(),
        host.get_private_key(),
    )
    # Cache it for next time use
    host.get_peerstore().set_local_record(env)
    return env.marshal_envelope()


class PeerRecordState:
    envelope: Envelope
    seq: int

    def __init__(self, envelope: Envelope, seq: int):
        self.envelope = envelope
        self.seq = seq


class PeerStore(IPeerStore):
    peer_data_map: dict[ID, PeerData]

    def __init__(self, max_records: int = 10000) -> None:
        self.peer_data_map = defaultdict(PeerData)
        self.addr_update_channels: dict[ID, MemorySendChannel[Multiaddr]] = {}
        self.peer_record_map: dict[ID, PeerRecordState] = {}
        self.local_peer_record: Envelope | None = None
        self.max_records = max_records

    def get_local_record(self) -> Envelope | None:
        """Get the local-signed-record wrapped in Envelope"""
        return self.local_peer_record

    def set_local_record(self, envelope: Envelope) -> None:
        """Set the local-signed-record wrapped in Envelope"""
        self.local_peer_record = envelope

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
        """Clears all data associated with the given peer_id."""
        if peer_id in self.peer_data_map:
            del self.peer_data_map[peer_id]
        else:
            raise PeerStoreError("peer ID not found")

        # Clear the peer records
        if peer_id in self.peer_record_map:
            self.peer_record_map.pop(peer_id, None)

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

    def _enforce_record_limit(self) -> None:
        """Enforce maximum number of stored records."""
        if len(self.peer_record_map) > self.max_records:
            # Record oldest records based on seequence number
            sorted_records = sorted(
                self.peer_record_map.items(), key=lambda x: x[1].seq
            )
            records_to_remove = len(self.peer_record_map) - self.max_records
            for peer_id, _ in sorted_records[:records_to_remove]:
                self.maybe_delete_peer_record(peer_id)
                del self.peer_record_map[peer_id]

    async def start_cleanup_task(self, cleanup_interval: int = 3600) -> None:
        """Start periodic cleanup of expired peer records and addresses."""
        while True:
            await trio.sleep(cleanup_interval)
            self._cleanup_expired_records()

    def _cleanup_expired_records(self) -> None:
        """Remove expired peer records and addresses"""
        expired_peers = []

        for peer_id, peer_data in self.peer_data_map.items():
            if peer_data.is_expired():
                expired_peers.append(peer_id)

        for peer_id in expired_peers:
            self.maybe_delete_peer_record(peer_id)
            del self.peer_data_map[peer_id]

        self._enforce_record_limit()

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

    def get(self, peer_id: ID, key: str) -> MetadataValue:
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

    def put(self, peer_id: ID, key: str, val: MetadataValue) -> None:
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

    # -----CERT-ADDR-BOOK-----

    def maybe_delete_peer_record(self, peer_id: ID) -> None:
        """
        Delete the signed peer record for a peer if it has no know
        (non-expired) addresses.

        This is a garbage collection mechanism: if all addresses for a peer have expired
        or been cleared, there's no point holding onto its signed `Envelope`

        :param peer_id: The peer whose record we may delete/
        """
        if peer_id in self.peer_record_map:
            if not self.addrs(peer_id):
                self.peer_record_map.pop(peer_id, None)

    def consume_peer_record(self, envelope: Envelope, ttl: int) -> bool:
        """
        Accept and store a signed PeerRecord, unless it's older than
        the one already stored.

        This function:
        - Extracts the peer ID and sequence number from the envelope
        - Rejects the record if it's older (lower seq)
        - Updates the stored peer record and replaces associated addresses if accepted

        :param envelope: Signed envelope containing a PeerRecord.
        :param ttl: Time-to-live for the included multiaddrs (in seconds).
        :return: True if the record was accepted and stored; False if it was rejected.
        """
        record = envelope.record()
        peer_id = record.peer_id

        existing = self.peer_record_map.get(peer_id)
        if existing and existing.seq > record.seq:
            return False  # reject older record

        new_addrs = set(record.addrs)

        self.peer_record_map[peer_id] = PeerRecordState(envelope, record.seq)
        self.peer_data_map[peer_id].clear_addrs()
        self.add_addrs(peer_id, list(new_addrs), ttl)

        return True

    def consume_peer_records(self, envelopes: list[Envelope], ttl: int) -> list[bool]:
        """Consume multiple peer records in a single operation."""
        results = []
        for envelope in envelopes:
            results.append(self.consume_peer_record(envelope, ttl))
        return results

    def get_peer_record(self, peer_id: ID) -> Envelope | None:
        """
        Retrieve the most recent signed PeerRecord `Envelope` for a peer, if it exists
        and is still relevant.

        First, it runs cleanup via `maybe_delete_peer_record` to purge stale data.
        Then it checks whether the peer has valid, unexpired addresses before
        returning the associated envelope.

        :param peer_id: The peer to look up.
        :return: The signed Envelope if the peer is known and has valid
            addresses; None otherwise.

        """
        self.maybe_delete_peer_record(peer_id)

        # Check if the peer has any valid addresses
        if (
            peer_id in self.peer_data_map
            and not self.peer_data_map[peer_id].is_expired()
        ):
            state = self.peer_record_map.get(peer_id)
            if state is not None:
                return state.envelope
        return None

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

        self.maybe_delete_peer_record(peer_id)

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

        self.maybe_delete_peer_record(peer_id)

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
