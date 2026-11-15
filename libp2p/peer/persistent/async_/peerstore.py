"""
Asynchronous persistent peerstore implementation for py-libp2p.

This module provides an asynchronous persistent peerstore that stores peer data
in a datastore backend, similar to the pstoreds implementation in go-libp2p.
All operations are purely asynchronous using trio.
"""

from collections import defaultdict
from collections.abc import AsyncIterable, Sequence
import logging
import time

from multiaddr import Multiaddr
import trio
from trio import MemoryReceiveChannel, MemorySendChannel

from libp2p.abc_async import IAsyncPeerStore
from libp2p.crypto.exceptions import CryptographyError
from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey
from libp2p.crypto.serialization import (
    deserialize_private_key,
    deserialize_public_key,
)
from libp2p.custom_types import MetadataValue
from libp2p.peer.envelope import Envelope
from libp2p.peer.id import ID
from libp2p.peer.peerdata import MAX_ADDRS_PER_PEER, PeerData, PeerDataError
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import (
    PeerRecordState,
    PeerStoreError,
    _peer_record_signer_matches,
)

from ..datastore.base import IDatastore
from ..serialization import (
    SerializationError,
    deserialize_addresses,
    deserialize_envelope,
    deserialize_latency,
    deserialize_metadata,
    deserialize_protocols,
    deserialize_record_state,
    serialize_addresses,
    serialize_envelope,
    serialize_latency,
    serialize_metadata,
    serialize_protocols,
    serialize_record_state,
)

logger = logging.getLogger(__name__)


