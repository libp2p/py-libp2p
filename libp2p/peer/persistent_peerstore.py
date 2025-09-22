"""
Persistent peerstore implementation for py-libp2p.

This module provides a persistent peerstore that stores peer data in a datastore
backend, similar to the pstoreds implementation in go-libp2p.
"""

from collections import defaultdict
from collections.abc import AsyncIterable, Sequence
import pickle
from typing import Any

from multiaddr import Multiaddr
import trio
from trio import MemoryReceiveChannel, MemorySendChannel

from libp2p.abc import IPeerStore
from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey
from libp2p.peer.envelope import Envelope

from .datastore import IDatastore
from .id import ID
from .peerdata import PeerData, PeerDataError
from .peerinfo import PeerInfo
from .peerstore import (
    PeerRecordState,
    PeerStoreError,
)


class PersistentPeerStore(IPeerStore):
    """
    Persistent peerstore implementation that stores peer data in a datastore backend.

    This implementation follows the same interface as the in-memory PeerStore but
    persists data to a datastore backend, similar to the pstoreds implementation
    in go-libp2p.
    """

    def __init__(self, datastore: IDatastore, max_records: int = 10000) -> None:
        """
        Initialize persistent peerstore.

        Args:
            datastore: The datastore backend to use for persistence
            max_records: Maximum number of peer records to store

        """
        self.datastore = datastore
        self.max_records = max_records

        # In-memory caches for frequently accessed data
        self.peer_data_map: dict[ID, PeerData] = defaultdict(PeerData)
        self.addr_update_channels: dict[ID, MemorySendChannel[Multiaddr]] = {}
        self.peer_record_map: dict[ID, PeerRecordState] = {}
        self.local_peer_record: Envelope | None = None

        # Key prefixes for different data types
        self.ADDR_PREFIX = b"addr:"
        self.KEY_PREFIX = b"key:"
        self.METADATA_PREFIX = b"metadata:"
        self.PROTOCOL_PREFIX = b"protocol:"
        self.PEER_RECORD_PREFIX = b"peer_record:"
        self.LOCAL_RECORD_KEY = b"local_record"

    def _get_addr_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for peer addresses."""
        return self.ADDR_PREFIX + peer_id.to_bytes()

    def _get_key_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for peer keys."""
        return self.KEY_PREFIX + peer_id.to_bytes()

    def _get_metadata_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for peer metadata."""
        return self.METADATA_PREFIX + peer_id.to_bytes()

    def _get_protocol_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for peer protocols."""
        return self.PROTOCOL_PREFIX + peer_id.to_bytes()

    def _get_peer_record_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for peer records."""
        return self.PEER_RECORD_PREFIX + peer_id.to_bytes()

    async def _load_peer_data(self, peer_id: ID) -> PeerData:
        """Load peer data from datastore, creating if not exists."""
        if peer_id not in self.peer_data_map:
            peer_data = PeerData()

            # Load addresses
            addr_key = self._get_addr_key(peer_id)
            addr_data = await self.datastore.get(addr_key)
            if addr_data:
                addrs = pickle.loads(addr_data)
                peer_data.addrs = addrs

            # Load keys
            key_key = self._get_key_key(peer_id)
            key_data = await self.datastore.get(key_key)
            if key_data:
                keys = pickle.loads(key_data)
                peer_data.pubkey = keys.get("pubkey")
                peer_data.privkey = keys.get("privkey")

            # Load metadata
            metadata_key = self._get_metadata_key(peer_id)
            metadata_data = await self.datastore.get(metadata_key)
            if metadata_data:
                peer_data.metadata = pickle.loads(metadata_data)

            # Load protocols
            protocol_key = self._get_protocol_key(peer_id)
            protocol_data = await self.datastore.get(protocol_key)
            if protocol_data:
                peer_data.protocols = pickle.loads(protocol_data)

            self.peer_data_map[peer_id] = peer_data

        return self.peer_data_map[peer_id]

    async def _save_peer_data(self, peer_id: ID, peer_data: PeerData) -> None:
        """Save peer data to datastore."""
        # Save addresses
        addr_key = self._get_addr_key(peer_id)
        await self.datastore.put(addr_key, pickle.dumps(peer_data.addrs))

        # Save keys
        key_key = self._get_key_key(peer_id)
        keys = {"pubkey": peer_data.pubkey, "privkey": peer_data.privkey}
        await self.datastore.put(key_key, pickle.dumps(keys))

        # Save metadata
        metadata_key = self._get_metadata_key(peer_id)
        await self.datastore.put(metadata_key, pickle.dumps(peer_data.metadata))

        # Save protocols
        protocol_key = self._get_protocol_key(peer_id)
        await self.datastore.put(protocol_key, pickle.dumps(peer_data.protocols))

    async def _load_peer_record(self, peer_id: ID) -> PeerRecordState | None:
        """Load peer record from datastore."""
        if peer_id not in self.peer_record_map:
            record_key = self._get_peer_record_key(peer_id)
            record_data = await self.datastore.get(record_key)
            if record_data:
                record_state = pickle.loads(record_data)
                self.peer_record_map[peer_id] = record_state
                return record_state
        return self.peer_record_map.get(peer_id)

    async def _save_peer_record(
        self, peer_id: ID, record_state: PeerRecordState
    ) -> None:
        """Save peer record to datastore."""
        record_key = self._get_peer_record_key(peer_id)
        await self.datastore.put(record_key, pickle.dumps(record_state))
        self.peer_record_map[peer_id] = record_state

    async def _load_local_record(self) -> None:
        """Load local peer record from datastore."""
        local_data = await self.datastore.get(self.LOCAL_RECORD_KEY)
        if local_data:
            self.local_peer_record = pickle.loads(local_data)

    async def _save_local_record(self, envelope: Envelope) -> None:
        """Save local peer record to datastore."""
        await self.datastore.put(self.LOCAL_RECORD_KEY, pickle.dumps(envelope))
        self.local_peer_record = envelope

    def get_local_record(self) -> Envelope | None:
        """Get the local-signed-record wrapped in Envelope"""
        return self.local_peer_record

    def set_local_record(self, envelope: Envelope) -> None:
        """Set the local-signed-record wrapped in Envelope"""
        # Save to datastore asynchronously
        trio.from_thread.run_sync(lambda: trio.run(self._save_local_record, envelope))

    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """

        async def _inner() -> PeerInfo:
            peer_data = await self._load_peer_data(peer_id)
            if peer_data.is_expired():
                peer_data.clear_addrs()
                await self._save_peer_data(peer_id, peer_data)
            return PeerInfo(peer_id, peer_data.get_addrs())

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def peer_ids(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        # Query all peer IDs from datastore
        peer_ids: set[ID] = set()
        for key, _ in self.datastore.query(self.ADDR_PREFIX):
            peer_id_bytes = key[len(self.ADDR_PREFIX) :]
            peer_ids.add(ID(peer_id_bytes))
        return list(peer_ids)

    def clear_peerdata(self, peer_id: ID) -> None:
        """Clears all data associated with the given peer_id."""
        # Remove from memory
        if peer_id in self.peer_data_map:
            del self.peer_data_map[peer_id]

        # Remove from datastore
        keys_to_delete = [
            self._get_addr_key(peer_id),
            self._get_key_key(peer_id),
            self._get_metadata_key(peer_id),
            self._get_protocol_key(peer_id),
            self._get_peer_record_key(peer_id),
        ]

        async def _inner() -> None:
            for key in keys_to_delete:
                await self.datastore.delete(key)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

        # Clear peer records from memory
        if peer_id in self.peer_record_map:
            del self.peer_record_map[peer_id]

    def valid_peer_ids(self) -> list[ID]:
        """
        :return: all of the valid peer IDs stored in peer store
        """

        async def _inner() -> list[ID]:
            valid_peer_ids: list[ID] = []
            all_peer_ids = self.peer_ids()
            for peer_id in all_peer_ids:
                peer_data = await self._load_peer_data(peer_id)
                if not peer_data.is_expired():
                    valid_peer_ids.append(peer_id)
                else:
                    peer_data.clear_addrs()
                    await self._save_peer_data(peer_id, peer_data)
            return valid_peer_ids

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def _enforce_record_limit(self) -> None:
        """Enforce maximum number of stored records."""
        if len(self.peer_record_map) > self.max_records:
            # Record oldest records based on sequence number
            sorted_records = sorted(
                self.peer_record_map.items(), key=lambda x: x[1].seq
            )
            records_to_remove = len(self.peer_record_map) - self.max_records
            for peer_id, _ in sorted_records[:records_to_remove]:
                trio.from_thread.run_sync(
                    lambda: trio.run(self._maybe_delete_peer_record_async, peer_id)
                )
                del self.peer_record_map[peer_id]

    async def start_cleanup_task(self, cleanup_interval: int = 3600) -> None:
        """Start periodic cleanup of expired peer records and addresses."""
        while True:
            await trio.sleep(cleanup_interval)
            await self._cleanup_expired_records()

    async def _cleanup_expired_records(self) -> None:
        """Remove expired peer records and addresses"""
        all_peer_ids = self.peer_ids()
        expired_peers = []

        for peer_id in all_peer_ids:
            peer_data = await self._load_peer_data(peer_id)
            if peer_data.is_expired():
                expired_peers.append(peer_id)

        for peer_id in expired_peers:
            await self._maybe_delete_peer_record_async(peer_id)
            await self._clear_peerdata_async(peer_id)

        self._enforce_record_limit()

    # --------PROTO-BOOK--------

    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """

        async def _inner() -> list[str]:
            peer_data = await self._load_peer_data(peer_id)
            return peer_data.get_protocols()

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.add_protocols(list(protocols))
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.set_protocols(list(protocols))
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def remove_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to get info for
        :param protocols: unsupported protocols to remove
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.remove_protocols(protocols)
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def supports_protocols(self, peer_id: ID, protocols: Sequence[str]) -> list[str]:
        """
        :return: all of the peer IDs stored in peer store
        """

        async def _inner() -> list[str]:
            peer_data = await self._load_peer_data(peer_id)
            return peer_data.supports_protocols(protocols)

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def first_supported_protocol(self, peer_id: ID, protocols: Sequence[str]) -> str:
        async def _inner() -> str:
            peer_data = await self._load_peer_data(peer_id)
            return peer_data.first_supported_protocol(protocols)

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def clear_protocol_data(self, peer_id: ID) -> None:
        """Clears protocol data"""

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_protocol_data()
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    # ------METADATA---------

    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """

        async def _inner() -> Any:
            peer_data = await self._load_peer_data(peer_id)
            try:
                val = peer_data.get_metadata(key)
            except PeerDataError as error:
                raise PeerStoreError() from error
            return val

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.put_metadata(key, val)
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def clear_metadata(self, peer_id: ID) -> None:
        """Clears metadata"""

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_metadata()
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    # -----CERT-ADDR-BOOK-----

    def maybe_delete_peer_record(self, peer_id: ID) -> None:
        """
        Delete the signed peer record for a peer if it has no known
        (non-expired) addresses.
        """

        async def _inner() -> None:
            addrs = await self._addrs_async(peer_id)
            if not addrs and peer_id in self.peer_record_map:
                record_key = self._get_peer_record_key(peer_id)
                await self.datastore.delete(record_key)
                del self.peer_record_map[peer_id]

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def consume_peer_record(self, envelope: Envelope, ttl: int) -> bool:
        """
        Accept and store a signed PeerRecord, unless it's older than
        the one already stored.
        """

        async def _inner() -> bool:
            record = envelope.record()
            peer_id = record.peer_id
            existing = await self._load_peer_record(peer_id)
            if existing and existing.seq > record.seq:
                return False
            new_addrs = set(record.addrs)
            record_state = PeerRecordState(envelope, record.seq)
            await self._save_peer_record(peer_id, record_state)
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_addrs()
            await self._add_addrs_async(peer_id, list(new_addrs), ttl)
            return True

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def consume_peer_records(self, envelopes: list[Envelope], ttl: int) -> list[bool]:
        """Consume multiple peer records in a single operation."""

        async def _inner() -> list[bool]:
            results: list[bool] = []
            for envelope in envelopes:
                results.append(
                    await trio.to_thread.run_sync(
                        self.consume_peer_record, envelope, ttl
                    )
                )
            return results

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def get_peer_record(self, peer_id: ID) -> Envelope | None:
        """
        Retrieve the most recent signed PeerRecord `Envelope` for a peer, if it exists
        and is still relevant.
        """

        async def _inner() -> Envelope | None:
            await self._maybe_delete_peer_record_async(peer_id)
            try:
                addrs = await self._addrs_async(peer_id)
                if addrs:
                    record_state = await self._load_peer_record(peer_id)
                    if record_state is not None:
                        return record_state.envelope
            except PeerStoreError:
                pass
            return None

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    # -------ADDR-BOOK--------

    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """
        self.add_addrs(peer_id, [addr], ttl)

    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.add_addrs(list(addrs))
            peer_data.set_ttl(ttl)
            peer_data.update_last_identified()
            await self._save_peer_data(peer_id, peer_data)

            if peer_id in self.addr_update_channels:
                for addr in addrs:
                    try:
                        self.addr_update_channels[peer_id].send_nowait(addr)
                    except trio.WouldBlock:
                        pass

            await self._maybe_delete_peer_record_async(peer_id)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs of a valid peer.
        :raise PeerStoreError: if peer ID not found
        """

        async def _inner() -> list[Multiaddr]:
            peer_data = await self._load_peer_data(peer_id)
            if not peer_data.is_expired():
                return peer_data.get_addrs()
            else:
                peer_data.clear_addrs()
                await self._save_peer_data(peer_id, peer_data)
                raise PeerStoreError("peer ID is expired")

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_addrs()
            await self._save_peer_data(peer_id, peer_data)
            await self._maybe_delete_peer_record_async(peer_id)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def peers_with_addrs(self) -> list[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """

        async def _inner() -> list[ID]:
            output: list[ID] = []
            all_peer_ids = self.peer_ids()
            for peer_id in all_peer_ids:
                peer_data = await self._load_peer_data(peer_id)
                if len(peer_data.get_addrs()) >= 1:
                    if not peer_data.is_expired():
                        output.append(peer_id)
                    else:
                        peer_data.clear_addrs()
                        await self._save_peer_data(peer_id, peer_data)
            return output

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    async def addr_stream(self, peer_id: ID) -> AsyncIterable[Multiaddr]:
        """
        Returns an async stream of newly added addresses for the given peer.
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

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            if ID.from_pubkey(pubkey) != peer_id:
                raise PeerStoreError("peer ID and pubkey does not match")
            peer_data.add_pubkey(pubkey)
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID or peer pubkey not found
        """

        async def _inner() -> PublicKey:
            peer_data = await self._load_peer_data(peer_id)
            try:
                pubkey = peer_data.get_pubkey()
            except PeerDataError as e:
                raise PeerStoreError("peer pubkey not found") from e
            return pubkey

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID or peer privkey not found
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            if ID.from_pubkey(privkey.get_public_key()) != peer_id:
                raise PeerStoreError("peer ID and privkey does not match")
            peer_data.add_privkey(privkey)
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID or peer privkey not found
        """

        async def _inner() -> PrivateKey:
            peer_data = await self._load_peer_data(peer_id)
            try:
                privkey = peer_data.get_privkey()
            except PeerDataError as e:
                raise PeerStoreError("peer privkey not found") from e
            return privkey

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        """
        self.add_pubkey(peer_id, key_pair.public_key)
        self.add_privkey(peer_id, key_pair.private_key)

    def peer_with_keys(self) -> list[ID]:
        """Returns the peer_ids for which keys are stored"""

        async def _inner() -> list[ID]:
            peer_ids_with_keys: list[ID] = []
            all_peer_ids = self.peer_ids()
            for peer_id in all_peer_ids:
                peer_data = await self._load_peer_data(peer_id)
                if peer_data.pubkey is not None:
                    peer_ids_with_keys.append(peer_id)
            return peer_ids_with_keys

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def clear_keydata(self, peer_id: ID) -> None:
        """Clears the keys of the peer"""

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_keydata()
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    # --------METRICS--------

    def record_latency(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new latency measurement for the given peer
        using Exponentially Weighted Moving Average (EWMA)
        """

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.record_latency(RTT)
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    def latency_EWMA(self, peer_id: ID) -> float:
        """
        :param peer_id: peer ID to get private key for
        :return: The latency EWMA value for that peer
        """

        async def _inner() -> float:
            peer_data = await self._load_peer_data(peer_id)
            return peer_data.latency_EWMA()

        return trio.from_thread.run_sync(lambda: trio.run(_inner))

    def clear_metrics(self, peer_id: ID) -> None:
        """Clear the latency metrics"""

        async def _inner() -> None:
            peer_data = await self._load_peer_data(peer_id)
            peer_data.clear_metrics()
            await self._save_peer_data(peer_id, peer_data)

        trio.from_thread.run_sync(lambda: trio.run(_inner))

    async def close(self) -> None:
        """Close the persistent peerstore and underlying datastore."""
        if hasattr(self.datastore, "close"):
            await self.datastore.close()

    # --- Internal async wrappers for sync API ---
    async def _add_addrs_async(
        self, peer_id: ID, addrs: list[Multiaddr], ttl: int
    ) -> None:
        peer_data = await self._load_peer_data(peer_id)
        peer_data.add_addrs(list(addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()
        await self._save_peer_data(peer_id, peer_data)

    async def _addrs_async(self, peer_id: ID) -> list[Multiaddr]:
        peer_data = await self._load_peer_data(peer_id)
        if not peer_data.is_expired():
            return peer_data.get_addrs()
        else:
            peer_data.clear_addrs()
            await self._save_peer_data(peer_id, peer_data)
            raise PeerStoreError("peer ID is expired")

    async def _maybe_delete_peer_record_async(self, peer_id: ID) -> None:
        addrs = await self._addrs_async(peer_id)
        if not addrs and peer_id in self.peer_record_map:
            record_key = self._get_peer_record_key(peer_id)
            await self.datastore.delete(record_key)
            del self.peer_record_map[peer_id]

    async def _clear_peerdata_async(self, peer_id: ID) -> None:
        keys_to_delete = [
            self._get_addr_key(peer_id),
            self._get_key_key(peer_id),
            self._get_metadata_key(peer_id),
            self._get_protocol_key(peer_id),
            self._get_peer_record_key(peer_id),
        ]
        for key in keys_to_delete:
            await self.datastore.delete(key)
        if peer_id in self.peer_data_map:
            del self.peer_data_map[peer_id]
