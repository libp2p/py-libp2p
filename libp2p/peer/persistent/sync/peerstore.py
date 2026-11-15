"""
Synchronous persistent peerstore implementation for py-libp2p.

This module provides a synchronous persistent peerstore that stores peer data
in a datastore backend, similar to the pstoreds implementation in go-libp2p.
All operations are purely synchronous without any async/await.
"""

from collections import OrderedDict
from collections.abc import Sequence
import logging
import threading
import time

from multiaddr import Multiaddr

from libp2p.abc import IPeerStore
from libp2p.crypto.exceptions import CryptographyError
from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey
from libp2p.crypto.serialization import (
    deserialize_private_key,
    deserialize_public_key,
)
from libp2p.custom_types import MetadataValue
from libp2p.peer.envelope import Envelope
from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData, PeerDataError
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import (
    PeerRecordState,
    PeerStoreError,
    _peer_record_signer_matches,
)

from ..datastore.base_sync import IDatastoreSync
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


class SyncPersistentPeerStore(IPeerStore):
    """
    Synchronous persistent peerstore implementation that stores peer data
    in a datastore backend.

    This implementation follows the IPeerStore interface with purely
    synchronous operations. All data is persisted immediately to the datastore
    backend without background threads or async operations, similar to the
    pstoreds implementation in go-libp2p.
    """

    def __init__(
        self,
        datastore: IDatastoreSync,
        max_records: int = 10000,
        sync_interval: float = 1.0,
        auto_sync: bool = True,
        max_cached_peers: int = 1000,
        max_stored_peers: int | None = None,
    ) -> None:
        """
        Initialize synchronous persistent peerstore.

        Args:
            datastore: The synchronous datastore backend to use for persistence
            max_records: Maximum number of peer records to store
            sync_interval: Minimum interval between sync operations (seconds)
            auto_sync: Whether to automatically sync after writes
            max_cached_peers: Maximum number of peer data objects to cache in memory
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
        self.sync_interval = sync_interval
        self.auto_sync = auto_sync
        self.max_cached_peers = max_cached_peers
        # A cache cap alone does not bound the datastore: evicted peers keep
        # their rows forever, so every peer ever seen grows the database.
        self.max_stored_peers = (
            max_records if max_stored_peers is None else max_stored_peers
        )
        self._writes_since_prune = 0
        self.local_peer_id: ID | None = None
        self._last_sync = time.time()
        self._pending_sync = False

        # In-memory LRU caches for frequently accessed data
        self.peer_data_map: OrderedDict[ID, PeerData] = OrderedDict()
        self.peer_record_map: OrderedDict[ID, PeerRecordState] = OrderedDict()
        self.local_peer_record: Envelope | None = None

        # Thread safety for concurrent access
        self._lock = threading.RLock()

        # Key prefixes for different data types
        self.ADDR_PREFIX = b"addr:"
        self.KEY_PREFIX = b"key:"
        self.METADATA_PREFIX = b"metadata:"
        self.PROTOCOL_PREFIX = b"protocol:"
        self.PEER_RECORD_PREFIX = b"peer_record:"
        self.LOCAL_RECORD_KEY = b"local_record"

        # Load local record on initialization
        self._load_local_record()

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

    def _enforce_peer_data_cache_limit(self) -> None:
        """
        Evict least-recently used peer records from memory if exceeding capacity.
        The local peer identity is permanent and NEVER evicted.
        """
        while len(self.peer_data_map) > self.max_cached_peers:
            evicted = False
            for pid, data in list(self.peer_data_map.items()):
                if pid == self.local_peer_id or (
                    data is not None and data.privkey is not None
                ):
                    # Move local peer to MRU position so it isn't repeatedly checked
                    self.peer_data_map.move_to_end(pid)
                    continue
                del self.peer_data_map[pid]
                evicted = True
                break
            if not evicted:
                break

    def _enforce_peer_record_cache_limit(self) -> None:
        """Evict least-recently used peer records from memory cache."""
        while len(self.peer_record_map) > self.max_cached_peers:
            self.peer_record_map.popitem(last=False)

    # --------BOUNDED PERSISTED PEER SET--------

    # Every N writes (while the cache is saturated) the datastore is checked
    # against max_stored_peers.  The check is O(stored peers), so running it
    # rarely keeps the amortized cost negligible.
    DATASTORE_PRUNE_INTERVAL = 512
    # Peers removed per periodic check.  Large legacy databases are drained
    # by the startup call with no per-call budget.
    DATASTORE_PRUNE_BATCH = 512

    def _count_stored_peers(self) -> int:
        """Number of peers with a persisted address record."""
        try:
            counter = getattr(self.datastore, "count", None)
            if counter is not None:
                return int(counter(self.ADDR_PREFIX))
            return sum(1 for _ in self.datastore.query(self.ADDR_PREFIX))
        except Exception as e:
            logger.error(f"Failed to count stored peers: {e}")
            return 0

    def _iter_stored_peer_ids(self) -> list[ID]:
        """Peer IDs that currently have a persisted address record."""
        peer_ids: list[ID] = []
        prefix_len = len(self.ADDR_PREFIX)
        try:
            if hasattr(self.datastore, "query_keys"):
                key_iter = self.datastore.query_keys(self.ADDR_PREFIX)
            else:
                key_iter = (k for k, _ in self.datastore.query(self.ADDR_PREFIX))
            for key in key_iter:
                if not key.startswith(self.ADDR_PREFIX):
                    continue
                try:
                    peer_ids.append(ID(key[prefix_len:]))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to enumerate stored peers: {e}")
        return peer_ids

    def _peer_recency(self, peer_id: ID) -> int:
        """Best-effort last-seen timestamp for a persisted peer."""
        try:
            data = self.datastore.get(self._get_additional_key(peer_id))
            if data:
                return int(deserialize_metadata(data).get("last_identified", 0))
        except Exception:
            pass
        return 0

    def _delete_peers_from_datastore(self, peer_ids: Sequence[ID]) -> None:
        """Delete all persisted rows for the given peers in one transaction."""
        if not peer_ids:
            return
        try:
            batch_factory = getattr(self.datastore, "batch", None)
            batch = batch_factory() if batch_factory is not None else None
            for peer_id in peer_ids:
                for key in (
                    self._get_addr_key(peer_id),
                    self._get_key_key(peer_id),
                    self._get_metadata_key(peer_id),
                    self._get_protocol_key(peer_id),
                    self._get_peer_record_key(peer_id),
                    self._get_additional_key(peer_id),
                    self._get_latency_key(peer_id),
                ):
                    if batch is not None:
                        batch.delete(key)
                    else:
                        self.datastore.delete(key)
                if batch is None:
                    self.peer_data_map.pop(peer_id, None)
                    self.peer_record_map.pop(peer_id, None)
            if batch is not None:
                batch.commit()
                for peer_id in peer_ids:
                    self.peer_data_map.pop(peer_id, None)
                    self.peer_record_map.pop(peer_id, None)
            self.datastore.sync(b"")
        except Exception as e:
            logger.error(f"Failed to delete {len(peer_ids)} peers from datastore: {e}")

    def enforce_datastore_limit(
        self,
        limit: int | None = None,
        max_deletes: int | None = None,
    ) -> int:
        """
        Trim the persisted peer set down to ``limit`` peers.

        Evicting a peer from the in-memory cache does not remove its rows, so
        without this the datastore retains one (potentially large) record for
        every peer the node has ever seen.  Peers that are currently cached
        are never candidates: they are local, connected, or actively used.
        Among the rest, the least recently seen peers are removed first.

        Args:
            limit: Maximum number of stored peers (defaults to
                ``max_stored_peers``).
            max_deletes: Optional cap on peers removed by this call, so a
                periodic check stays cheap.  ``None`` drains the whole
                overflow.

        Returns:
            The number of peers removed.

        """
        cap = self.max_stored_peers if limit is None else limit
        with self._lock:
            overflow = self._count_stored_peers() - cap
            if overflow <= 0:
                return 0
            if max_deletes is not None:
                overflow = min(overflow, max_deletes)

            cached = set(self.peer_data_map)
            candidates: list[tuple[int, ID]] = []
            for peer_id in self._iter_stored_peer_ids():
                if peer_id == self.local_peer_id or peer_id in cached:
                    continue
                candidates.append((self._peer_recency(peer_id), peer_id))
            if not candidates:
                return 0

            candidates.sort(key=lambda item: item[0])
            victims = [peer_id for _, peer_id in candidates[:overflow]]
            self._delete_peers_from_datastore(victims)
            if victims:
                logger.info(
                    "Peerstore datastore trimmed: removed %d stale peers (limit %d)",
                    len(victims),
                    cap,
                )
            return len(victims)

    def _maybe_prune_datastore(self) -> None:
        """Periodically bound the persisted peer set (see enforce_datastore_limit)."""
        self._writes_since_prune += 1
        if self._writes_since_prune < self.DATASTORE_PRUNE_INTERVAL:
            return
        # Growth only happens once writes start displacing cached peers.
        if len(self.peer_data_map) < self.max_cached_peers:
            return
        self._writes_since_prune = 0
        try:
            self.enforce_datastore_limit(max_deletes=self.DATASTORE_PRUNE_BATCH)
        except Exception:
            logger.exception("Peerstore datastore trim failed")

    def _load_peer_data(self, peer_id: ID) -> PeerData:
        """Load peer data from datastore, creating if not exists."""
        with self._lock:
            if peer_id in self.peer_data_map:
                self.peer_data_map.move_to_end(peer_id)
                return self.peer_data_map[peer_id]

            peer_data = PeerData()

            try:
                # Load addresses
                addr_key = self._get_addr_key(peer_id)
                addr_data = self.datastore.get(addr_key)
                if addr_data:
                    peer_data.addrs = deserialize_addresses(addr_data)

                # Load keys
                key_key = self._get_key_key(peer_id)
                key_data = self.datastore.get(key_key)
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
                metadata_data = self.datastore.get(metadata_key)
                if metadata_data:
                    metadata_bytes = deserialize_metadata(metadata_data)
                    # Convert bytes back to appropriate types
                    peer_data.metadata = {
                        k: v.decode("utf-8") if isinstance(v, bytes) else v
                        for k, v in metadata_bytes.items()
                    }

                # Load protocols
                protocol_key = self._get_protocol_key(peer_id)
                protocol_data = self.datastore.get(protocol_key)
                if protocol_data:
                    peer_data.protocols = deserialize_protocols(protocol_data)

                # Load latency data
                latency_key = self._get_latency_key(peer_id)
                latency_data = self.datastore.get(latency_key)
                if latency_data:
                    latency_ns = deserialize_latency(latency_data)
                    # Convert nanoseconds back to seconds for latmap
                    peer_data.latmap = latency_ns / 1_000_000_000

                # LRU eviction must not turn a finite address TTL into the
                # PeerData default (zero means permanent). Older databases
                # lack this optional record and retain their legacy behavior.
                additional_data = self.datastore.get(self._get_additional_key(peer_id))
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
                logger.exception(f"Unexpected error loading peer data for {peer_id}")
                # Continue with empty peer data

            if peer_data.privkey is not None:
                self.local_peer_id = peer_id

            self.peer_data_map[peer_id] = peer_data
            self._enforce_peer_data_cache_limit()
            return peer_data

    def _persist_field(self, key: bytes, value: bytes | None) -> None:
        """Persist deletion too, without rewriting unchanged peer fields."""
        previous = self.datastore.get(key)
        if value is None:
            if previous is not None:
                self.datastore.delete(key)
        elif previous != value:
            self.datastore.put(key, value)

    def _save_peer_data(self, peer_id: ID, peer_data: PeerData) -> None:
        """
        Save peer data to datastore.

        :param peer_id: The peer ID to save data for
        :param peer_data: The peer data to save
        :raises PeerStoreError: If saving to datastore fails
        :raises SerializationError: If serialization fails
        """
        try:
            # Save addresses
            self._persist_field(
                self._get_addr_key(peer_id),
                serialize_addresses(peer_data.addrs) if peer_data.addrs else None,
            )

            self._persist_field(
                self._get_additional_key(peer_id),
                serialize_metadata(
                    {"ttl": peer_data.ttl, "last_identified": peer_data.last_identified}
                ),
            )

            # Save keys as serialized metadata (pubkey/privkey protobuf bytes)
            if peer_data.pubkey or peer_data.privkey:
                key_key = self._get_key_key(peer_id)
                keys_metadata = {}
                if peer_data.pubkey:
                    keys_metadata["pubkey"] = peer_data.pubkey.serialize()
                if peer_data.privkey:
                    keys_metadata["privkey"] = peer_data.privkey.serialize()
                key_data = serialize_metadata(keys_metadata)
                self.datastore.put(key_key, key_data)

            # Save metadata
            self._persist_field(
                self._get_metadata_key(peer_id),
                serialize_metadata(peer_data.metadata) if peer_data.metadata else None,
            )

            # Save protocols
            self._persist_field(
                self._get_protocol_key(peer_id),
                serialize_protocols(peer_data.protocols)
                if peer_data.protocols
                else None,
            )

            # Save latency data if available
            if hasattr(peer_data, "latmap") and peer_data.latmap > 0:
                latency_key = self._get_latency_key(peer_id)
                # Convert seconds to nanoseconds for storage
                latency_ns = int(peer_data.latmap * 1_000_000_000)
                latency_data = serialize_latency(latency_ns)
                self.datastore.put(latency_key, latency_data)

            # Conditionally sync to ensure data is persisted
            self._maybe_sync()
            self._maybe_prune_datastore()

        except SerializationError:
            raise
        except Exception as e:
            raise PeerStoreError(f"Failed to save peer data for {peer_id}") from e

    def _maybe_sync(self) -> None:
        """
        Conditionally sync the datastore based on configuration.

        :raises PeerStoreError: If sync operation fails
        """
        if not self.auto_sync:
            return

        current_time = time.time()
        if current_time - self._last_sync >= self.sync_interval:
            try:
                self.datastore.sync(b"")
                self._last_sync = current_time
                self._pending_sync = False
            except Exception as e:
                raise PeerStoreError("Failed to sync datastore") from e
        else:
            self._pending_sync = True

    def _load_peer_record(self, peer_id: ID) -> PeerRecordState | None:
        """Load peer record from datastore."""
        with self._lock:
            if peer_id in self.peer_record_map:
                self.peer_record_map.move_to_end(peer_id)
                return self.peer_record_map[peer_id]
            try:
                record_key = self._get_peer_record_key(peer_id)
                record_data = self.datastore.get(record_key)
                if record_data:
                    record_state = deserialize_record_state(record_data)
                    self.peer_record_map[peer_id] = record_state
                    self._enforce_peer_record_cache_limit()
                    return record_state
            except (SerializationError, KeyError, ValueError) as e:
                logger.error(f"Failed to load peer record for {peer_id}: {e}")
            except Exception:
                logger.exception(f"Unexpected error loading peer record for {peer_id}")
            return None

    def _save_peer_record(self, peer_id: ID, record_state: PeerRecordState) -> None:
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
            self.datastore.put(record_key, record_data)
            self.peer_record_map[peer_id] = record_state
            self.peer_record_map.move_to_end(peer_id)
            self._enforce_peer_record_cache_limit()
            self._maybe_sync()
        except Exception as e:
            raise PeerStoreError(f"Failed to save peer record for {peer_id}") from e

    def _load_local_record(self) -> None:
        """
        Load local peer record from datastore.

        :raises PeerStoreError: If loading fails unexpectedly
        """
        try:
            local_data = self.datastore.get(self.LOCAL_RECORD_KEY)
            if local_data:
                self.local_peer_record = deserialize_envelope(local_data)
        except (SerializationError, KeyError, ValueError) as e:
            logger.error(f"Failed to load local peer record: {e}")
        except Exception:
            logger.exception("Unexpected error loading local peer record")

    def _save_local_record(self, envelope: Envelope) -> None:
        """
        Save local peer record to datastore.

        :param envelope: The envelope to save
        :raises PeerStoreError: If saving to datastore fails
        :raises SerializationError: If serialization fails
        """
        try:
            envelope_data = serialize_envelope(envelope)
            self.datastore.put(self.LOCAL_RECORD_KEY, envelope_data)
            self.local_peer_record = envelope
            self._maybe_sync()
        except Exception as e:
            raise PeerStoreError("Failed to save local peer record") from e

    def _clear_peerdata_from_datastore(self, peer_id: ID) -> None:
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
                self.datastore.delete(key)
            self.datastore.sync(b"")
        except Exception as e:
            logger.error(f"Failed to clear peer data from datastore for {peer_id}: {e}")

    # --------CORE PEERSTORE METHODS--------

    def get_local_record(self) -> Envelope | None:
        """Get the local-signed-record wrapped in Envelope"""
        return self.local_peer_record

    def set_local_record(self, envelope: Envelope) -> None:
        """Set the local-signed-record wrapped in Envelope"""
        self._save_local_record(envelope)

    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """
        peer_data = self._load_peer_data(peer_id)
        if peer_data.is_expired():
            peer_data.clear_addrs()
            self._save_peer_data(peer_id, peer_data)
        return PeerInfo(peer_id, peer_data.get_addrs())

    def count_peers(self) -> int:
        """Return the number of peers stored without materializing them."""
        if hasattr(self.datastore, "count"):
            return self.datastore.count(self.ADDR_PREFIX)
        return len(self.peer_data_map)

    def peer_ids(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        # Get all peer IDs from datastore by querying address keys
        peer_ids = set()

        try:
            # Query only address keys (not values) to find peer IDs
            key_iter = (
                self.datastore.query_keys(self.ADDR_PREFIX)
                if hasattr(self.datastore, "query_keys")
                else (k for k, _ in self.datastore.query(self.ADDR_PREFIX))
            )
            for key in key_iter:
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

    def sample_peer_ids(self, limit: int = 150, random_order: bool = True) -> list[ID]:
        """
        Return a bounded sample of peer IDs from the datastore and memory cache.
        Does not perform a full table scan or deserialize value blobs.
        """
        sampled_peer_ids: set[ID] = set()

        # Check memory cache first
        with self._lock:
            for pid in list(self.peer_data_map.keys()):
                if self.local_peer_id and pid == self.local_peer_id:
                    continue
                sampled_peer_ids.add(pid)
                if len(sampled_peer_ids) >= limit:
                    break

        if len(sampled_peer_ids) >= limit:
            return list(sampled_peer_ids)

        needed = limit - len(sampled_peer_ids)
        try:
            if hasattr(self.datastore, "query_keys"):
                key_iter = self.datastore.query_keys(
                    self.ADDR_PREFIX, limit=needed * 3, random_order=random_order
                )
            else:
                key_iter = (k for k, _ in self.datastore.query(self.ADDR_PREFIX))

            prefix_len = len(self.ADDR_PREFIX)
            for key in key_iter:
                if key.startswith(self.ADDR_PREFIX):
                    peer_id_bytes = key[prefix_len:]
                    try:
                        peer_id = ID(peer_id_bytes)
                        if self.local_peer_id and peer_id == self.local_peer_id:
                            continue
                        sampled_peer_ids.add(peer_id)
                        if len(sampled_peer_ids) >= limit:
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"Failed to sample peer IDs: {e}")

        return list(sampled_peer_ids)

    def has_peer(self, peer_id: ID) -> bool:
        """
        Return True if the peer is known to this store (memory or datastore).

        O(1) in-memory lookup, falling back to a single datastore key check —
        never a full ``peer_ids()`` scan (which reconstructs and hashes every
        peer and was saturating CPU on hot paths with large peerstores).
        """
        if peer_id in self.peer_data_map:
            return True
        try:
            return bool(self.datastore.get(self._get_addr_key(peer_id)))
        except Exception:
            return False

    def clear_peerdata(self, peer_id: ID) -> None:
        """Clears all data associated with the given peer_id."""
        with self._lock:
            # Remove from memory
            if peer_id in self.peer_data_map:
                del self.peer_data_map[peer_id]

            # Clear peer records from memory
            if peer_id in self.peer_record_map:
                del self.peer_record_map[peer_id]

            # Clear from datastore
            self._clear_peerdata_from_datastore(peer_id)

    def valid_peer_ids(self) -> list[ID]:
        """
        :return: all of the valid peer IDs stored in peer store
        """
        valid_peer_ids: list[ID] = []
        all_peer_ids = self.peer_ids()

        for peer_id in all_peer_ids:
            try:
                peer_data = self._load_peer_data(peer_id)
                if not peer_data.is_expired():
                    valid_peer_ids.append(peer_id)
                else:
                    peer_data.clear_addrs()
                    self._save_peer_data(peer_id, peer_data)
            except Exception as e:
                logger.error(f"Error checking validity of peer {peer_id}: {e}")

        return valid_peer_ids

    def _enforce_record_limit(self) -> None:
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
                    self.datastore.delete(record_key)
                except Exception as e:
                    logger.error(f"Failed to delete peer record for {peer_id}: {e}")

    # Note: async start_cleanup_task is not implemented in sync version
    # Users should implement their own cleanup mechanism if needed
    async def start_cleanup_task(self, cleanup_interval: int = 3600) -> None:
        """Start periodic cleanup - not implemented in sync version."""
        raise NotImplementedError(
            "Cleanup task not supported in synchronous peerstore. "
            "Implement your own cleanup mechanism if needed."
        )

    # --------PROTO-BOOK--------

    def get_protocols(self, peer_id: ID) -> list[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """
        peer_data = self._load_peer_data(peer_id)
        return peer_data.get_protocols()

    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.add_protocols(list(protocols))
        self._save_peer_data(peer_id, peer_data)

    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.set_protocols(list(protocols))
        self._save_peer_data(peer_id, peer_data)

    def remove_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to get info for
        :param protocols: unsupported protocols to remove
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.remove_protocols(protocols)
        self._save_peer_data(peer_id, peer_data)

    def supports_protocols(self, peer_id: ID, protocols: Sequence[str]) -> list[str]:
        """
        :return: all of the peer IDs stored in peer store
        """
        peer_data = self._load_peer_data(peer_id)
        return peer_data.supports_protocols(protocols)

    def first_supported_protocol(self, peer_id: ID, protocols: Sequence[str]) -> str:
        peer_data = self._load_peer_data(peer_id)
        return peer_data.first_supported_protocol(protocols)

    def clear_protocol_data(self, peer_id: ID) -> None:
        """Clears protocol data"""
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_protocol_data()
        self._save_peer_data(peer_id, peer_data)

    # ------METADATA---------

    def get(self, peer_id: ID, key: str) -> MetadataValue:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """
        peer_data = self._load_peer_data(peer_id)
        try:
            return peer_data.get_metadata(key)
        except PeerDataError as error:
            raise PeerStoreError() from error

    def put(self, peer_id: ID, key: str, val: MetadataValue) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.put_metadata(key, val)
        self._save_peer_data(peer_id, peer_data)

    def clear_metadata(self, peer_id: ID) -> None:
        """Clears metadata"""
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_metadata()
        self._save_peer_data(peer_id, peer_data)

    # -----CERT-ADDR-BOOK-----

    def maybe_delete_peer_record(self, peer_id: ID) -> None:
        """
        Delete the signed peer record for a peer if it has no known
        (non-expired) addresses.
        """
        peer_data = self._load_peer_data(peer_id)
        if not peer_data.get_addrs() and peer_id in self.peer_record_map:
            # Remove from memory and datastore
            del self.peer_record_map[peer_id]
            try:
                record_key = self._get_peer_record_key(peer_id)
                self.datastore.delete(record_key)
                self.datastore.sync(b"")
            except Exception as e:
                logger.error(f"Failed to delete peer record for {peer_id}: {e}")

    def consume_peer_record(self, envelope: Envelope, ttl: int) -> bool:
        """
        Accept and store a signed PeerRecord, unless it's older than
        the one already stored.
        """
        if not _peer_record_signer_matches(envelope):
            return False

        record = envelope.record()
        peer_id = record.peer_id

        # Check if we have an existing record
        existing = self._load_peer_record(peer_id)
        if existing and existing.seq > record.seq:
            return False

        # Store the new record
        new_addrs = set(record.addrs)
        record_state = PeerRecordState(envelope, record.seq)
        self._save_peer_record(peer_id, record_state)

        # Update peer data
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_addrs()
        peer_data.add_addrs(list(new_addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()
        self._save_peer_data(peer_id, peer_data)

        return True

    def consume_peer_records(self, envelopes: list[Envelope], ttl: int) -> list[bool]:
        """Consume multiple peer records in a single operation."""
        results: list[bool] = []
        for envelope in envelopes:
            results.append(self.consume_peer_record(envelope, ttl))
        return results

    def get_peer_record(self, peer_id: ID) -> Envelope | None:
        """
        Retrieve the most recent signed PeerRecord `Envelope` for a peer, if it exists
        and is still relevant.
        """
        peer_data = self._load_peer_data(peer_id)
        if not peer_data.is_expired() and peer_data.get_addrs():
            record_state = self._load_peer_record(peer_id)
            if record_state is not None:
                return record_state.envelope
        return None

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
        peer_data = self._load_peer_data(peer_id)
        peer_data.add_addrs(list(addrs))
        peer_data.set_ttl(ttl)
        peer_data.update_last_identified()
        self._save_peer_data(peer_id, peer_data)

        self.maybe_delete_peer_record(peer_id)

    def addrs(self, peer_id: ID) -> list[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs of a valid peer.
        :raise PeerStoreError: if peer ID not found
        """
        peer_data = self._load_peer_data(peer_id)
        if not peer_data.is_expired():
            return peer_data.get_addrs()
        else:
            peer_data.clear_addrs()
            self._save_peer_data(peer_id, peer_data)
            raise PeerStoreError("peer ID is expired")

    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_addrs()
        self._save_peer_data(peer_id, peer_data)
        self.maybe_delete_peer_record(peer_id)

    def peers_with_addrs(self) -> list[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """
        output: list[ID] = []
        all_peer_ids = self.peer_ids()

        for peer_id in all_peer_ids:
            try:
                peer_data = self._load_peer_data(peer_id)
                if len(peer_data.get_addrs()) >= 1:
                    if not peer_data.is_expired():
                        output.append(peer_id)
                    else:
                        peer_data.clear_addrs()
                        self._save_peer_data(peer_id, peer_data)
            except Exception as e:
                logger.error(f"Error checking addresses for peer {peer_id}: {e}")

        return output

    # Note: addr_stream is not implemented in sync version as it requires
    # async operations
    def addr_stream(self, peer_id: ID) -> None:
        """
        Address stream not supported in synchronous peerstore.
        """
        raise NotImplementedError(
            "Address stream not supported in synchronous peerstore. "
            "Use the async peerstore implementation for streaming functionality."
        )

    # -------KEY-BOOK---------

    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID and pubkey does not match
        """
        if ID.from_pubkey(pubkey) != peer_id:
            raise PeerStoreError("peer ID and pubkey does not match")
        peer_data = self._load_peer_data(peer_id)
        peer_data.add_pubkey(pubkey)
        self._save_peer_data(peer_id, peer_data)

    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID or peer pubkey not found
        """
        peer_data = self._load_peer_data(peer_id)
        try:
            return peer_data.get_pubkey()
        except PeerDataError as e:
            raise PeerStoreError("peer pubkey not found") from e

    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        if ID.from_pubkey(privkey.get_public_key()) != peer_id:
            raise PeerStoreError("peer ID and privkey does not match")
        self.local_peer_id = peer_id
        peer_data = self._load_peer_data(peer_id)
        peer_data.add_privkey(privkey)
        self._save_peer_data(peer_id, peer_data)
        if peer_id in self.peer_data_map:
            self.peer_data_map.move_to_end(peer_id)

    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID or peer privkey not found
        """
        peer_data = self._load_peer_data(peer_id)
        try:
            return peer_data.get_privkey()
        except PeerDataError as e:
            raise PeerStoreError("peer privkey not found") from e

    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        """
        self.local_peer_id = peer_id
        self.add_pubkey(peer_id, key_pair.public_key)
        self.add_privkey(peer_id, key_pair.private_key)

    def peer_with_keys(self) -> list[ID]:
        """Returns the peer_ids for which keys are stored"""
        peer_ids_with_keys: list[ID] = []
        all_peer_ids = self.peer_ids()

        for peer_id in all_peer_ids:
            try:
                peer_data = self._load_peer_data(peer_id)
                if peer_data.pubkey is not None:
                    peer_ids_with_keys.append(peer_id)
            except Exception as e:
                logger.error(f"Error checking keys for peer {peer_id}: {e}")

        return peer_ids_with_keys

    def clear_keydata(self, peer_id: ID) -> None:
        """Clears the keys of the peer"""
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_keydata()
        self._save_peer_data(peer_id, peer_data)

    # --------METRICS--------

    def record_latency(self, peer_id: ID, RTT: float) -> None:
        """
        Records a new latency measurement for the given peer
        using Exponentially Weighted Moving Average (EWMA)
        """
        peer_data = self._load_peer_data(peer_id)
        peer_data.record_latency(RTT)
        self._save_peer_data(peer_id, peer_data)

    def latency_EWMA(self, peer_id: ID) -> float:
        """
        :param peer_id: peer ID to get private key for
        :return: The latency EWMA value for that peer
        """
        peer_data = self._load_peer_data(peer_id)
        return peer_data.latency_EWMA()

    def clear_metrics(self, peer_id: ID) -> None:
        """Clear the latency metrics"""
        peer_data = self._load_peer_data(peer_id)
        peer_data.clear_metrics()
        self._save_peer_data(peer_id, peer_data)

    def close(self) -> None:
        """Close the persistent peerstore and underlying datastore."""
        with self._lock:
            # Close the datastore
            if hasattr(self.datastore, "close"):
                self.datastore.close()

            # Clear memory caches
            self.peer_data_map.clear()
            self.peer_record_map.clear()
            self.local_peer_record = None

    def __enter__(self) -> "SyncPersistentPeerStore":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        self.close()
