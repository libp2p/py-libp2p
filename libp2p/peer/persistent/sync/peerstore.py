"""
Synchronous persistent peerstore implementation for py-libp2p.

This module provides a synchronous persistent peerstore that stores peer data 
in a datastore backend, similar to the pstoreds implementation in go-libp2p.
All operations are purely synchronous without any async/await.
"""

from collections import defaultdict
from collections.abc import Sequence
import logging
import pickle
import threading
from typing import Any, Iterator

from multiaddr import Multiaddr

from libp2p.abc import IPeerStore
from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey
from libp2p.peer.envelope import Envelope
from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData, PeerDataError
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import PeerRecordState, PeerStoreError

from ..datastore.base_sync import IDatastoreSync

logger = logging.getLogger(__name__)


class SyncPersistentPeerStore(IPeerStore):
    """
    Synchronous persistent peerstore implementation that stores peer data in a datastore backend.

    This implementation follows the IPeerStore interface with purely synchronous operations.
    All data is persisted immediately to the datastore backend without background threads
    or async operations, similar to the pstoreds implementation in go-libp2p.
    """

    def __init__(self, datastore: IDatastoreSync, max_records: int = 10000) -> None:
        """
        Initialize synchronous persistent peerstore.

        Args:
            datastore: The synchronous datastore backend to use for persistence
            max_records: Maximum number of peer records to store

        """
        self.datastore = datastore
        self.max_records = max_records

        # In-memory caches for frequently accessed data
        self.peer_data_map: dict[ID, PeerData] = defaultdict(PeerData)
        self.peer_record_map: dict[ID, PeerRecordState] = {}
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

    def _load_peer_data(self, peer_id: ID) -> PeerData:
        """Load peer data from datastore, creating if not exists."""
        with self._lock:
            if peer_id not in self.peer_data_map:
                peer_data = PeerData()

                try:
                    # Load addresses
                    addr_key = self._get_addr_key(peer_id)
                    addr_data = self.datastore.get(addr_key)
                    if addr_data:
                        addrs = pickle.loads(addr_data)
                        peer_data.addrs = addrs

                    # Load keys
                    key_key = self._get_key_key(peer_id)
                    key_data = self.datastore.get(key_key)
                    if key_data:
                        keys = pickle.loads(key_data)
                        peer_data.pubkey = keys.get("pubkey")
                        peer_data.privkey = keys.get("privkey")

                    # Load metadata
                    metadata_key = self._get_metadata_key(peer_id)
                    metadata_data = self.datastore.get(metadata_key)
                    if metadata_data:
                        peer_data.metadata = pickle.loads(metadata_data)

                    # Load protocols
                    protocol_key = self._get_protocol_key(peer_id)
                    protocol_data = self.datastore.get(protocol_key)
                    if protocol_data:
                        peer_data.protocols = pickle.loads(protocol_data)

                    # Load additional fields
                    additional_key = self._get_additional_key(peer_id)
                    additional_data = self.datastore.get(additional_key)
                    if additional_data:
                        additional = pickle.loads(additional_data)
                        peer_data.last_identified = additional.get(
                            "last_identified", peer_data.last_identified
                        )
                        peer_data.ttl = additional.get("ttl", peer_data.ttl)
                        peer_data.latmap = additional.get("latmap", peer_data.latmap)

                except Exception as e:
                    logger.error(f"Failed to load peer data for {peer_id}: {e}")
                    # Continue with empty peer data

                self.peer_data_map[peer_id] = peer_data

            return self.peer_data_map[peer_id]

    def _save_peer_data(self, peer_id: ID, peer_data: PeerData) -> None:
        """Save peer data to datastore."""
        try:
            # Save addresses
            addr_key = self._get_addr_key(peer_id)
            self.datastore.put(addr_key, pickle.dumps(peer_data.addrs))

            # Save keys
            key_key = self._get_key_key(peer_id)
            keys = {"pubkey": peer_data.pubkey, "privkey": peer_data.privkey}
            self.datastore.put(key_key, pickle.dumps(keys))

            # Save metadata
            metadata_key = self._get_metadata_key(peer_id)
            self.datastore.put(metadata_key, pickle.dumps(peer_data.metadata))

            # Save protocols
            protocol_key = self._get_protocol_key(peer_id)
            self.datastore.put(protocol_key, pickle.dumps(peer_data.protocols))

            # Save additional fields
            additional_key = self._get_additional_key(peer_id)
            additional_data = {
                "last_identified": peer_data.last_identified,
                "ttl": peer_data.ttl,
                "latmap": peer_data.latmap,
            }
            self.datastore.put(additional_key, pickle.dumps(additional_data))

            # Sync to ensure data is persisted
            self.datastore.sync(b"")

        except Exception as e:
            raise PeerStoreError(f"Failed to save peer data for {peer_id}") from e

    def _load_peer_record(self, peer_id: ID) -> PeerRecordState | None:
        """Load peer record from datastore."""
        with self._lock:
            if peer_id not in self.peer_record_map:
                try:
                    record_key = self._get_peer_record_key(peer_id)
                    record_data = self.datastore.get(record_key)
                    if record_data:
                        record_state = pickle.loads(record_data)
                        self.peer_record_map[peer_id] = record_state
                        return record_state
                except Exception as e:
                    logger.error(f"Failed to load peer record for {peer_id}: {e}")
            return self.peer_record_map.get(peer_id)

    def _save_peer_record(self, peer_id: ID, record_state: PeerRecordState) -> None:
        """Save peer record to datastore."""
        try:
            record_key = self._get_peer_record_key(peer_id)
            self.datastore.put(record_key, pickle.dumps(record_state))
            self.peer_record_map[peer_id] = record_state
            self.datastore.sync(b"")
        except Exception as e:
            raise PeerStoreError(f"Failed to save peer record for {peer_id}") from e

    def _load_local_record(self) -> None:
        """Load local peer record from datastore."""
        try:
            local_data = self.datastore.get(self.LOCAL_RECORD_KEY)
            if local_data:
                self.local_peer_record = pickle.loads(local_data)
        except Exception as e:
            logger.error(f"Failed to load local peer record: {e}")

    def _save_local_record(self, envelope: Envelope) -> None:
        """Save local peer record to datastore."""
        try:
            self.datastore.put(self.LOCAL_RECORD_KEY, pickle.dumps(envelope))
            self.local_peer_record = envelope
            self.datastore.sync(b"")
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

    def peer_ids(self) -> list[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        # Get all peer IDs from datastore by querying all prefixes
        peer_ids = set()
        
        try:
            # Query all address keys to find peer IDs
            for key, _ in self.datastore.query(self.ADDR_PREFIX):
                if key.startswith(self.ADDR_PREFIX):
                    peer_id_bytes = key[len(self.ADDR_PREFIX):]
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

    def get(self, peer_id: ID, key: str) -> Any:
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

    def put(self, peer_id: ID, key: str, val: Any) -> None:
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

    # Note: addr_stream is not implemented in sync version as it requires async operations
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
        peer_data = self._load_peer_data(peer_id)
        peer_data.add_privkey(privkey)
        self._save_peer_data(peer_id, peer_data)

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
