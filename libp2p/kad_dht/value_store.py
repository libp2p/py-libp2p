"""
Value store implementation for Kademlia DHT.

Provides a way to store and retrieve key-value pairs with optional expiration.
"""

import json
import logging
import time
from typing import (
    Optional,
)

from libp2p.abc import (
    IHost,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)

from .pb.kademlia_pb2 import (
    Message,
)

logger = logging.getLogger("libp2p.kademlia.value_store")

# Default time to live for values in seconds (24 hours)
DEFAULT_TTL = 24 * 60 * 60
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")


class ValueStore:
    """
    Store for key-value pairs in a Kademlia DHT.

    Values are stored with a timestamp and optional expiration time.
    """

    def __init__(self, host: IHost = None, local_peer_id: Optional[ID] = None):
        """
        Initialize an empty value store.

        :param host: The libp2p host instance.
        :param local_peer_id: The local peer ID to ignore in peer requests.

        """
        # Store format: {key: (value, validity)}
        self.store: dict[bytes, tuple[bytes, float]] = {}
        # Store references to the host and local peer ID for making requests
        self.host = host
        self.local_peer_id = local_peer_id

    def put(self, key: bytes, value: bytes, validity: Optional[float] = None) -> None:
        """
        Store a value in the DHT.

        :param key: The key to store the value under
        :param value: The value to store
        :param ttl: Time to live in seconds, or None for no expiration

        Returns
        -------
        None

        """
        if validity is None:
            # If no validity is provided, set a default TTL
            validity = time.time() + DEFAULT_TTL
        logger.info(
            "Storing value for key %s... with validity %s", key.hex()[:8], validity
        )
        self.store[key] = (value, validity)
        logger.debug(f"Stored value for key {key.hex()[:8]}...")

    async def _store_at_peer(self, peer_id: ID, key: str, value: bytes) -> bool:
        """
        Store a value at a specific peer.

        Args:
            peer_id: The ID of the peer to store the value at
            key: The key to store
            value: The value to store

        Returns
        -------
        bool
            True if the value was successfully stored, False otherwise

        """
        stream = None
        try:
            # Don't try to store at ourselves
            if self.local_peer_id and peer_id == self.local_peer_id:
                return True

            if not self.host:
                logger.error("Host not initialized, cannot store value at peer")
                return False

            logger.info(f"Storing value for key {key} at peer {peer_id}")

            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            logger.info(f"Opened stream to peer {peer_id}")

            # Create the PUT_VALUE message with protobuf
            message = Message()
            message.type = Message.MessageType.PUT_VALUE

            # Convert key to bytes if it's a string
            key_bytes = key if isinstance(key, bytes) else key.encode()

            # Set message fields
            message.key = key_bytes
            message.record.key = key_bytes
            message.record.value = value
            message.record.timeReceived = str(time.time())

            # Serialize and send the protobuf message with length prefix
            proto_bytes = message.SerializeToString()
            await stream.write(len(proto_bytes).to_bytes(4, "big"))
            await stream.write(proto_bytes)
            logger.info("Sent PUT_VALUE protobuf message")

            # Read response length (4 bytes)
            length_bytes = await stream.read(4)
            if len(length_bytes) < 4:
                logger.warning("Failed to read response length")
                return False

            response_length = int.from_bytes(length_bytes, byteorder="big")

            # Read response
            response_bytes = await stream.read(response_length)
            if len(response_bytes) < response_length:
                logger.warning("Failed to read complete response")
                return False

            # Parse protobuf response
            response = Message()
            response.ParseFromString(response_bytes)

            # Check if response is valid
            if response.type == Message.MessageType.PUT_VALUE:
                logger.debug(f"Successfully stored value at peer {peer_id}")
                return True

            return False

        except Exception as e:
            logger.warning(f"Failed to store value at peer {peer_id}: {e}")
            return False

        finally:
            if stream:
                await stream.close()

    def get(self, key: bytes) -> Optional[bytes]:
        """
        Retrieve a value from the DHT.

        Args:
            key: The key to look up

        Returns
        -------
        Optional[bytes]
            The stored value, or None if not found or expired

        """
        logger.info("Retrieving value for key %s...", key.hex()[:8])
        if key not in self.store:
            return None

        value, validity = self.store[key]
        logger.info(
            "Found value for key %s... with validity %s",
            key.hex()[:8],
            validity,
        )
        # Check if the value has expired
        if validity < time.time():
            self.remove(key)
            return None

        return value

    async def _get_from_peer(
        self, peer_id: ID, key: Optional[str | bytes]
    ) -> Optional[bytes]:
        """
        Retrieve a value from a specific peer.

        Args:
            peer_id: The ID of the peer to retrieve the value from
            key: The key to retrieve

        Returns
        -------
        Optional[bytes]
            The value if found, None otherwise

        """
        stream = None
        try:
            # Don't try to get from ourselves
            if peer_id == self.local_peer_id:
                return None

            logger.info(f"Getting value for key {key} from peer {peer_id}")

            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])
            logger.info(f"Opened stream to peer {peer_id} for GET_VALUE")

            # Create the GET_VALUE message using protobuf
            message = Message()
            message.type = Message.MessageType.GET_VALUE

            # Convert key to bytes if it's a string
            key_bytes = key.encode() if isinstance(key, str) else key
            message.key = key_bytes

            # Serialize and send the protobuf message
            proto_bytes = message.SerializeToString()
            await stream.write(len(proto_bytes).to_bytes(4, "big"))
            await stream.write(proto_bytes)

            # Read response length (4 bytes)
            length_bytes = b""
            remaining = 4
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(
                        f"Connection closed by peer {peer_id} while reading length"
                    )
                    return None

                length_bytes += chunk
                remaining -= len(chunk)

            response_length = int.from_bytes(length_bytes, byteorder="big")

            # Read response data
            response_bytes = b""
            remaining = response_length
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(
                        f"Connection closed by peer {peer_id} while reading data"
                    )
                    return None

                response_bytes += chunk
                remaining -= len(chunk)

            # Parse protobuf response
            try:
                response = Message()
                response.ParseFromString(response_bytes)
                logger.info(
                    f"Received protobuf response from peer"
                    f" {peer_id}, type: {response.type}"
                )

                # Process protobuf response
                if (
                    response.type == Message.MessageType.GET_VALUE
                    and response.HasField("record")
                    and response.record.value
                ):
                    logger.debug(
                        f"Received value for key {key_bytes.hex()} from peer {peer_id}"
                    )
                    return response.record.value

            except Exception as proto_err:
                # Fall back to JSON for backward compatibility
                logger.warning(f"Failed to parse as protobuf, trying JSON: {proto_err}")
                try:
                    json_response = json.loads(response_bytes.decode())
                    if (
                        json_response.get("type") == "VALUE"
                        and "value" in json_response
                    ):
                        value = json_response["value"]
                        if isinstance(value, str):
                            value = value.encode()
                        logger.debug(
                            f"Received JSON value for key {key} from peer {peer_id}"
                        )
                        return value
                except Exception as json_err:
                    logger.error(f"Failed to parse as JSON too: {json_err}")

            return None

        except Exception as e:
            logger.warning(f"Failed to get value from peer {peer_id}: {e}")
            return None

        finally:
            if stream:
                await stream.close()

    def remove(self, key: bytes) -> bool:
        """
        Remove a value from the DHT.

        Args:
            key: The key to remove

        Returns
        -------
        bool
            True if the key was found and removed, False otherwise

        """
        if key in self.store:
            del self.store[key]
            logger.debug(f"Removed value for key {key.hex()[:8]}...")
            return True
        return False

    def has(self, key: bytes) -> bool:
        """
        Check if a key exists in the store and hasn't expired.

        Args:
            key: The key to check

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
            key
            for key, (_, validity) in self.store.items()
            if validity is not None and current_time > validity
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
