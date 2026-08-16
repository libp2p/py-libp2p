"""
Value store implementation for Kademlia DHT.

Provides a way to store and retrieve key-value pairs with optional expiration.
"""

import json
import logging
from pathlib import Path
import time
from typing import Any

from multiaddr import Multiaddr
import varint

from libp2p.abc import (
    IHost,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.kad_dht.utils import maybe_consume_signed_record
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.records.record import make_signed_put_record
from libp2p.utils.varint import read_varint_prefixed_bytes_limited

from .common import (
    BUCKET_SIZE,
    DEFAULT_TTL,
    MAX_DHT_MESSAGE_SIZE,
    MAX_VALUE_STORE_SIZE,
    PROTOCOL_ID,
    format_time_rfc3339,
    parse_time_received,
)
from .pb.kademlia_pb2 import Message, Record

logger = logging.getLogger(__name__)

# Republish interval: 22 hours (same as provider records)
REPUBLISH_INTERVAL = 22 * 60 * 60


class ValueStore:
    """
    Store for key-value pairs in a Kademlia DHT.

    Values are stored with a timestamp and optional expiration time.
    """

    def __init__(self, host: IHost, local_peer_id: ID, persist_path: str | None = None):
        """
        Initialize an empty value store.

        :param host: The libp2p host instance.
        :param local_peer_id: The local peer ID to ignore in peer requests.
        :param persist_path: Optional file path for JSON persistence

        """
        # Store format: {key: (value, validity)}
        self.store: dict[bytes, tuple[Record, float]] = {}
        # Store references to the host and local peer ID for making requests
        self.host = host
        self.local_peer_id = local_peer_id
        # Track keys that were locally put (for republishing)
        self.local_keys: set[bytes] = set()
        # Track when each key was last republished
        self._last_republish: dict[bytes, float] = {}
        self._persist_path = persist_path
        # Load from disk if persistence is enabled
        if persist_path:
            self._load()

    def _save(self) -> None:
        """Save value records to disk as JSON."""
        if not self._persist_path:
            return
        data: dict[str, Any] = {}
        for key, (record, validity) in self.store.items():
            key_hex = key.hex()
            data[key_hex] = {
                "key": record.key.hex(),
                "value": record.value.hex(),
                "timeReceived": record.timeReceived,
                "validity": validity,
                "author": record.author.hex() if record.author else None,
                "signature": record.signature.hex() if record.signature else None,
            }
        # Also save local_keys
        data["_local_keys"] = [k.hex() for k in self.local_keys]
        try:
            assert self._persist_path is not None
            persist_path = Path(self._persist_path)
            persist_path.parent.mkdir(parents=True, exist_ok=True)
            with persist_path.open("w") as f:
                json.dump(data, f)
            logger.debug(
                f"Saved {len(self.store)} value records to {self._persist_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to save value records: {e}")

    def _load(self) -> None:
        """Load value records from disk."""
        if not self._persist_path or not Path(self._persist_path).exists():
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            loaded = 0
            for key_hex, record_data in data.items():
                if key_hex == "_local_keys":
                    self.local_keys = {bytes.fromhex(k) for k in record_data}
                    continue
                key = bytes.fromhex(key_hex)
                record = Record()
                record.key = bytes.fromhex(record_data["key"])
                record.value = bytes.fromhex(record_data["value"])
                record.timeReceived = record_data["timeReceived"]
                if record_data.get("author"):
                    record.author = bytes.fromhex(record_data["author"])
                if record_data.get("signature"):
                    record.signature = bytes.fromhex(record_data["signature"])
                validity = record_data["validity"]
                # Skip expired records
                if validity > time.time():
                    self.store[key] = (record, validity)
                    loaded += 1
            logger.debug(f"Loaded {loaded} value records from {self._persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load value records: {e}")

    def _evict_if_full(self) -> None:
        """Evict the oldest entry if the store exceeds max size."""
        if len(self.store) >= MAX_VALUE_STORE_SIZE:
            # Find the entry with the oldest timeReceived
            oldest_key = None
            oldest_time = float("inf")
            for key, (record, _) in self.store.items():
                time_received = parse_time_received(record.timeReceived)
                if time_received is not None:
                    if time_received < oldest_time:
                        oldest_time = time_received
                        oldest_key = key
                else:
                    # If timeReceived is invalid, treat as oldest
                    oldest_key = key
                    break
            if oldest_key is not None:
                logger.debug(
                    "Evicting oldest entry for key %s (store at capacity %d)",
                    oldest_key.hex(),
                    MAX_VALUE_STORE_SIZE,
                )
                del self.store[oldest_key]

    def put(self, key: bytes, value: bytes, validity: float = 0.0) -> None:
        """
        Store a value in the DHT.

        :param key: The key to store the value under
        :param value: The value to store
        :param validity: Absolute UNIX expiration timestamp.
         Defaults to `time.time() + DEFAULT_TTL` if set to 0.0.

        Returns
        -------
        None

        """
        if validity == 0.0:
            validity = time.time() + DEFAULT_TTL
        logger.debug(
            "Storing value for key %s... with validity %s", key.hex(), validity
        )

        # Create a signed record using the host's private key
        private_key = self.host.get_private_key()
        record = make_signed_put_record(key, value, private_key)

        # Set timeReceived when storing locally (RFC3339 per spec)
        record.timeReceived = format_time_rfc3339()

        # Evict oldest entry if store is full
        self._evict_if_full()

        self.store[key] = (record, validity)
        # Track as locally put for republishing
        self.local_keys.add(key)
        logger.debug(f"Stored value for key {key.hex()}")
        self._save()

    def put_record(self, key: bytes, record: Record) -> None:
        """
        Store a signed Record directly in the DHT without re-signing.

        Used when storing records retrieved from the network to preserve
        the original author's signature.

        :param key: The key to store the record under
        :param record: The signed Record to store
        """
        validity = time.time() + DEFAULT_TTL
        logger.debug("Storing record directly for key %s", key.hex())
        # Evict oldest entry if store is full
        self._evict_if_full()
        self.store[key] = (record, validity)
        self._save()

    async def _republish_records(self, peer_routing: Any = None) -> None:
        """
        Republish locally-stored records to the k closest peers.

        Per spec: records should be periodically republished to ensure
        they remain available in the network.

        :param peer_routing: PeerRouting instance for finding closest peers
        """
        if peer_routing is None:
            logger.debug("No peer routing available, skipping record republish")
            return

        current_time = time.time()

        # Snapshot to avoid mutation during iteration
        local_keys_snapshot = list(self.local_keys)

        for key in local_keys_snapshot:
            # Skip if not in store (may have been evicted)
            if key not in self.store:
                self.local_keys.discard(key)
                continue

            # Check if republish is due
            last_republished = self._last_republish.get(key, 0)
            if (current_time - last_republished) < REPUBLISH_INTERVAL:
                continue

            record, _ = self.store[key]
            logger.debug(f"Republishing record for key {key.hex()}")

            # Find k closest peers and store the record at each
            try:
                closest_peers = await peer_routing.find_closest_peers_network(key)
                # Store at up to k closest peers
                for peer_id in closest_peers[:BUCKET_SIZE]:
                    if peer_id == self.local_peer_id:
                        continue
                    try:
                        await self._store_at_peer(
                            peer_id, key, record.value, record=record
                        )
                    except Exception as e:
                        logger.debug(f"Failed to republish to {peer_id}: {e}")

                self._last_republish[key] = current_time
            except Exception as e:
                logger.debug(f"Failed to republish record for key {key.hex()}: {e}")

    async def _store_at_peer(
        self, peer_id: ID, key: bytes, value: bytes, record: Record | None = None
    ) -> bool:
        """
        Store a value at a specific peer.

        Parameters
        ----------
        peer_id : ID
            The ID of the peer to store the value at
        key : bytes
            The key to store
        value : bytes
            The value to store
        record : Record | None
            The original signed Record to send. If None, a new record will be
            created signed by the local peer (normal put path).

        Returns
        -------
        bool
            True if the value was successfully stored, False otherwise

        """
        result = False
        stream = None
        try:
            # Don't try to store at ourselves
            if self.local_peer_id and peer_id == self.local_peer_id:
                result = True
                return result

            if not self.host:
                logger.error("Host not initialized, cannot store value at peer")
                return False

            logger.debug(f"Storing value for key {key.hex()} at peer {peer_id}")

            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            logger.debug(f"Opened stream to peer {peer_id}")

            # Create the PUT_VALUE message with protobuf
            message = Message()
            message.type = Message.MessageType.PUT_VALUE

            # Create sender's signed-peer-record
            envelope_bytes, _ = env_to_send_in_RPC(self.host)
            message.senderRecord = envelope_bytes

            # Build the outbound record from the provided record when available
            # (entry correction path). Otherwise, create a new signed record with
            # the local peer's key (normal put path).
            if record is not None:
                message.record.CopyFrom(record)
            else:
                local_entry = self.store.get(key)
                if local_entry is not None:
                    signed_record, _ = local_entry
                    message.record.CopyFrom(signed_record)
                else:
                    private_key = self.host.get_private_key()
                    signed_record = make_signed_put_record(key, value, private_key)
                    message.record.CopyFrom(signed_record)
            message.key = key
            # Note: timeReceived will be set by the receiving peer when storing
            message.record.ClearField("timeReceived")

            # Serialize and send the protobuf message with length prefix
            proto_bytes = message.SerializeToString()
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)
            logger.debug("Sent PUT_VALUE protobuf message with varint length")
            response_bytes = await read_varint_prefixed_bytes_limited(
                stream, MAX_DHT_MESSAGE_SIZE
            )
            logger.debug("Response length: %d bytes", len(response_bytes))

            # Parse protobuf response
            response = Message()
            response.ParseFromString(response_bytes)

            # Check if response is valid
            if response.type == Message.MessageType.PUT_VALUE:
                # Consume the sender's signed-peer-record if sent
                if not maybe_consume_signed_record(response, self.host, peer_id):
                    logger.error(
                        "Received an invalid-signed-record, ignoring the response"
                    )
                    return False
                if response.key == key:
                    result = True
            return result

        except Exception as e:
            logger.warning(f"Failed to store value at peer {peer_id}: {e}")
            return False

        finally:
            if stream:
                await stream.close()

        return False

    def get(self, key: bytes) -> Record | None:
        """
        Retrieve a value from the DHT.

        Parameters
        ----------
        key : bytes
            The key to look up

        Returns
        -------
        Optional[bytes]
            The stored value, or None if not found or expired

        """
        logger.debug("Retrieving value for key %s...", key.hex()[:8])
        if key not in self.store:
            return None

        record, validity = self.store[key]
        logger.debug(
            "Found value for key %s... with validity %s",
            key.hex(),
            validity,
        )
        # Check if the value has expired
        if validity is not None and validity < time.time():
            logger.debug(
                "Value for key %s... has expired, removing it",
                key.hex()[:8],
            )
            self.remove(key)
            return None

        return record

    async def _get_from_peer(
        self,
        peer_id: ID,
        key: bytes,
        return_record: bool = False,
        return_closer_peers: bool = False,
    ) -> bytes | Record | None | tuple[bytes | Record | None, list[ID]]:
        """
        Retrieve a value from a specific peer.

        Parameters
        ----------
        peer_id : ID
            The ID of the peer to retrieve the value from
        key : bytes
            The key to retrieve
        return_record : bool
            If True, return the full Record (for quorum),
            else return just the value
        return_closer_peers : bool
            If True, return a tuple of (result, closer_peers)

        Returns
        -------
        Optional[bytes] | Optional[Record] | Tuple
            The value if found (or full Record if return_record=True), None otherwise
            If return_closer_peers, returns (result, closer_peers_list)

        """
        stream = None
        try:
            # If querying ourselves, return the local value directly
            if peer_id == self.local_peer_id:
                local_record = self.get(key)
                if local_record is None:
                    if return_closer_peers:
                        return None, []
                    return None
                result = local_record if return_record else local_record.value
                if return_closer_peers:
                    return result, []
                return result

            logger.debug(f"Getting value for key {key.hex()} from peer {peer_id}")

            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])
            logger.debug(f"Opened stream to peer {peer_id} for GET_VALUE")

            # Create the GET_VALUE message using protobuf
            message = Message()
            message.type = Message.MessageType.GET_VALUE
            message.key = key

            # Create sender's signed-peer-record
            envelope_bytes, _ = env_to_send_in_RPC(self.host)
            message.senderRecord = envelope_bytes

            # Serialize and send the protobuf message
            proto_bytes = message.SerializeToString()
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)

            response_bytes = await read_varint_prefixed_bytes_limited(
                stream, MAX_DHT_MESSAGE_SIZE
            )
            # Parse protobuf response
            try:
                response = Message()
                response.ParseFromString(response_bytes)
                logger.debug(
                    f"Received protobuf response from peer"
                    f" {peer_id}, type: {response.type}"
                )

                # Extract closer peers if requested
                closer: list[ID] = []
                if return_closer_peers:
                    for peer_proto in response.closerPeers:
                        try:
                            closer_id = ID(peer_proto.id)
                            if closer_id != self.local_peer_id:
                                closer.append(closer_id)
                                # Per spec: store addresses in peerbook
                                if peer_proto.addrs:
                                    addrs = [Multiaddr(a) for a in peer_proto.addrs]
                                    self.host.get_peerstore().add_addrs(
                                        closer_id, addrs, 600
                                    )
                        except Exception:
                            pass

                # Process protobuf response
                if (
                    response.type == Message.MessageType.GET_VALUE
                    and response.HasField("record")
                    and response.record.value
                ):
                    # Consume the sender's signed-peer-record
                    if not maybe_consume_signed_record(response, self.host, peer_id):
                        logger.error(
                            "Received an invalid-signed-record, ignoring the response"
                        )
                        if return_closer_peers:
                            return None, []
                        return None

                    logger.debug(
                        f"Received value for key {key.hex()} from peer {peer_id}"
                    )

                    # Update timeReceived to current time (RFC3339 per spec)
                    response.record.timeReceived = format_time_rfc3339()

                    result = response.record if return_record else response.record.value
                    if return_closer_peers:
                        return result, closer
                    return result

                # Handle case where value is not found but peer infos are returned
                else:
                    logger.debug(
                        f"Value not found for key {key.hex()} from peer {peer_id},"
                        f" received {len(response.closerPeers)} closer peers"
                    )
                    if return_closer_peers:
                        return None, closer
                    return None

            except Exception as proto_err:
                logger.warning(f"Failed to parse as protobuf: {proto_err}")

            if return_closer_peers:
                return None, []
            return None

        except Exception as e:
            logger.warning(f"Failed to get value from peer {peer_id}: {e}")
            if return_closer_peers:
                return None, []
            return None

        finally:
            if stream:
                await stream.close()

    def remove(self, key: bytes) -> bool:
        """
        Remove a value from the DHT.

        Parameters
        ----------
        key : bytes
            The key to remove

        Returns
        -------
        bool
            True if the key was found and removed, False otherwise

        """
        if key in self.store:
            del self.store[key]
            logger.debug(f"Removed value for key {key.hex()[:8]}...")
            self._save()
            return True
        return False

    def has(self, key: bytes) -> bool:
        """
        Check if a key exists in the store and hasn't expired.

        Parameters
        ----------
        key : bytes
            The key to check

        Returns
        -------
        bool
            True if the key exists and hasn't expired, False otherwise

        """
        if key not in self.store:
            return False

        _, validity = self.store[key]
        if validity is not None and time.time() > validity:
            self.remove(key)
            return False

        return True

    def cleanup_expired(self) -> int:
        """
        Remove all expired values from the store.

        Returns
        -------
        int
            The number of expired values that were removed

        """
        current_time = time.time()
        expired_keys = [
            key for key, (_, validity) in self.store.items() if current_time > validity
        ]

        for key in expired_keys:
            del self.store[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired values")

        return len(expired_keys)

    def get_keys(self) -> list[bytes]:
        """
        Get all non-expired keys in the store.

        Returns
        -------
        list[bytes]
            List of keys

        """
        # Clean up expired values first
        self.cleanup_expired()
        return list(self.store.keys())

    def size(self) -> int:
        """
        Get the number of items in the store (after removing expired entries).

        Returns
        -------
        int
            Number of items

        """
        self.cleanup_expired()
        return len(self.store)