class AsyncPersistentPeerStore(IAsyncPeerStore):
    """
    Asynchronous persistent peerstore implementation that stores peer data
    in a datastore backend.

    This implementation follows the IAsyncPeerStore interface with purely
    asynchronous operations. All data is persisted to the datastore backend
    using async/await, similar to the pstoreds implementation in go-libp2p.
    """

    def __init__(
        self,
        datastore: IDatastore,
        max_records: int = 10000,
        sync_interval: float = 1.0,
        auto_sync: bool = True,
        max_cached_peers: int = 1000,
        max_stored_peers: int | None = None,
    ) -> None:
        """
        Initialize asynchronous persistent peerstore.

        Args:
            datastore: The asynchronous datastore backend to use for persistence
            max_records: Maximum number of peer records to store
            sync_interval: Minimum interval between sync operations (seconds)
            auto_sync: Whether to automatically sync after writes
            max_cached_peers: Maximum number of peer data objects cached in memory
            max_stored_peers: Maximum number of peers whose records are kept in
                the datastore. ``None`` uses ``max_records``.

        :raises ValueError: If datastore is None or max_records is invalid

        """
        if datastore is None:
            raise ValueError("datastore cannot be None")
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        if max_cached_peers <= 0:
            raise ValueError("max_cached_peers must be positive")
        if max_stored_peers is not None and max_stored_peers <= 0:
            raise ValueError("max_stored_peers must be positive")

        self.datastore = datastore
        self.max_records = max_records
        self.max_cached_peers = max_cached_peers
        # A cache cap alone does not bound the datastore: evicted peers keep
        # their rows forever, so every peer ever seen grows the database.
        self.max_stored_peers = (
            max_records if max_stored_peers is None else max_stored_peers
        )
        self._writes_since_prune = 0
        self.local_peer_id: ID | None = None
        self.sync_interval = sync_interval
        self.auto_sync = auto_sync
        self._last_sync = time.time()
        self._pending_sync = False

        # In-memory caches for frequently accessed data
        self.peer_data_map: dict[ID, PeerData] = defaultdict(PeerData)
        self.addr_update_channels: dict[ID, MemorySendChannel[Multiaddr]] = {}
        self.peer_record_map: dict[ID, PeerRecordState] = {}
        self.local_peer_record: Envelope | None = None

        # Thread safety for concurrent access
        self._lock = trio.Lock()

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

    def _get_additional_key(self, peer_id: ID) -> bytes:
        """Get the datastore key for additional peer data fields."""
        return b"additional:" + peer_id.to_bytes()

    def _get_latency_key(self, peer_id: ID) -> bytes:
        """Get datastore key for peer latency data."""
        return b"latency:" + peer_id.to_bytes()

    async def _load_peer_data(self, peer_id: ID) -> PeerData:
        """Load peer data from datastore, creating if not exists."""
        async with self._lock:
            if peer_id not in self.peer_data_map:
                peer_data = PeerData()

                try:
                    # Load addresses
                    addr_key = self._get_addr_key(peer_id)
                    addr_data = await self.datastore.get(addr_key)
                    if addr_data:
                        peer_data.addrs = deserialize_addresses(addr_data)
                        # Rows written before the per-peer cap may hold
                        # hundreds of stale addresses; never load more than
                        # the cap.
                        if len(peer_data.addrs) > MAX_ADDRS_PER_PEER:
                            peer_data.addrs = peer_data.addrs[-MAX_ADDRS_PER_PEER:]

                    # Load keys
                    key_key = self._get_key_key(peer_id)
                    key_data = await self.datastore.get(key_key)
                    if key_data:
                        keys_metadata = deserialize_metadata(key_data)
                        if keys_metadata.get("pubkey"):
                            peer_data.pubkey = deserialize_public_key(
                                keys_metadata["pubkey"]
                            )
                        if keys_metadata.get("privkey"):
                            peer_data.privkey = deserialize_private_key(
                                keys_metadata["privkey"]
                            )

                    # Load metadata
                    metadata_key = self._get_metadata_key(peer_id)
                    metadata_data = await self.datastore.get(metadata_key)
                    if metadata_data:
                        metadata_bytes = deserialize_metadata(metadata_data)
                        # Convert bytes back to appropriate types
                        peer_data.metadata = {
                            k: v.decode("utf-8") if isinstance(v, bytes) else v
                            for k, v in metadata_bytes.items()
                        }

                    # Load protocols
                    protocol_key = self._get_protocol_key(peer_id)
                    protocol_data = await self.datastore.get(protocol_key)
                    if protocol_data:
                        peer_data.protocols = deserialize_protocols(protocol_data)

                    # Load latency data
                    latency_key = self._get_latency_key(peer_id)
                    latency_data = await self.datastore.get(latency_key)
                    if latency_data:
                        latency_ns = deserialize_latency(latency_data)
                        # Convert nanoseconds back to seconds for latmap
                        peer_data.latmap = latency_ns / 1_000_000_000

                    # Restore TTL/last-seen so cache eviction does not turn a
                    # finite address TTL into the PeerData default (permanent).
                    additional_data = await self.datastore.get(
                        self._get_additional_key(peer_id)
                    )
                    if additional_data:
                        additional = deserialize_metadata(additional_data)
                        peer_data.ttl = int(additional.get("ttl", b"0"))
                        peer_data.last_identified = int(
                            additional.get(
                                "last_identified", str(peer_data.last_identified)
                            )
                        )

                except (
                    SerializationError,
                    CryptographyError,
                    KeyError,
                    ValueError,
                    TypeError,
                ) as e:
                    logger.error(f"Failed to load peer data for {peer_id}: {e}")
                    # Continue with empty peer data
                except Exception:
                    logger.exception(
                        f"Unexpected error loading peer data for {peer_id}"
                    )
                    # Continue with empty peer data

                if peer_data.privkey is not None:
                    self.local_peer_id = peer_id

                self.peer_data_map[peer_id] = peer_data
                self._enforce_peer_data_cache_limit()
            return self.peer_data_map[peer_id]

    def _enforce_peer_data_cache_limit(self) -> None:
        """
        Evict least-recently-inserted cached peer data beyond the cap.

        PeerData defaults to ttl=0 (always valid), so the periodic expiry
        cleanup never removes entries for peers that were merely queried.
        Without a cache cap, a long-running node accumulates one PeerData
        object for every peer ID it has ever looked up.
        """
        while len(self.peer_data_map) > self.max_cached_peers:
            oldest = next(iter(self.peer_data_map))
            self.peer_data_map.pop(oldest, None)

    # --------BOUNDED PERSISTED PEER SET--------

    DATASTORE_PRUNE_INTERVAL = 512
    DATASTORE_PRUNE_BATCH = 512

    async def _iter_stored_peer_ids(self) -> list[ID]:
        """Peer IDs that currently have a persisted address record."""
        peer_ids: list[ID] = []
        prefix_len = len(self.ADDR_PREFIX)
        try:
            for key, _ in self.datastore.query(self.ADDR_PREFIX):
                if not key.startswith(self.ADDR_PREFIX):
                    continue
                try:
                    peer_ids.append(ID(key[prefix_len:]))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to enumerate stored peers: {e}")
        return peer_ids

    async def _peer_recency(self, peer_id: ID) -> int:
        """Best-effort last-seen timestamp for a persisted peer."""
        try:
            data = await self.datastore.get(self._get_additional_key(peer_id))
            if data:
                return int(deserialize_metadata(data).get("last_identified", 0))
        except Exception:
            pass
        return 0

    async def _delete_peers_from_datastore(self, peer_ids: Sequence[ID]) -> None:
        """Delete all persisted rows for the given peers in one batch."""
        if not peer_ids:
            return
        keys = [
            self._get_addr_key,
            self._get_key_key,
            self._get_metadata_key,
            self._get_protocol_key,
            self._get_peer_record_key,
            self._get_additional_key,
            self._get_latency_key,
        ]
        try:
            batch_factory = getattr(self.datastore, "batch", None)
            if batch_factory is not None:
                batch = await batch_factory()
                for peer_id in peer_ids:
                    for key_fn in keys:
                        await batch.delete(key_fn(peer_id))
                await batch.commit()
            else:
                for peer_id in peer_ids:
                    for key_fn in keys:
                        await self.datastore.delete(key_fn(peer_id))
            await self.datastore.sync(b"")
            for peer_id in peer_ids:
                self.peer_data_map.pop(peer_id, None)
                self.peer_record_map.pop(peer_id, None)
        except Exception as e:
            logger.error(f"Failed to delete {len(peer_ids)} peers from datastore: {e}")

    async def enforce_datastore_limit_async(
        self,
        limit: int | None = None,
        max_deletes: int | None = None,
    ) -> int:
        """
        Trim the persisted peer set down to ``limit`` peers.

        Evicting a peer from the in-memory cache does not remove its rows, so
        without this the datastore retains one record for every peer the node
        has ever seen.  Cached peers are never candidates; among the rest the
        least recently seen peers are removed first.

        Returns:
            The number of peers removed.

        """
        cap = self.max_stored_peers if limit is None else limit
        async with self._lock:
            stored_ids = await self._iter_stored_peer_ids()
            overflow = len(stored_ids) - cap
            if overflow <= 0:
                return 0
            if max_deletes is not None:
                overflow = min(overflow, max_deletes)

            cached = set(self.peer_data_map)
            candidates: list[tuple[int, ID]] = []
            for peer_id in stored_ids:
                if peer_id == self.local_peer_id or peer_id in cached:
                    continue
                candidates.append((await self._peer_recency(peer_id), peer_id))
            if not candidates:
                return 0

            candidates.sort(key=lambda item: item[0])
            victims = [peer_id for _, peer_id in candidates[:overflow]]
            await self._delete_peers_from_datastore(victims)
            if victims:
                logger.info(
                    "Peerstore datastore trimmed: removed %d stale peers (limit %d)",
                    len(victims),
                    cap,
                )
            return len(victims)

    async def _maybe_prune_datastore(self) -> None:
        """Periodically bound the persisted peer set."""
        self._writes_since_prune += 1
        if self._writes_since_prune < self.DATASTORE_PRUNE_INTERVAL:
            return
        if len(self.peer_data_map) < self.max_cached_peers:
            return
        self._writes_since_prune = 0
        try:
            await self.enforce_datastore_limit_async(
                max_deletes=self.DATASTORE_PRUNE_BATCH
            )
        except Exception:
            logger.exception("Peerstore datastore trim failed")

    async def _save_peer_data(self, peer_id: ID, peer_data: PeerData) -> None:
        """
        Save peer data to datastore.

        :param peer_id: The peer ID to save data for
        :param peer_data: The peer data to save
        :raises PeerStoreError: If saving to datastore fails
        :raises SerializationError: If serialization fails
        """
        try:
            # Save addresses
            if peer_data.addrs:
                addr_key = self._get_addr_key(peer_id)
                addr_data = serialize_addresses(peer_data.addrs)
                await self.datastore.put(addr_key, addr_data)

            # Save keys as serialized metadata (pubkey/privkey protobuf bytes)
            if peer_data.pubkey or peer_data.privkey:
                key_key = self._get_key_key(peer_id)
                keys_metadata = {}
                if peer_data.pubkey:
                    keys_metadata["pubkey"] = peer_data.pubkey.serialize()
                if peer_data.privkey:
                    keys_metadata["privkey"] = peer_data.privkey.serialize()
                key_data = serialize_metadata(keys_metadata)
                await self.datastore.put(key_key, key_data)

            # Save metadata
            if peer_data.metadata:
                metadata_key = self._get_metadata_key(peer_id)
                metadata_data = serialize_metadata(peer_data.metadata)
                await self.datastore.put(metadata_key, metadata_data)

            # Save protocols
            if peer_data.protocols:
                protocol_key = self._get_protocol_key(peer_id)
                protocol_data = serialize_protocols(peer_data.protocols)
                await self.datastore.put(protocol_key, protocol_data)

            # Save latency data if available
            if hasattr(peer_data, "latmap") and peer_data.latmap > 0:
                latency_key = self._get_latency_key(peer_id)
                # Convert seconds to nanoseconds for storage
                latency_ns = int(peer_data.latmap * 1_000_000_000)
                latency_data = serialize_latency(latency_ns)
                await self.datastore.put(latency_key, latency_data)

            # Persist TTL/last-seen so recency survives a restart.
            await self.datastore.put(
                self._get_additional_key(peer_id),
                serialize_metadata(
                    {"ttl": peer_data.ttl, "last_identified": peer_data.last_identified}
                ),
            )

            # Conditionally sync to ensure data is persisted
            await self._maybe_sync()
            await self._maybe_prune_datastore()

        except SerializationError:
            raise
        except Exception as e:
            raise PeerStoreError(f"Failed to save peer data for {peer_id}") from e

    async def _maybe_sync(self) -> None:
        """
        Conditionally sync the datastore based on configuration.

        :raises PeerStoreError: If sync operation fails
        """
        if not self.auto_sync:
            return

        current_time = time.time()
        if current_time - self._last_sync >= self.sync_interval:
            try:
                await self.datastore.sync(b"")
                self._last_sync = current_time
                self._pending_sync = False
            except Exception as e:
                raise PeerStoreError("Failed to sync datastore") from e
        else:
            self._pending_sync = True

    async def _load_peer_record(self, peer_id: ID) -> PeerRecordState | None:
        """
        Load peer record from datastore.

        :param peer_id: The peer ID to load record for
        :return: PeerRecordState if found, None otherwise
        :raises PeerStoreError: If loading fails unexpectedly
        """
        async with self._lock:
            if peer_id not in self.peer_record_map:
                try:
                    record_key = self._get_peer_record_key(peer_id)
                    record_data = await self.datastore.get(record_key)
                    if record_data:
                        record_state = deserialize_record_state(record_data)
                        self.peer_record_map[peer_id] = record_state
                        return record_state
                except (SerializationError, KeyError, ValueError) as e:
                    logger.error(f"Failed to load peer record for {peer_id}: {e}")
                except Exception:
                    logger.exception(
                        f"Unexpected error loading peer record for {peer_id}"
                    )
            return self.peer_record_map.get(peer_id)

    async def _save_peer_record(
        self, peer_id: ID, record_state: PeerRecordState
    ) -> None:
        """
        Save peer record to datastore.

        :param peer_id: The peer ID to save record for
        :param record_state: The record state to save
        :raises PeerStoreError: If saving to datastore fails
        :raises SerializationError: If serialization fails
        """
        try:
            record_key = self._get_peer_record_key(peer_id)
            record_data = serialize_record_state(record_state)
            await self.datastore.put(record_key, record_data)
            self.peer_record_map[peer_id] = record_state
            await self._maybe_sync()
        except SerializationError:
            raise
        except Exception as e:
            raise PeerStoreError(f"Failed to save peer record for {peer_id}") from e

    async def _load_local_record(self) -> None:
        """
        Load local peer record from datastore.

        :raises PeerStoreError: If loading fails unexpectedly
        """
        try:
            local_data = await self.datastore.get(self.LOCAL_RECORD_KEY)
            if local_data:
                self.local_peer_record = deserialize_envelope(local_data)
        except (SerializationError, KeyError, ValueError) as e:
            logger.error(f"Failed to load local peer record: {e}")
        except Exception:
            logger.exception("Unexpected error loading local peer record")

    async def _save_local_record(self, envelope: Envelope) -> None:
        """
        Save local peer record to datastore.

        :param envelope: The envelope to save
        :raises PeerStoreError: If saving to datastore fails
        :raises SerializationError: If serialization fails
        """
        try:
            envelope_data = serialize_envelope(envelope)
            await self.datastore.put(self.LOCAL_RECORD_KEY, envelope_data)
            self.local_peer_record = envelope
            await self._maybe_sync()
        except SerializationError:
            raise
        except Exception as e:
            raise PeerStoreError("Failed to save local peer record") from e

    async def _clear_peerdata_from_datastore(self, peer_id: ID) -> None:
        """Clear peer data from datastore."""
        try:
            keys_to_delete = [
                self._get_addr_key(peer_id),
                self._get_key_key(peer_id),
                self._get_metadata_key(peer_id),
                self._get_protocol_key(peer_id),
                self._get_peer_record_key(peer_id),
                self._get_additional_key(peer_id),
                self._get_latency_key(peer_id),
            ]
            for key in keys_to_delete:
                await self.datastore.delete(key)
            await self.datastore.sync(b"")
        except Exception as e:
            logger.error(f"Failed to clear peer data from datastore for {peer_id}: {e}")

    # --------CORE ASYNC PEERSTORE METHODS--------

    async def get_local_record_async(self) -> Envelope | None:
        """Get the local-signed-record wrapped in Envelope"""
        if self.local_peer_record is None:
            await self._load_local_record()
        return self.local_peer_record

    async def set_local_record_async(self, envelope: Envelope) -> None:
        """Set the local-signed-record wrapped in Envelope"""
        await self._save_local_record(envelope)

    async def peer_info_async(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """
        peer_data = await self._load_peer_data(peer_id)
        if peer_data.is_expired():
            peer_data.clear_addrs()
            await self._save_peer_data(peer_id, peer_data)
        return PeerInfo(peer_id, peer_data.get_addrs())

    async def peer_ids_async(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        # Get all peer IDs from datastore by querying all prefixes
        peer_ids = set()

        try:
            # Query all address keys to find peer IDs
            for key, _ in self.datastore.query(self.ADDR_PREFIX):
                if key.startswith(self.ADDR_PREFIX):
                    peer_id_bytes = key[len(self.ADDR_PREFIX) :]
                    try:
                        peer_id = ID(peer_id_bytes)
                        peer_ids.add(peer_id)
                    except Exception:
                        continue  # Skip invalid peer IDs
        except Exception as e:
            logger.error(f"Failed to query peer IDs: {e}")

        # Also include any peer IDs from memory cache
        peer_ids.update(self.peer_data_map.keys())

        return list(peer_ids)

    async def clear_peerdata_async(self, peer_id: ID) -> None:
        """Clears all data associated with the given peer_id."""
        async with self._lock:
            # Remove from memory
            if peer_id in self.peer_data_map:
                del self.peer_data_map[peer_id]

            # Clear peer records from memory
            if peer_id in self.peer_record_map:
                del self.peer_record_map[peer_id]

            # Clear from datastore
            await self._clear_peerdata_from_datastore(peer_id)

    async def valid_peer_ids_async(self) -> list[ID]:
        """
        :return: all of the valid peer IDs stored in peer store
        """
        valid_peer_ids: list[ID] = []
        all_peer_ids = await self.peer_ids_async()

        for peer_id in all_peer_ids:
            try:
                peer_data = await self._load_peer_data(peer_id)
                if not peer_data.is_expired():
                    valid_peer_ids.append(peer_id)
                else:
                    peer_data.clear_addrs()
                    await self._save_peer_data(peer_id, peer_data)
            except Exception as e:
                logger.error(f"Error checking validity of peer {peer_id}: {e}")

        return valid_peer_ids

    async def _enforce_record_limit(self) -> None:
        """Enforce maximum number of stored records."""
        if len(self.peer_record_map) > self.max_records:
            # Remove oldest records based on sequence number
            sorted_records = sorted(
                self.peer_record_map.items(), key=lambda x: x[1].seq
            )
            records_to_remove = len(self.peer_record_map) - self.max_records
            for peer_id, _ in sorted_records[:records_to_remove]:
                # Remove from memory and datastore
                del self.peer_record_map[peer_id]
                try:
                    record_key = self._get_peer_record_key(peer_id)
                    await self.datastore.delete(record_key)
                except Exception as e:
                    logger.error(f"Failed to delete peer record for {peer_id}: {e}")

    async def start_cleanup_task(self, cleanup_interval: int = 3600) -> None:
        """Start periodic cleanup of expired peer records and addresses."""
        while True:
            await trio.sleep(cleanup_interval)
            await self._cleanup_expired_records()

    async def _cleanup_expired_records(self) -> None:
        """Remove expired peer records and addresses"""
        all_peer_ids = await self.peer_ids_async()
        expired_peers = []

        for peer_id in all_peer_ids:
            try:
                peer_data = await self._load_peer_data(peer_id)
                if peer_data.is_expired():
                    expired_peers.append(peer_id)
            except Exception as e:
                logger.error(f"Error checking expiry for peer {peer_id}: {e}")

        for peer_id in expired_peers:
            await self.maybe_delete_peer_record_async(peer_id)
            await self.clear_peerdata_async(peer_id)

        await self._enforce_record_limit()

    # --------PROTO-BOOK--------

    async def get_protocols_async(self, peer_id: ID) -> list[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """
        peer_data = await self._load_peer_data(peer_id)
        return peer_data.get_protocols()

    async def add_protocols_async(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.add_protocols(list(protocols))
        await self._save_peer_data(peer_id, peer_data)

    async def set_protocols_async(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.set_protocols(list(protocols))
        await self._save_peer_data(peer_id, peer_data)

    async def remove_protocols_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> None:
        """
        :param peer_id: peer ID to get info for
        :param protocols: unsupported protocols to remove
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.remove_protocols(protocols)
        await self._save_peer_data(peer_id, peer_data)

    async def supports_protocols_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> list[str]:
        """
        :return: all of the peer IDs stored in peer store
        """
        peer_data = await self._load_peer_data(peer_id)
        return peer_data.supports_protocols(protocols)

    async def first_supported_protocol_async(
        self, peer_id: ID, protocols: Sequence[str]
    ) -> str:
        peer_data = await self._load_peer_data(peer_id)
        return peer_data.first_supported_protocol(protocols)

    async def clear_protocol_data_async(self, peer_id: ID) -> None:
        """Clears protocol data"""
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_protocol_data()
        await self._save_peer_data(peer_id, peer_data)

    # ------METADATA---------

    async def get_async(self, peer_id: ID, key: str) -> MetadataValue:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """
        peer_data = await self._load_peer_data(peer_id)
        try:
            return peer_data.get_metadata(key)
        except PeerDataError as error:
            raise PeerStoreError() from error

    async def put_async(self, peer_id: ID, key: str, val: MetadataValue) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.put_metadata(key, val)
        await self._save_peer_data(peer_id, peer_data)

    async def clear_metadata_async(self, peer_id: ID) -> None:
        """Clears metadata"""
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_metadata()
        await self._save_peer_data(peer_id, peer_data)

    # -----CERT-ADDR-BOOK-----

    async def maybe_delete_peer_record_async(self, peer_id: ID) -> None:
        """
        Delete the signed peer record for a peer if it has no known
        (non-expired) addresses.
        """
        peer_data = await self._load_peer_data(peer_id)
        if not peer_data.get_addrs() and peer_id in self.peer_record_map:
            # Remove from memory and datastore
            del self.peer_record_map[peer_id]
            try:
                record_key = self._get_peer_record_key(peer_id)
                await self.datastore.delete(record_key)
                await self.datastore.sync(b"")
            except Exception as e:
                logger.error(f"Failed to delete peer record for {peer_id}: {e}")

    async def consume_peer_record_async(self, envelope: Envelope, ttl: int) -> bool:
        """
        Accept and store a signed PeerRecord, unless it's older than
        the one already stored.
        """
        if not _peer_record_signer_matches(envelope):
            return False

        record = envelope.record()
        peer_id = record.peer_id

        # Check if we have an existing record
        existing = await self._load_peer_record(peer_id)
        if existing and existing.seq > record.seq:
            return False

        # Store the new record
        new_addrs = set(record.addrs)
        record_state = PeerRecordState(envelope, record.seq)
        await self._save_peer_record(peer_id, record_state)

        # Update peer data
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_addrs()
        peer_data.add_addrs(list(new_addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()
        await self._save_peer_data(peer_id, peer_data)

        return True

    async def get_peer_record_async(self, peer_id: ID) -> Envelope | None:
        """
        Retrieve the most recent signed PeerRecord `Envelope` for a peer, if it exists
        and is still relevant.
        """
        peer_data = await self._load_peer_data(peer_id)
        if not peer_data.is_expired() and peer_data.get_addrs():
            record_state = await self._load_peer_record(peer_id)
            if record_state is not None:
                return record_state.envelope
        return None

    # -------ADDR-BOOK--------

    async def add_addr_async(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """
        await self.add_addrs_async(peer_id, [addr], ttl)

    async def add_addrs_async(
        self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int
    ) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.add_addrs(list(addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()
        await self._save_peer_data(peer_id, peer_data)

        # Notify address stream listeners
        if peer_id in self.addr_update_channels:
            for addr in addrs:
                try:
                    self.addr_update_channels[peer_id].send_nowait(addr)
                except trio.WouldBlock:
                    # Channel is full, skip this address update
                    # This is not a critical error as the address is already stored
                    pass

        await self.maybe_delete_peer_record_async(peer_id)

    async def addrs_async(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs of a valid peer.
        :raise PeerStoreError: if peer ID not found
        """
        peer_data = await self._load_peer_data(peer_id)
        if not peer_data.is_expired():
            return peer_data.get_addrs()
        else:
            peer_data.clear_addrs()
            await self._save_peer_data(peer_id, peer_data)
            raise PeerStoreError("peer ID is expired")

    async def clear_addrs_async(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_addrs()
        await self._save_peer_data(peer_id, peer_data)
        await self.maybe_delete_peer_record_async(peer_id)

    async def peers_with_addrs_async(self) -> list[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """
        output: list[ID] = []
        all_peer_ids = await self.peer_ids_async()

        for peer_id in all_peer_ids:
            try:
                peer_data = await self._load_peer_data(peer_id)
                if len(peer_data.get_addrs()) >= 1:
                    if not peer_data.is_expired():
                        output.append(peer_id)
                    else:
                        peer_data.clear_addrs()
                        await self._save_peer_data(peer_id, peer_data)
            except Exception as e:
                logger.error(f"Error checking addresses for peer {peer_id}: {e}")

        return output

    async def addr_stream_async(self, peer_id: ID) -> AsyncIterable[Multiaddr]:  # type: ignore[override]
        """
        Returns an async stream of newly added addresses for the given peer.
        """
        send: MemorySendChannel[Multiaddr]
        receive: MemoryReceiveChannel[Multiaddr]

        send, receive = trio.open_memory_channel(0)
        self.addr_update_channels[peer_id] = send

        try:
            async for addr in receive:
                yield addr
        finally:
            # The subscriber is gone (finished, cancelled or errored). Drop
            # the channel so it cannot retain the peer entry or pending
            # addresses for the process lifetime.
            if self.addr_update_channels.get(peer_id) is send:
                self.addr_update_channels.pop(peer_id, None)
            send.close()
            receive.close()

    # -------KEY-BOOK---------

    async def add_pubkey_async(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID and pubkey does not match
        """
        if ID.from_pubkey(pubkey) != peer_id:
            raise PeerStoreError("peer ID and pubkey does not match")
        peer_data = await self._load_peer_data(peer_id)
        peer_data.add_pubkey(pubkey)
        await self._save_peer_data(peer_id, peer_data)

    async def pubkey_async(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID or peer pubkey not found
        """
        peer_data = await self._load_peer_data(peer_id)
        try:
            return peer_data.get_pubkey()
        except PeerDataError as e:
            raise PeerStoreError("peer pubkey not found") from e

    async def add_privkey_async(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        if ID.from_pubkey(privkey.get_public_key()) != peer_id:
            raise PeerStoreError("peer ID and privkey does not match")
        peer_data = await self._load_peer_data(peer_id)
        peer_data.add_privkey(privkey)
        await self._save_peer_data(peer_id, peer_data)

    async def privkey_async(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        peer_data = await self._load_peer_data(peer_id)
        try:
            return peer_data.get_privkey()
        except PeerDataError as e:
            raise PeerStoreError("peer privkey not found") from e

    async def add_key_pair_async(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        """
        await self.add_pubkey_async(peer_id, key_pair.public_key)
        await self.add_privkey_async(peer_id, key_pair.private_key)

    async def peer_with_keys_async(self) -> list[ID]:
        """Returns the peer_ids for which keys are stored"""
        peer_ids_with_keys: list[ID] = []
        all_peer_ids = await self.peer_ids_async()

        for peer_id in all_peer_ids:
            try:
                peer_data = await self._load_peer_data(peer_id)
                if peer_data.pubkey is not None:
                    peer_ids_with_keys.append(peer_id)
            except Exception as e:
                logger.error(f"Error checking keys for peer {peer_id}: {e}")

        return peer_ids_with_keys

    async def clear_keydata_async(self, peer_id: ID) -> None:
        """Clears the keys of the peer"""
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_keydata()
        await self._save_peer_data(peer_id, peer_data)

    # --------METRICS--------

    async def record_latency_async(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new latency measurement for the given peer
        using Exponentially Weighted Moving Average (EWMA)
        """
        peer_data = await self._load_peer_data(peer_id)
        peer_data.record_latency(RTT)
        await self._save_peer_data(peer_id, peer_data)

    async def latency_EWMA_async(self, peer_id: ID) -> float:
        """
        :param peer_id: peer ID to get private key for
        :return: The latency EWMA value for that peer
        """
        peer_data = await self._load_peer_data(peer_id)
        return peer_data.latency_EWMA()

    async def clear_metrics_async(self, peer_id: ID) -> None:
        """Clear the latency metrics"""
        peer_data = await self._load_peer_data(peer_id)
        peer_data.clear_metrics()
        await self._save_peer_data(peer_id, peer_data)

    async def close_async(self) -> None:
        """Close the persistent peerstore and underlying datastore."""
        async with self._lock:
            # Close the datastore
            if hasattr(self.datastore, "close"):
                await self.datastore.close()

            # Clear memory caches
            self.peer_data_map.clear()
            self.peer_record_map.clear()
            self.local_peer_record = None

    async def __aenter__(self) -> "AsyncPersistentPeerStore":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close_async()
