"""
Value store implementation for Kademlia DHT.

Provides a way to store and retrieve key-value pairs with optional expiration.
"""

import logging
import time

import varint

from libp2p.abc import (
    IHost,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)

from .common import (
    DEFAULT_TTL,
    PROTOCOL_ID,
)
from .pb.kademlia_pb2 import (
    Message,
)

# logger = logging.getLogger("libp2p.kademlia.value_store")
logger = logging.getLogger("kademlia-example.value_store")


class ValueStore:
    """
    Store for key-value pairs in a Kademlia DHT.

    Values are stored with a timestamp and optional expiration time.
    """

    def __init__(self, host: IHost, local_peer_id: ID):
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

    def put(self, key: bytes, value: bytes, validity: float = 0.0) -> None:
        """
        Store a value in the DHT.

        :param key: The key to store the value under
        :param value: The value to store
        :param validity: validity in seconds before the value expires.
         Defaults to `DEFAULT_TTL` if set to 0.0.

        Returns
        -------
        None

        """
        if validity == 0.0:
            validity = time.time() + DEFAULT_TTL
        logger.debug(
            "Storing value for key %s... with validity %s", key.hex(), validity
        )
        self.store[key] = (value, validity)
        logger.debug(f"Stored value for key {key.hex()}")

    async def _store_at_peer(self, peer_id: ID, key: bytes, value: bytes) -> bool:
        """
        Store a value at a specific peer.

        params: peer_id: The ID of the peer to store the value at
        params: key: The key to store
        params: value: The value to store

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

            # Set message fields
            message.key = key
            message.record.key = key
            message.record.value = value
            message.record.timeReceived = str(time.time())

            # Serialize and send the protobuf message with length prefix
            proto_bytes = message.SerializeToString()
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)
            logger.debug("Sent PUT_VALUE protobuf message with varint length")
            # Read varint-prefixed response length

            length_bytes = b""
            while True:
                logger.debug("Reading varint length prefix for response...")
                b = await stream.read(1)
                if not b:
                    logger.warning("Connection closed while reading varint length")
                    return False
                length_bytes += b
                if b[0] & 0x80 == 0:
                    break
            logger.debug(f"Received varint length bytes: {length_bytes.hex()}")
            response_length = varint.decode_bytes(length_bytes)
            logger.debug("Response length: %d bytes", response_length)
            # Read response data
            response_bytes = b""
            remaining = response_length
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(
                        f"Connection closed by peer {peer_id} while reading data"
                    )
                    return False
                response_bytes += chunk
                remaining -= len(chunk)

            # Parse protobuf response
            response = Message()
            response.ParseFromString(response_bytes)

            # Check if response is valid
            if response.type == Message.MessageType.PUT_VALUE:
                if response.key:
                    result = True
            return result

        except Exception as e:
            logger.warning(f"Failed to store value at peer {peer_id}: {e}")
            return False

        finally:
            if stream:
                await stream.close()
            return result

    def get(self, key: bytes) -> bytes | None:
        """
        Retrieve a value from the DHT.

        params: key: The key to look up

        Returns
        -------
        Optional[bytes]
            The stored value, or None if not found or expired

        """
        logger.debug("Retrieving value for key %s...", key.hex()[:8])
        if key not in self.store:
            return None

        value, validity = self.store[key]
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

        return value

    async def _get_from_peer(self, peer_id: ID, key: bytes) -> bytes | None:
        """
        Retrieve a value from a specific peer.

        params: peer_id: The ID of the peer to retrieve the value from
        params: key: The key to retrieve

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

            logger.debug(f"Getting value for key {key.hex()} from peer {peer_id}")

            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])
            logger.debug(f"Opened stream to peer {peer_id} for GET_VALUE")

            # Create the GET_VALUE message using protobuf
            message = Message()
            message.type = Message.MessageType.GET_VALUE
            message.key = key

            # Serialize and send the protobuf message
            proto_bytes = message.SerializeToString()
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)

            # Read response length
            length_bytes = b""
            while True:
                b = await stream.read(1)
                if not b:
                    logger.warning("Connection closed while reading length")
                    return None
                length_bytes += b
                if b[0] & 0x80 == 0:
                    break
            response_length = varint.decode_bytes(length_bytes)
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
                logger.debug(
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
                        f"Received value for key {key.hex()} from peer {peer_id}"
                    )
                    return response.record.value

                # Handle case where value is not found but peer infos are returned
                else:
                    logger.debug(
                        f"Value not found for key {key.hex()} from peer {peer_id},"
                        f" received {len(response.closerPeers)} closer peers"
                    )
                    return None

            except Exception as proto_err:
                logger.warning(f"Failed to parse as protobuf: {proto_err}")

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


        params: key: The key to remove

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

        params: key: The key to check

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
